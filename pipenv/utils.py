# -*- coding: utf-8 -*-
import os
import hashlib
import tempfile

import delegator
import pip
import parse
import requirements
import requests
import six

from piptools.resolver import Resolver
from piptools.repositories.pypi import PyPIRepository
from piptools.scripts.compile import get_pip_command
from piptools import logging

# List of version control systems we support.
VCS_LIST = ('git', 'svn', 'hg', 'bzr')
FILE_LIST = ('http://', 'https://', 'ftp://', 'file:///')

requests = requests.Session()


def python_version(path_to_python):
    if not path_to_python:
        return None

    try:
        c = delegator.run([path_to_python, '--version'], block=False)
    except Exception:
        return None
    output = c.out.strip() or c.err.strip()

    @parse.with_pattern(r'.*')
    def allow_empty(text):
        return text

    TEMPLATE = 'Python {}.{}.{:d}{:AllowEmpty}'
    parsed = parse.parse(TEMPLATE, output, dict(AllowEmpty=allow_empty))
    if parsed:
        parsed = parsed.fixed
    else:
        return None

    return u"{v[0]}.{v[1]}.{v[2]}".format(v=parsed)


def shellquote(s):
    """Prepares a string for the shell (on Windows too!)"""
    return '"' + s.replace("'", "'\\''") + '"'


def clean_pkg_version(version):
    """Uses pip to prepare a package version string, from our internal version."""
    return six.u(pep440_version(str(version).replace('==', '')))


class HackedPythonVersion(object):
    """A Beautiful hack, which allows us to tell pip which version of Python we're using."""
    def __init__(self, python):
        self.python = python

    def __enter__(self):
        if self.python:
            os.environ['PIP_PYTHON_VERSION'] = str(self.python)

    def __exit__(self, *args):
        # Restore original Python version information.
        if self.python:
            del os.environ['PIP_PYTHON_VERSION']


def resolve_deps(deps, sources=None, verbose=False, python=False):
    """Given a list of dependencies, return a resolved list of dependencies,
    using pip-tools -- and their hashes, using the warehouse API / pip.
    """

    with HackedPythonVersion(python):

        class PipCommand(pip.basecommand.Command):
            """Needed for pip-tools."""
            name = 'PipCommand'

        constraints = []

        for dep in deps:
            if dep.startswith('-e '):
                constraint = pip.req.InstallRequirement.from_editable(dep[len('-e '):])
            else:
                constraint = pip.req.InstallRequirement.from_line(dep)
            constraints.append(constraint)

        pip_command = get_pip_command()

        pip_args = []

        if sources:
            pip_args.extend(['-i', sources[0]['url']])

        pip_options, _ = pip_command.parse_args(pip_args)

        pypi = PyPIRepository(pip_options=pip_options, session=requests)

        if verbose:
            logging.log.verbose = True

        resolver = Resolver(constraints=constraints, repository=pypi, allow_unsafe=True, prereleases=True)
        results = []

        # pre-resolve instead of iterating to avoid asking pypi for hashes of editable packages
        resolved_tree = resolver.resolve()

    for result in resolved_tree:
        name = pep423_name(result.name)
        version = clean_pkg_version(result.specifier)

        collected_hashes = []

        try:
            # Grab the hashes from the new warehouse API.
            r = requests.get('https://pypi.org/pypi/{0}/json'.format(name))
            api_releases = r.json()['releases']

            cleaned_releases = {}
            for api_version, api_info in api_releases.items():
                cleaned_releases[clean_pkg_version(api_version)] = api_info

            for release in cleaned_releases[version]:
                collected_hashes.append(release['digests']['sha256'])

            collected_hashes = ['sha256:' + s for s in collected_hashes]

            # Collect un-collectable hashes.
            if not collected_hashes:
                collected_hashes = list(list(resolver.resolve_hashes([result]).items())[0][1])

        except (ValueError, KeyError):
            pass

        results.append({'name': name, 'version': version, 'hashes': collected_hashes})

    return results


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

    req = [r for r in requirements.parse(dep)][0]
    # File installs.
    if (req.uri or (os.path.exists(req.path) if req.path else False)) and not req.vcs:

        # Assign a package name to the file, last 7 of it's sha256 hex digest.
        hashable_path = req.uri if req.uri else req.path
        req.name = hashlib.sha256(hashable_path.encode('utf-8')).hexdigest()
        req.name = req.name[len(req.name) - 7:]

        # {file: uri} TOML (spec 3 I guess...)
        dependency[req.name] = {'file': hashable_path}

        # Add --editable if applicable
        if req.editable:
            dependency[req.name].update({'editable': True})

    # VCS Installs.
    if req.vcs:
        if req.name is None:
            raise ValueError('pipenv requires an #egg fragment for version controlled '
                             'dependencies. Please install remote dependency '
                             'in the form {0}#egg=<package-name>.'.format(req.uri))

        # Extras: e.g. #egg=requests[security]
        if req.extras:
            dependency[req.name] = {'extras': req.extras}
        # Crop off the git+, etc part.
        dependency.setdefault(req.name, {}).update({req.vcs: req.uri[len(req.vcs) + 1:]})

        # Add --editable, if it's there.
        if req.editable:
            dependency[req.name].update({'editable': True})

        # Add subdirectory, if it's there
        if req.subdirectory:
            dependency[req.name].update({'subdirectory': req.subdirectory})

        # Add the specifier, if it was provided.
        if req.revision:
            dependency[req.name].update({'ref': req.revision})

    elif req.specs or req.extras:

        specs = None
        # Comparison operators: e.g. Django>1.10
        if req.specs:
            r = multi_split(dep, '!=<>')
            specs = dep[len(r[0]):]
            dependency[req.name] = specs

        # Extras: e.g. requests[socks]
        if req.extras:
            dependency[req.name] = {'extras': req.extras}

            if specs:
                dependency[req.name].update({'version': specs})

    # Bare dependencies: e.g. requests
    else:
        dependency[dep] = '*'

    return dependency


def convert_deps_to_pip(deps, r=True):
    """"Converts a Pipfile-formatted dependency to a pip-formatted one."""

    dependencies = []

    for dep in deps.keys():

        # Default (e.g. '>1.10').
        extra = deps[dep] if isinstance(deps[dep], six.string_types) else ''
        version = ''

        # Get rid of '*'.
        if deps[dep] == '*' or str(extra) == '{}':
            extra = ''

        hash = ''
        # Support for single hash (spec 1).
        if 'hash' in deps[dep]:
            hash = ' --hash={0}'.format(deps[dep]['hash'])

        # Support for multiple hashes (spec 2).
        if 'hashes' in deps[dep]:
            hash = '{0} '.format(''.join([' --hash={0} '.format(h) for h in deps[dep]['hashes']]))

        # Support for extras (e.g. requests[socks])
        if 'extras' in deps[dep]:
            extra = '[{0}]'.format(deps[dep]['extras'][0])

        if 'version' in deps[dep]:
            version = deps[dep]['version']

        # Support for version control
        maybe_vcs = [vcs for vcs in VCS_LIST if vcs in deps[dep]]
        vcs = maybe_vcs[0] if maybe_vcs else None

        # Support for files.
        if 'file' in deps[dep]:
            extra = deps[dep]['file']

            # Flag the file as editable if it is a local relative path
            if 'editable' in deps[dep]:
                dep = '-e '
            else:
                dep = ''

        if vcs:
            extra = '{0}+{1}'.format(vcs, deps[dep][vcs])

            # Support for @refs.
            if 'ref' in deps[dep]:
                extra += '@{0}'.format(deps[dep]['ref'])

            extra += '#egg={0}'.format(dep)

            # Support for subdirectory
            if 'subdirectory' in deps[dep]:
                extra += '&subdirectory={0}'.format(deps[dep]['subdirectory'])

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


def is_file(package):
    """Determine if a package name is for a File dependency."""
    if os.path.exists(str(package)):
        return True

    for start in FILE_LIST:
        if str(package).startswith(start):
            return True

    return False


def pep440_version(version):
    """Normalize version to PEP 440 standards"""

    # Use pip built-in version parser.
    return str(pip.index.parse_version(version))


def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""

    return name.lower().replace('_', '-')


def proper_case(package_name):
    """Properly case project name from pypi.org."""

    # Hit the simple API.
    r = requests.get('https://pypi.org/pypi/{0}/json'.format(package_name), timeout=0.3, stream=True)
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
        split_file[section + '-vcs'] = vcs_dict

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
    """Mimic os.walk, but walk 'up' instead of down the directory tree.
    From: https://gist.github.com/zdavkeos/1098474
    """

    bottom = os.path.realpath(bottom)

    # Get files in current dir.
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

    # See if we are at the top.
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
