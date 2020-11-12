from __future__ import print_function
import os
import sys
from itertools import chain
from collections import defaultdict
import argparse
from operator import attrgetter
import json
from importlib import import_module

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

pardir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(pardir)
from pipenv.vendor.pip_shims import get_installed_distributions, FrozenRequirement

import pkg_resources
# inline:
# from graphviz import backend, Digraph


__version__ = '1.0.0'


flatten = chain.from_iterable


def build_dist_index(pkgs):
    """Build an index pkgs by their key as a dict.

    :param list pkgs: list of pkg_resources.Distribution instances
    :returns: index of the pkgs by the pkg key
    :rtype: dict

    """
    return dict((p.key, DistPackage(p)) for p in pkgs)


def construct_tree(index):
    """Construct tree representation of the pkgs from the index.

    The keys of the dict representing the tree will be objects of type
    DistPackage and the values will be list of ReqPackage objects.

    :param dict index: dist index ie. index of pkgs by their keys
    :returns: tree of pkgs and their dependencies
    :rtype: dict

    """
    return dict((p, [ReqPackage(r, index.get(r.key))
                     for r in p.requires()])
                for p in index.values())


def sorted_tree(tree):
    """Sorts the dict representation of the tree

    The root packages as well as the intermediate packages are sorted
    in the alphabetical order of the package names.

    :param dict tree: the pkg dependency tree obtained by calling
                     `construct_tree` function
    :returns: sorted tree
    :rtype: collections.OrderedDict

    """
    return OrderedDict(sorted([(k, sorted(v, key=attrgetter('key')))
                               for k, v in tree.items()],
                              key=lambda kv: kv[0].key))


def find_tree_root(tree, key):
    """Find a root in a tree by it's key

    :param dict tree: the pkg dependency tree obtained by calling
                     `construct_tree` function
    :param str key: key of the root node to find
    :returns: a root node if found else None
    :rtype: mixed

    """
    result = [p for p in tree.keys() if p.key == key]
    assert len(result) in [0, 1]
    return None if len(result) == 0 else result[0]


def reverse_tree(tree):
    """Reverse the dependency tree.

    ie. the keys of the resulting dict are objects of type
    ReqPackage and the values are lists of DistPackage objects.

    :param dict tree: the pkg dependency tree obtained by calling
                      `construct_tree` function
    :returns: reversed tree
    :rtype: dict

    """
    rtree = defaultdict(list)
    child_keys = set(c.key for c in flatten(tree.values()))
    for k, vs in tree.items():
        for v in vs:
            node = find_tree_root(rtree, v.key) or v
            rtree[node].append(k.as_required_by(v))
        if k.key not in child_keys:
            rtree[k.as_requirement()] = []
    return rtree


def guess_version(pkg_key, default='?'):
    """Guess the version of a pkg when pip doesn't provide it

    :param str pkg_key: key of the package
    :param str default: default version to return if unable to find
    :returns: version
    :rtype: string

    """
    try:
        m = import_module(pkg_key)
    except ImportError:
        return default
    else:
        return getattr(m, '__version__', default)


def frozen_req_from_dist(dist):
    try:
        return FrozenRequirement.from_dist(dist)
    except TypeError:
        return FrozenRequirement.from_dist(dist, [])


class Package(object):
    """Abstract class for wrappers around objects that pip returns.

    This class needs to be subclassed with implementations for
    `render_as_root` and `render_as_branch` methods.

    """

    def __init__(self, obj):
        self._obj = obj
        self.project_name = obj.project_name
        self.key = obj.key

    def render_as_root(self, frozen):
        return NotImplementedError

    def render_as_branch(self, frozen):
        return NotImplementedError

    def render(self, parent=None, frozen=False):
        if not parent:
            return self.render_as_root(frozen)
        else:
            return self.render_as_branch(frozen)

    @staticmethod
    def frozen_repr(obj):
        fr = frozen_req_from_dist(obj)
        return str(fr).strip()

    def __getattr__(self, key):
        return getattr(self._obj, key)

    def __repr__(self):
        return '<{0}("{1}")>'.format(self.__class__.__name__, self.key)


class DistPackage(Package):
    """Wrapper class for pkg_resources.Distribution instances

      :param obj: pkg_resources.Distribution to wrap over
      :param req: optional ReqPackage object to associate this
                  DistPackage with. This is useful for displaying the
                  tree in reverse
    """

    def __init__(self, obj, req=None):
        super(DistPackage, self).__init__(obj)
        self.version_spec = None
        self.req = req

    def render_as_root(self, frozen):
        if not frozen:
            return '{0}=={1}'.format(self.project_name, self.version)
        else:
            return self.__class__.frozen_repr(self._obj)

    def render_as_branch(self, frozen):
        assert self.req is not None
        if not frozen:
            parent_ver_spec = self.req.version_spec
            parent_str = self.req.project_name
            if parent_ver_spec:
                parent_str += parent_ver_spec
            return (
                '{0}=={1} [requires: {2}]'
            ).format(self.project_name, self.version, parent_str)
        else:
            return self.render_as_root(frozen)

    def as_requirement(self):
        """Return a ReqPackage representation of this DistPackage"""
        return ReqPackage(self._obj.as_requirement(), dist=self)

    def as_required_by(self, req):
        """Return a DistPackage instance associated to a requirement

        This association is necessary for displaying the tree in
        reverse.

        :param ReqPackage req: the requirement to associate with
        :returns: DistPackage instance

        """
        return self.__class__(self._obj, req)

    def as_dict(self):
        return {'key': self.key,
                'package_name': self.project_name,
                'installed_version': self.version}


class ReqPackage(Package):
    """Wrapper class for Requirements instance

      :param obj: The `Requirements` instance to wrap over
      :param dist: optional `pkg_resources.Distribution` instance for
                   this requirement
    """

    UNKNOWN_VERSION = '?'

    def __init__(self, obj, dist=None):
        super(ReqPackage, self).__init__(obj)
        self.dist = dist

    @property
    def version_spec(self):
        specs = sorted(self._obj.specs, reverse=True)  # `reverse` makes '>' prior to '<'
        return ','.join([''.join(sp) for sp in specs]) if specs else None

    @property
    def installed_version(self):
        if not self.dist:
            return guess_version(self.key, self.UNKNOWN_VERSION)
        return self.dist.version

    def is_conflicting(self):
        """If installed version conflicts with required version"""
        # unknown installed version is also considered conflicting
        if self.installed_version == self.UNKNOWN_VERSION:
            return True
        ver_spec = (self.version_spec if self.version_spec else '')
        req_version_str = '{0}{1}'.format(self.project_name, ver_spec)
        req_obj = pkg_resources.Requirement.parse(req_version_str)
        return self.installed_version not in req_obj

    def render_as_root(self, frozen):
        if not frozen:
            return '{0}=={1}'.format(self.project_name, self.installed_version)
        elif self.dist:
            return self.__class__.frozen_repr(self.dist._obj)
        else:
            return self.project_name

    def render_as_branch(self, frozen):
        if not frozen:
            req_ver = self.version_spec if self.version_spec else 'Any'
            return (
                '{0} [required: {1}, installed: {2}]'
                ).format(self.project_name, req_ver, self.installed_version)
        else:
            return self.render_as_root(frozen)

    def as_dict(self):
        return {'key': self.key,
                'package_name': self.project_name,
                'installed_version': self.installed_version,
                'required_version': self.version_spec}


def render_tree(tree, list_all=True, show_only=None, frozen=False, exclude=None):
    """Convert tree to string representation

    :param dict tree: the package tree
    :param bool list_all: whether to list all the pgks at the root
                          level or only those that are the
                          sub-dependencies
    :param set show_only: set of select packages to be shown in the
                          output. This is optional arg, default: None.
    :param bool frozen: whether or not show the names of the pkgs in
                        the output that's favourable to pip --freeze
    :param set exclude: set of select packages to be excluded from the
                          output. This is optional arg, default: None.
    :returns: string representation of the tree
    :rtype: str

    """
    tree = sorted_tree(tree)
    branch_keys = set(r.key for r in flatten(tree.values()))
    nodes = tree.keys()
    use_bullets = not frozen

    key_tree = dict((k.key, v) for k, v in tree.items())
    get_children = lambda n: key_tree.get(n.key, [])

    if show_only:
        nodes = [p for p in nodes
                 if p.key in show_only or p.project_name in show_only]
    elif not list_all:
        nodes = [p for p in nodes if p.key not in branch_keys]

    def aux(node, parent=None, indent=0, chain=None):
        if exclude and (node.key in exclude or node.project_name in exclude):
            return []
        if chain is None:
            chain = [node.project_name]
        node_str = node.render(parent, frozen)
        if parent:
            prefix = ' '*indent + ('- ' if use_bullets else '')
            node_str = prefix + node_str
        result = [node_str]
        children = [aux(c, node, indent=indent+2,
                        chain=chain+[c.project_name])
                    for c in get_children(node)
                    if c.project_name not in chain]
        result += list(flatten(children))
        return result

    lines = flatten([aux(p) for p in nodes])
    return '\n'.join(lines)


def render_json(tree, indent):
    """Converts the tree into a flat json representation.

    The json repr will be a list of hashes, each hash having 2 fields:
      - package
      - dependencies: list of dependencies

    :param dict tree: dependency tree
    :param int indent: no. of spaces to indent json
    :returns: json representation of the tree
    :rtype: str

    """
    return json.dumps([{'package': k.as_dict(),
                        'dependencies': [v.as_dict() for v in vs]}
                       for k, vs in tree.items()],
                      indent=indent)


def render_json_tree(tree, indent):
    """Converts the tree into a nested json representation.

    The json repr will be a list of hashes, each hash having the following fields:
      - package_name
      - key
      - required_version
      - installed_version
      - dependencies: list of dependencies

    :param dict tree: dependency tree
    :param int indent: no. of spaces to indent json
    :returns: json representation of the tree
    :rtype: str

    """
    tree = sorted_tree(tree)
    branch_keys = set(r.key for r in flatten(tree.values()))
    nodes = [p for p in tree.keys() if p.key not in branch_keys]
    key_tree = dict((k.key, v) for k, v in tree.items())
    get_children = lambda n: key_tree.get(n.key, [])

    def aux(node, parent=None, chain=None):
        if chain is None:
            chain = [node.project_name]

        d = node.as_dict()
        if parent:
            d['required_version'] = node.version_spec if node.version_spec else 'Any'
        else:
            d['required_version'] = d['installed_version']

        d['dependencies'] = [
            aux(c, parent=node, chain=chain+[c.project_name])
            for c in get_children(node)
            if c.project_name not in chain
        ]

        return d

    return json.dumps([aux(p) for p in nodes], indent=indent)


def dump_graphviz(tree, output_format='dot'):
    """Output dependency graph as one of the supported GraphViz output formats.

    :param dict tree: dependency graph
    :param string output_format: output format
    :returns: representation of tree in the specified output format
    :rtype: str or binary representation depending on the output format

    """
    try:
        from graphviz import backend, Digraph
    except ImportError:
        print('graphviz is not available, but necessary for the output '
              'option. Please install it.', file=sys.stderr)
        sys.exit(1)

    if output_format not in backend.FORMATS:
        print('{0} is not a supported output format.'.format(output_format),
              file=sys.stderr)
        print('Supported formats are: {0}'.format(
            ', '.join(sorted(backend.FORMATS))), file=sys.stderr)
        sys.exit(1)

    graph = Digraph(format=output_format)
    for package, deps in tree.items():
        project_name = package.project_name
        label = '{0}\n{1}'.format(project_name, package.version)
        graph.node(project_name, label=label)
        for dep in deps:
            label = dep.version_spec
            if not label:
                label = 'any'
            graph.edge(project_name, dep.project_name, label=label)

    # Allow output of dot format, even if GraphViz isn't installed.
    if output_format == 'dot':
        return graph.source

    # As it's unknown if the selected output format is binary or not, try to
    # decode it as UTF8 and only print it out in binary if that's not possible.
    try:
        return graph.pipe().decode('utf-8')
    except UnicodeDecodeError:
        return graph.pipe()


def print_graphviz(dump_output):
    """Dump the data generated by GraphViz to stdout.

    :param dump_output: The output from dump_graphviz
    """
    if hasattr(dump_output, 'encode'):
        print(dump_output)
    else:
        with os.fdopen(sys.stdout.fileno(), 'wb') as bytestream:
            bytestream.write(dump_output)


def conflicting_deps(tree):
    """Returns dependencies which are not present or conflict with the
    requirements of other packages.

    e.g. will warn if pkg1 requires pkg2==2.0 and pkg2==1.0 is installed

    :param tree: the requirements tree (dict)
    :returns: dict of DistPackage -> list of unsatisfied/unknown ReqPackage
    :rtype: dict

    """
    conflicting = defaultdict(list)
    for p, rs in tree.items():
        for req in rs:
            if req.is_conflicting():
                conflicting[p].append(req)
    return conflicting


def cyclic_deps(tree):
    """Return cyclic dependencies as list of tuples

    :param list pkgs: pkg_resources.Distribution instances
    :param dict pkg_index: mapping of pkgs with their respective keys
    :returns: list of tuples representing cyclic dependencies
    :rtype: generator

    """
    key_tree = dict((k.key, v) for k, v in tree.items())
    get_children = lambda n: key_tree.get(n.key, [])
    cyclic = []
    for p, rs in tree.items():
        for req in rs:
            if p.key in map(attrgetter('key'), get_children(req)):
                cyclic.append((p, req, p))
    return cyclic


def get_parser():
    parser = argparse.ArgumentParser(description=(
        'Dependency tree of the installed python packages'
    ))
    parser.add_argument('-v', '--version', action='version',
                        version='{0}'.format(__version__))
    parser.add_argument('-f', '--freeze', action='store_true',
                        help='Print names so as to write freeze files')
    parser.add_argument('-a', '--all', action='store_true',
                        help='list all deps at top level')
    parser.add_argument('-l', '--local-only',
                        action='store_true', help=(
                            'If in a virtualenv that has global access '
                            'do not show globally installed packages'
                        ))
    parser.add_argument('-u', '--user-only', action='store_true',
                        help=(
                            'Only show installations in the user site dir'
                        ))
    parser.add_argument('-w', '--warn', action='store', dest='warn',
                        nargs='?', default='suppress',
                        choices=('silence', 'suppress', 'fail'),
                        help=(
                            'Warning control. "suppress" will show warnings '
                            'but return 0 whether or not they are present. '
                            '"silence" will not show warnings at all and '
                            'always return 0. "fail" will show warnings and '
                            'return 1 if any are present. The default is '
                            '"suppress".'
                        ))
    parser.add_argument('-r', '--reverse', action='store_true',
                        default=False, help=(
                            'Shows the dependency tree in the reverse fashion '
                            'ie. the sub-dependencies are listed with the '
                            'list of packages that need them under them.'
                        ))
    parser.add_argument('-p', '--packages',
                        help=(
                            'Comma separated list of select packages to show '
                            'in the output. If set, --all will be ignored.'
                        ))
    parser.add_argument('-e', '--exclude',
                        help=(
                            'Comma separated list of select packages to exclude '
                            'from the output. If set, --all will be ignored.'
                        ), metavar='PACKAGES')
    parser.add_argument('-j', '--json', action='store_true', default=False,
                        help=(
                            'Display dependency tree as json. This will yield '
                            '"raw" output that may be used by external tools. '
                            'This option overrides all other options.'
                        ))
    parser.add_argument('--json-tree', action='store_true', default=False,
                        help=(
                            'Display dependency tree as json which is nested '
                            'the same way as the plain text output printed by default. '
                            'This option overrides all other options (except --json).'
                        ))
    parser.add_argument('--graph-output', dest='output_format',
                        help=(
                            'Print a dependency graph in the specified output '
                            'format. Available are all formats supported by '
                            'GraphViz, e.g.: dot, jpeg, pdf, png, svg'
                        ))
    return parser


def _get_args():
    parser = get_parser()
    return parser.parse_args()


def main():
    args = _get_args()
    pkgs = get_installed_distributions(local_only=args.local_only,
                                       user_only=args.user_only)

    dist_index = build_dist_index(pkgs)
    tree = construct_tree(dist_index)

    if args.json:
        print(render_json(tree, indent=4))
        return 0
    elif args.json_tree:
        print(render_json_tree(tree, indent=4))
        return 0
    elif args.output_format:
        output = dump_graphviz(tree, output_format=args.output_format)
        print_graphviz(output)
        return 0

    return_code = 0

    # show warnings about possibly conflicting deps if found and
    # warnings are enabled
    if args.warn != 'silence':
        conflicting = conflicting_deps(tree)
        if conflicting:
            print('Warning!!! Possibly conflicting dependencies found:',
                  file=sys.stderr)
            for p, reqs in conflicting.items():
                pkg = p.render_as_root(False)
                print('* {}'.format(pkg), file=sys.stderr)
                for req in reqs:
                    req_str = req.render_as_branch(False)
                    print(' - {}'.format(req_str), file=sys.stderr)
            print('-'*72, file=sys.stderr)

        cyclic = cyclic_deps(tree)
        if cyclic:
            print('Warning!! Cyclic dependencies found:', file=sys.stderr)
            for a, b, c in cyclic:
                print('* {0} => {1} => {2}'.format(a.project_name,
                                                   b.project_name,
                                                   c.project_name),
                      file=sys.stderr)
            print('-'*72, file=sys.stderr)

        if args.warn == 'fail' and (conflicting or cyclic):
            return_code = 1

    show_only = set(args.packages.split(',')) if args.packages else None
    exclude = set(args.exclude.split(',')) if args.exclude else None

    if show_only and exclude and (show_only & exclude):
        print('Conflicting packages found in --packages and --exclude lists.', file=sys.stderr)
        sys.exit(1)

    tree = render_tree(tree if not args.reverse else reverse_tree(tree),
                       list_all=args.all, show_only=show_only,
                       frozen=args.freeze, exclude=exclude)
    print(tree)
    return return_code


if __name__ == '__main__':
    sys.exit(main())
