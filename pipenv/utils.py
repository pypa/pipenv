# -*- coding: utf-8 -*-
import os
import tempfile

import parse
import requests
import six

# List of version control systems we support.
VCS_LIST = ('git', 'svn', 'hg', 'bzr')

requests = requests.session()


def format_toml(data):
    """Pretty-formats a given toml string."""
    data = data.split('\n')
    for i, line in enumerate(data):
        if i > 0:
            if line.startswith('['):
                data[i] = '\n{0}'.format(line)

    return '\n'.join(data)


def multi_split(s, split):
    """Splits on multiple given separators."""
    for r in split:
        s = s.replace(r, '|')

    return [i for i in s.split('|') if len(i) > 0]


def convert_deps_from_pip(dep):
    """"Converts a pip-formatted dependency to a Pipfile-formatted one."""
    dependency = {}

    import requirements
    req = [r for r in requirements.parse(dep)][0]

    # VCS Installs.
    if req.vcs:
        if req.name is None:
            raise ValueError('pipenv requires an #egg fragment for version controlled '
                             'dependencies. Please install remote dependency '
                             'in the form {0}#egg=<package-name>.'.format(req.uri))

        # Crop off the git+, etc part.
        dependency[req.name] = {req.vcs: req.uri[len(req.vcs) + 1:]}

        # Add --editable, if it's there.
        if req.editable:
            dependency[req.name].update({'editable': True})

        # Add the specifier, if it was provided.
        if req.revision:
            dependency[req.name].update({'ref': req.revision})

    elif req.specs or req.extras:

        specs = None
        # Comparison operators: e.g. Django>1.10
        if req.specs:
            r = multi_split(dep, '=<>')
            specs = dep[len(r[0]):]
            dependency[req.name] = specs

        # Extras: e.g. requests[socks]
        if req.extras:
            r = multi_split(dep, '[]')
            dependency[req.name] = {'extras': req.extras}

            if specs:
                dependency[req.name].update({'version': specs})

    # Bare dependencies: e.g. requests
    else:
        dependency[dep] = '*'

    return dependency


def convert_deps_to_pip(deps, r=True):
    """"Converts a Pipfile-formatteddependency to a pip-formatted one."""
    dependencies = []

    for dep in deps.keys():

        # Default (e.g. '>1.10').
        extra = deps[dep] if isinstance(deps[dep], six.string_types) else ''
        version = ''

        # Get rid of '*'.
        if deps[dep] == '*' or str(extra) == '{}':
            extra = ''

        hash = ''
        if 'hash' in deps[dep]:
            hash = ' --hash={0}'.format(deps[dep]['hash'])

        # Support for extras (e.g. requests[socks])
        if 'extras' in deps[dep]:
            extra = '[{0}]'.format(deps[dep]['extras'][0])

        if 'version' in deps[dep]:
            version = deps[dep]['version']

        # Support for version control
        maybe_vcs = [vcs for vcs in VCS_LIST if vcs in deps[dep]]
        vcs = maybe_vcs[0] if maybe_vcs else None

        if vcs:
            extra = '{0}+{1}'.format(vcs, deps[dep][vcs])

            # Support for @refs.
            if 'ref' in deps[dep]:
                extra += '@{0}'.format(deps[dep]['ref'])

            extra += '#egg={0}'.format(dep)

            # Support for editable.
            if 'editable' in deps[dep]:
                # Support for --egg.
                dep = '-e '
            else:
                dep = ''

        dependencies.append('{0}{1}{2}{3}'.format(dep, extra, version, hash))

    if not r:
        return dependencies

    # Write requirements.txt to tmp directory.
    f = tempfile.NamedTemporaryFile(suffix='-requirements.txt', delete=False)
    f.write('\n'.join(dependencies).encode('utf-8'))
    return f.name


def mkdir_p(newdir):
    """works the way a good mkdir should :)
        - already exists, silently complete
        - regular file in the way, raise an exception
        - parent directory(ies) does not exist, make them as well
        From: http://code.activestate.com/recipes/82465-a-friendly-mkdir/
    """
    if os.path.isdir(newdir):
        pass
    elif os.path.isfile(newdir):
        raise OSError("a file with the same name as the desired dir, '{0}', already exists.".format(newdir))
    else:
        head, tail = os.path.split(newdir)
        if head and not os.path.isdir(head):
            mkdir_p(head)
        if tail:
            os.mkdir(newdir)


def is_required_version(version, specified_version):
    """Check to see if there's a hard requirement for version
    number provided in the Pipfile.
    """
    # Certain packages may be defined with multiple values.
    if isinstance(specified_version, dict):
        specified_version = specified_version.get('version', '')
    if specified_version.startswith('=='):
        return version.strip() == specified_version.split('==')[1].strip()
    return True


def is_vcs(pipfile_entry):
    """Determine if dictionary entry from Pipfile is for a vcs dependency."""
    if isinstance(pipfile_entry, dict):
        return any(key for key in pipfile_entry.keys() if key in VCS_LIST)
    return False


def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""
    return name.lower().replace('_','-')


def proper_case(package_name):
    """Properly case project name from pypi.org"""
    # Hit the simple API.
    r = requests.get('https://pypi.org/pypi/{0}/json'.format(package_name), timeout=1, stream=True)
    if not r.ok:
        raise IOError('Unable to find package {0} in PyPI repository.'.format(package_name))

    r = parse.parse('https://pypi.org/pypi/{name}/json', r.url)
    good_name = r['name']

    return good_name


def split_vcs(split_file):
    """Split VCS dependencies out from file."""
    if 'packages' in split_file or 'dev-packages' in split_file:
        sections = ('packages', 'dev-packages')
    elif 'default' in split_file or 'develop' in split_file:
        sections = ('default', 'develop')

    # For each vcs entry in a given section, move it to section-vcs.
    for section in sections:
        entries = split_file.get(section, {})
        vcs_dict = dict((k, entries.pop(k)) for k in list(entries.keys()) if is_vcs(entries[k]))
        split_file[section+'-vcs'] = vcs_dict

    return split_file


def recase_file(file_dict):
    """Recase file before writing to output."""
    if 'packages' in file_dict or 'dev-packages' in file_dict:
        sections = ('packages', 'dev-packages')
    elif 'default' in file_dict or 'develop' in file_dict:
        sections = ('default', 'develop')

    for section in sections:
        file_section = file_dict.get(section, {})

        # Try to properly case each key if we can.
        for key in list(file_section.keys()):
            try:
                cased_key = proper_case(key)
            except IOError:
                cased_key = key
            file_section[cased_key] = file_section.pop(key)

    return file_dict


def walk_up(bottom):
    """mimic os.walk, but walk 'up' instead of down the directory tree.
    From: https://gist.github.com/zdavkeos/1098474
    """

    bottom = os.path.realpath(bottom)

    # get files in current dir
    try:
        names = os.listdir(bottom)
    except Exception:
        return

    dirs, nondirs = [], []
    for name in names:
        if os.path.isdir(os.path.join(bottom, name)):
            dirs.append(name)
        else:
            nondirs.append(name)

    yield bottom, dirs, nondirs

    new_path = os.path.realpath(os.path.join(bottom, '..'))

    # see if we are at the top
    if new_path == bottom:
        return

    for x in walk_up(new_path):
        yield x


def find_requirements(max_depth=3):
        """Returns the path of a Pipfile in parent directories."""
        i = 0
        for c, d, f in walk_up(os.getcwd()):
            i += 1

            if i < max_depth:
                if 'requirements.txt':
                    r = os.path.join(c, 'requirements.txt')
                    if os.path.isfile(r):
                        return r
        raise RuntimeError('No requirements.txt found!')
