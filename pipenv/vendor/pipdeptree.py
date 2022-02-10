from __future__ import print_function
import os
import inspect
import sys
import subprocess
from itertools import chain
from collections import defaultdict, deque
import argparse
from operator import attrgetter
import json
from importlib import import_module
import tempfile

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

try:
    from collections.abc import Mapping
except ImportError:
    from collections import Mapping

pardir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(pardir)
from pipenv.vendor.pip_shims.shims import get_installed_distributions, FrozenRequirement

import pkg_resources
# inline:
# from graphviz import backend, Digraph


__version__ = '2.0.0'


flatten = chain.from_iterable


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
        v = getattr(m, '__version__', default)
        if inspect.ismodule(v):
            return getattr(v, '__version__', default)
        else:
            return v


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

    def as_parent_of(self, req):
        """Return a DistPackage instance associated to a requirement

        This association is necessary for reversing the PackageDAG.

        If `req` is None, and the `req` attribute of the current
        instance is also None, then the same instance will be
        returned.

        :param ReqPackage req: the requirement to associate with
        :returns: DistPackage instance

        """
        if req is None and self.req is None:
            return self
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

    @property
    def is_missing(self):
        return self.installed_version == self.UNKNOWN_VERSION

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


class PackageDAG(Mapping):
    """Representation of Package dependencies as directed acyclic graph
    using a dict (Mapping) as the underlying datastructure.

    The nodes and their relationships (edges) are internally
    stored using a map as follows,

    {a: [b, c],
     b: [d],
     c: [d, e],
     d: [e],
     e: [],
     f: [b],
     g: [e, f]}

    Here, node `a` has 2 children nodes `b` and `c`. Consider edge
    direction from `a` -> `b` and `a` -> `c` respectively.

    A node is expected to be an instance of a subclass of
    `Package`. The keys are must be of class `DistPackage` and each
    item in values must be of class `ReqPackage`. (See also
    ReversedPackageDAG where the key and value types are
    interchanged).

    """

    @classmethod
    def from_pkgs(cls, pkgs):
        pkgs = [DistPackage(p) for p in pkgs]
        idx = {p.key: p for p in pkgs}
        m = {p: [ReqPackage(r, idx.get(r.key))
                 for r in p.requires()]
             for p in pkgs}
        return cls(m)

    def __init__(self, m):
        """Initialize the PackageDAG object

        :param dict m: dict of node objects (refer class docstring)
        :returns: None
        :rtype: NoneType

        """
        self._obj = m
        self._index = {p.key: p for p in list(self._obj)}

    def get_node_as_parent(self, node_key):
        """Get the node from the keys of the dict representing the DAG.

        This method is useful if the dict representing the DAG
        contains different kind of objects in keys and values. Use
        this method to lookup a node obj as a parent (from the keys of
        the dict) given a node key.

        :param node_key: identifier corresponding to key attr of node obj
        :returns: node obj (as present in the keys of the dict)
        :rtype: Object

        """
        try:
            return self._index[node_key]
        except KeyError:
            return None

    def get_children(self, node_key):
        """Get child nodes for a node by it's key

        :param str node_key: key of the node to get children of
        :returns: list of child nodes
        :rtype: ReqPackage[]

        """
        node = self.get_node_as_parent(node_key)
        return self._obj[node] if node else []

    def filter(self, include, exclude):
        """Filters nodes in a graph by given parameters

        If a node is included, then all it's children are also
        included.

        :param set include: set of node keys to include (or None)
        :param set exclude: set of node keys to exclude (or None)
        :returns: filtered version of the graph
        :rtype: PackageDAG

        """
        # If neither of the filters are specified, short circuit
        if include is None and exclude is None:
            return self

        # Note: In following comparisons, we use lower cased values so
        # that user may specify `key` or `project_name`. As per the
        # documentation, `key` is simply
        # `project_name.lower()`. Refer:
        # https://setuptools.readthedocs.io/en/latest/pkg_resources.html#distribution-objects
        if include:
            include = set([s.lower() for s in include])
        if exclude:
            exclude = set([s.lower() for s in exclude])
        else:
            exclude = set([])

        # Check for mutual exclusion of show_only and exclude sets
        # after normalizing the values to lowercase
        if include and exclude:
            assert not (include & exclude)

        # Traverse the graph in a depth first manner and filter the
        # nodes according to `show_only` and `exclude` sets
        stack = deque()
        m = {}
        seen = set([])
        for node in self._obj.keys():
            if node.key in exclude:
                continue
            if include is None or node.key in include:
                stack.append(node)
            while True:
                if len(stack) > 0:
                    n = stack.pop()
                    cldn = [c for c in self._obj[n]
                            if c.key not in exclude]
                    m[n] = cldn
                    seen.add(n.key)
                    for c in cldn:
                        if c.key not in seen:
                            cld_node = self.get_node_as_parent(c.key)
                            if cld_node:
                                stack.append(cld_node)
                            else:
                                # It means there's no root node
                                # corresponding to the child node
                                # ie. a dependency is missing
                                continue
                else:
                    break

        return self.__class__(m)

    def reverse(self):
        """Reverse the DAG, or turn it upside-down

        In other words, the directions of edges of the nodes in the
        DAG will be reversed.

        Note that this function purely works on the nodes in the
        graph. This implies that to perform a combination of filtering
        and reversing, the order in which `filter` and `reverse`
        methods should be applied is important. For eg. if reverse is
        called on a filtered graph, then only the filtered nodes and
        it's children will be considered when reversing. On the other
        hand, if filter is called on reversed DAG, then the definition
        of "child" nodes is as per the reversed DAG.

        :returns: DAG in the reversed form
        :rtype: ReversedPackageDAG

        """
        m = defaultdict(list)
        child_keys = set(r.key for r in flatten(self._obj.values()))
        for k, vs in self._obj.items():
            for v in vs:
                # if v is already added to the dict, then ensure that
                # we are using the same object. This check is required
                # as we're using array mutation
                try:
                    node = [p for p in m.keys() if p.key == v.key][0]
                except IndexError:
                    node = v
                m[node].append(k.as_parent_of(v))
            if k.key not in child_keys:
                m[k.as_requirement()] = []
        return ReversedPackageDAG(dict(m))

    def sort(self):
        """Return sorted tree in which the underlying _obj dict is an
        OrderedDict, sorted alphabetically by the keys

        :returns: Instance of same class with OrderedDict

        """
        return self.__class__(sorted_tree(self._obj))

    # Methods required by the abstract base class Mapping
    def __getitem__(self, *args):
        return self._obj.get(*args)

    def __iter__(self):
        return self._obj.__iter__()

    def __len__(self):
        return len(self._obj)


class ReversedPackageDAG(PackageDAG):
    """Representation of Package dependencies in the reverse
    order.

    Similar to it's super class `PackageDAG`, the underlying
    datastructure is a dict, but here the keys are expected to be of
    type `ReqPackage` and each item in the values of type
    `DistPackage`.

    Typically, this object will be obtained by calling
    `PackageDAG.reverse`.

    """

    def reverse(self):
        """Reverse the already reversed DAG to get the PackageDAG again

        :returns: reverse of the reversed DAG
        :rtype: PackageDAG

        """
        m = defaultdict(list)
        child_keys = set(r.key for r in flatten(self._obj.values()))
        for k, vs in self._obj.items():
            for v in vs:
                try:
                    node = [p for p in m.keys() if p.key == v.key][0]
                except IndexError:
                    node = v.as_parent_of(None)
                m[node].append(k)
            if k.key not in child_keys:
                m[k.dist] = []
        return PackageDAG(dict(m))


def render_text(tree, list_all=True, frozen=False):
    """Print tree as text on console

    :param dict tree: the package tree
    :param bool list_all: whether to list all the pgks at the root
                          level or only those that are the
                          sub-dependencies
    :param bool frozen: whether or not show the names of the pkgs in
                        the output that's favourable to pip --freeze
    :returns: None

    """
    tree = tree.sort()
    nodes = tree.keys()
    branch_keys = set(r.key for r in flatten(tree.values()))
    use_bullets = not frozen

    if not list_all:
        nodes = [p for p in nodes if p.key not in branch_keys]

    def aux(node, parent=None, indent=0, chain=None):
        chain = chain or []
        node_str = node.render(parent, frozen)
        if parent:
            prefix = ' '*indent + ('- ' if use_bullets else '')
            node_str = prefix + node_str
        result = [node_str]
        children = [aux(c, node, indent=indent+2,
                        chain=chain+[c.project_name])
                    for c in tree.get_children(node.key)
                    if c.project_name not in chain]
        result += list(flatten(children))
        return result

    lines = flatten([aux(p) for p in nodes])
    print('\n'.join(lines))


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
    tree = tree.sort()
    branch_keys = set(r.key for r in flatten(tree.values()))
    nodes = [p for p in tree.keys() if p.key not in branch_keys]

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
            for c in tree.get_children(node.key)
            if c.project_name not in chain
        ]

        return d

    return json.dumps([aux(p) for p in nodes], indent=indent)


def dump_graphviz(tree, output_format='dot', is_reverse=False):
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

    if not is_reverse:
        for pkg, deps in tree.items():
            pkg_label = '{0}\\n{1}'.format(pkg.project_name, pkg.version)
            graph.node(pkg.key, label=pkg_label)
            for dep in deps:
                edge_label = dep.version_spec or 'any'
                if dep.is_missing:
                    dep_label = '{0}\\n(missing)'.format(dep.project_name)
                    graph.node(dep.key, label=dep_label, style='dashed')
                    graph.edge(pkg.key, dep.key, style='dashed')
                else:
                    graph.edge(pkg.key, dep.key, label=edge_label)
    else:
        for dep, parents in tree.items():
            dep_label = '{0}\\n{1}'.format(dep.project_name,
                                          dep.installed_version)
            graph.node(dep.key, label=dep_label)
            for parent in parents:
                # req reference of the dep associated with this
                # particular parent package
                req_ref = parent.req
                edge_label = req_ref.version_spec or 'any'
                graph.edge(dep.key, parent.key, label=edge_label)

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


def render_conflicts_text(conflicts):
    if conflicts:
        print('Warning!!! Possibly conflicting dependencies found:',
              file=sys.stderr)
        # Enforce alphabetical order when listing conflicts
        pkgs = sorted(conflicts.keys(), key=attrgetter('key'))
        for p in pkgs:
            pkg = p.render_as_root(False)
            print('* {}'.format(pkg), file=sys.stderr)
            for req in conflicts[p]:
                req_str = req.render_as_branch(False)
                print(' - {}'.format(req_str), file=sys.stderr)


def cyclic_deps(tree):
    """Return cyclic dependencies as list of tuples

    :param PackageDAG pkgs: package tree/dag
    :returns: list of tuples representing cyclic dependencies
    :rtype: list

    """
    index = {p.key: set([r.key for r in rs]) for p, rs in tree.items()}
    cyclic = []
    for p, rs in tree.items():
        for r in rs:
            if p.key in index.get(r.key, []):
                p_as_dep_of_r = [x for x
                                 in tree.get(tree.get_node_as_parent(r.key))
                                 if x.key == p.key][0]
                cyclic.append((p, r, p_as_dep_of_r))
    return cyclic


def render_cycles_text(cycles):
    if cycles:
        print('Warning!! Cyclic dependencies found:', file=sys.stderr)
        # List in alphabetical order of the dependency that's cycling
        # (2nd item in the tuple)
        cycles = sorted(cycles, key=lambda xs: xs[1].key)
        for a, b, c in cycles:
            print('* {0} => {1} => {2}'.format(a.project_name,
                                               b.project_name,
                                               c.project_name),
                  file=sys.stderr)


def get_parser():
    parser = argparse.ArgumentParser(description=(
        'Dependency tree of the installed python packages'
    ))
    parser.add_argument('-v', '--version', action='version',
                        version='{0}'.format(__version__))
    parser.add_argument('-f', '--freeze', action='store_true',
                        help='Print names so as to write freeze files')
    parser.add_argument('--python', default=sys.executable,
                        help='Python to use to look for packages in it (default: where'
                             ' installed)')
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


def handle_non_host_target(args):
    of_python = os.path.abspath(args.python)
    # if target is not current python re-invoke it under the actual host
    if of_python != os.path.abspath(sys.executable):
        # there's no way to guarantee that graphviz is available, so refuse
        if args.output_format:
            print("graphviz functionality is not supported when querying"
                  " non-host python", file=sys.stderr)
            raise SystemExit(1)
        argv = sys.argv[1:]  # remove current python executable
        for py_at, value in enumerate(argv):
            if value == "--python":
                del argv[py_at]
                del argv[py_at]
            elif value.startswith("--python"):
                del argv[py_at]
        # feed the file as argument, instead of file
        # to avoid adding the file path to sys.path, that can affect result
        file_path = inspect.getsourcefile(sys.modules[__name__])
        with open(file_path, 'rt') as file_handler:
            content = file_handler.read()
        cmd = [of_python, "-c", content]
        cmd.extend(argv)
        # invoke from an empty folder to avoid cwd altering sys.path
        cwd = tempfile.mkdtemp()
        try:
            return subprocess.call(cmd, cwd=cwd)
        finally:
            os.removedirs(cwd)
    return None


def main():
    args = _get_args()
    result = handle_non_host_target(args)
    if result is not None:
        return result
    pkgs = get_installed_distributions(local_only=args.local_only,
                                       user_only=args.user_only)

    tree = PackageDAG.from_pkgs(pkgs)

    is_text_output = not any([args.json, args.json_tree, args.output_format])

    return_code = 0

    # Before any reversing or filtering, show warnings to console
    # about possibly conflicting or cyclic deps if found and warnings
    # are enabled (ie. only if output is to be printed to console)
    if is_text_output and args.warn != 'silence':
        conflicts = conflicting_deps(tree)
        if conflicts:
            render_conflicts_text(conflicts)
            print('-'*72, file=sys.stderr)

        cycles = cyclic_deps(tree)
        if cycles:
            render_cycles_text(cycles)
            print('-'*72, file=sys.stderr)

        if args.warn == 'fail' and (conflicts or cycles):
            return_code = 1

    # Reverse the tree (if applicable) before filtering, thus ensuring
    # that the filter will be applied on ReverseTree
    if args.reverse:
        tree = tree.reverse()

    show_only = set(args.packages.split(',')) if args.packages else None
    exclude = set(args.exclude.split(',')) if args.exclude else None

    if show_only is not None or exclude is not None:
        tree = tree.filter(show_only, exclude)

    if args.json:
        print(render_json(tree, indent=4))
    elif args.json_tree:
        print(render_json_tree(tree, indent=4))
    elif args.output_format:
        output = dump_graphviz(tree,
                               output_format=args.output_format,
                               is_reverse=args.reverse)
        print_graphviz(output)
    else:
        render_text(tree, args.all, args.freeze)

    return return_code


if __name__ == '__main__':
    sys.exit(main())
