# -*- coding: utf-8 -*-
import errno
import os
import re
import hashlib
import tempfile
import sys
import shutil
import logging
import crayons
import parse
import six
import stat
import warnings
from click import echo as click_echo

from first import first
try:
    from weakref import finalize
except ImportError:
    try:
        from .vendor.backports.weakref import finalize
    except ImportError:
        class finalize(object):
            def __init__(self, *args, **kwargs):
                logging.warn('weakref.finalize unavailable, not cleaning...')

            def detach(self):
                return False

from time import time

logging.basicConfig(level=logging.ERROR)
try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
try:
    from pathlib import Path
except ImportError:
    try:
        from .vendor.pathlib2 import Path
    except ImportError:
        pass
from distutils.spawn import find_executable
from contextlib import contextmanager
from .pep508checker import lookup
from .environments import PIPENV_MAX_ROUNDS, PIPENV_CACHE_DIR

if six.PY2:

    class ResourceWarning(Warning):
        pass


specifiers = [k for k in lookup.keys()]
# List of version control systems we support.
VCS_LIST = ('git', 'svn', 'hg', 'bzr')
SCHEME_LIST = ('http://', 'https://', 'ftp://', 'ftps://', 'file://')
requests_session = None


def _get_requests_session():
    """Load requests lazily."""
    global requests_session
    if requests_session is not None:
        return requests_session
    import requests
    requests_session = requests.Session()
    return requests_session


def get_requirement(dep):
    from .vendor.pip9.req.req_install import _strip_extras, Wheel
    from .vendor.pip9.index import Link
    from .vendor import requirements
    """Pre-clean requirement strings passed to the requirements parser.

    Ensures that we can accept both local and relative paths, file and VCS URIs,
    remote URIs, and package names, and that we pass only valid requirement strings
    to the requirements parser. Performs necessary modifications to requirements
    object if the user input was a local relative path.

    :param str dep: A requirement line
    :returns: :class:`requirements.Requirement` object
    """
    path = None
    uri = None
    cleaned_uri = None
    editable = False
    dep_link = None
    # check for editable dep / vcs dep
    if dep.startswith('-e '):
        editable = True
        # Use the user supplied path as the written dependency
        dep = dep.split(' ', 1)[1]
    # Split out markers if they are present - similar to how pip does it
    # See pip9.req.req_install.InstallRequirement.from_line
    if not any(dep.startswith(uri_prefix) for uri_prefix in SCHEME_LIST):
        marker_sep = ';'
    else:
        marker_sep = '; '
    if marker_sep in dep:
        dep, markers = dep.split(marker_sep, 1)
        markers = markers.strip()
        if not markers:
            markers = None
    else:
        markers = None
    # Strip extras from the requirement so we can make a properly parseable req
    dep, extras = _strip_extras(dep)
    # Only operate on local, existing, non-URI formatted paths which are installable
    if is_installable_file(dep):
        dep_path = Path(dep)
        dep_link = Link(dep_path.absolute().as_uri())
        if dep_path.is_absolute() or dep_path.as_posix() == '.':
            path = dep_path.as_posix()
        else:
            path = get_converted_relative_path(dep)
        dep = dep_link.egg_fragment if dep_link.egg_fragment else dep_link.url_without_fragment
    elif is_vcs(dep):
        # Generate a Link object for parsing egg fragments
        dep_link = Link(dep)
        # Save the original path to store in the pipfile
        uri = dep_link.url
        # Construct the requirement using proper git+ssh:// replaced uris or names if available
        cleaned_uri = clean_git_uri(dep)
        dep = cleaned_uri
    if editable:
        dep = '-e {0}'.format(dep)
    req = [r for r in requirements.parse(dep)][0]
    # if all we built was the requirement name and still need everything else
    if req.name and not any([req.uri, req.path]):
        if dep_link:
            if dep_link.scheme.startswith('file') and path and not req.path:
                req.path = path
                req.local_file = True
                req.uri = None
            else:
                req.uri = dep_link.url_without_fragment
    # If the result is a local file with a URI and we have a local path, unset the URI
    # and set the path instead -- note that local files may have 'path' set by accident
    elif req.local_file and path and not req.vcs:
        req.path = path
        req.uri = None
        if dep_link and dep_link.is_wheel and not req.name:
            req.name = os.path.basename(Wheel(dep_link.path).name)
    elif req.vcs and req.uri and cleaned_uri and cleaned_uri != uri:
        req.uri = strip_ssh_from_git_uri(req.uri)
        req.line = strip_ssh_from_git_uri(req.line)
    req.editable = editable
    if markers:
        req.markers = markers
    if extras:
        # Bizarrely this is also what pip does...
        req.extras = [
            r for r in requirements.parse('fakepkg{0}'.format(extras))
        ][
            0
        ].extras
    return req


def cleanup_toml(tml):
    toml = tml.split('\n')
    new_toml = []
    # Remove all empty lines from TOML.
    for line in toml:
        if line.strip():
            new_toml.append(line)
    toml = '\n'.join(new_toml)
    new_toml = []
    # Add newlines between TOML sections.
    for i, line in enumerate(toml.split('\n')):
        # Skip the first line.
        if line.startswith('['):
            if i > 0:
                # Insert a newline before the heading.
                new_toml.append('')
        new_toml.append(line)
    # adding new line at the end of the TOML file
    new_toml.append('')
    toml = '\n'.join(new_toml)
    return toml


def parse_python_version(output):
    """Parse a Python version output returned by `python --version`.

    Return a dict with three keys: major, minor, and micro. Each value is a
    string containing a version part.

    Note: The micro part would be `'0'` if it's missing from the input string.
    """
    version_line = output.split('\n', 1)[0]
    version_pattern = re.compile(r'''
        ^                   # Beginning of line.
        Python              # Literally "Python".
        \s                  # Space.
        (?P<major>\d+)      # Major = one or more digits.
        \.                  # Dot.
        (?P<minor>\d+)      # Minor = one or more digits.
        (?:                 # Unnamed group for dot-micro.
            \.              # Dot.
            (?P<micro>\d+)  # Micro = one or more digit.
        )?                  # Micro is optional because pypa/pipenv#1893.
        .*                  # Trailing garbage.
        $                   # End of line.
    ''', re.VERBOSE)

    match = version_pattern.match(version_line)
    if not match:
        return None
    return match.groupdict(default='0')


def python_version(path_to_python):
    import delegator
    if not path_to_python:
        return None
    try:
        c = delegator.run([path_to_python, '--version'], block=False)
    except Exception:
        return None
    c.block()
    version = parse_python_version(c.out.strip() or c.err.strip())
    try:
        version = u'{major}.{minor}.{micro}'.format(**version)
    except TypeError:
        return None
    return version


def escape_grouped_arguments(s):
    """Prepares a string for the shell (on Windows too!)

    Only for use on grouped arguments (passed as a string to Popen)
    """
    if s is None:
        return None

    # Additional escaping for windows paths
    if os.name == 'nt':
        s = "{}".format(s.replace("\\", "\\\\"))
    return '"' + s.replace("'", "'\\''") + '"'


def clean_pkg_version(version):
    """Uses pip to prepare a package version string, from our internal version."""
    return six.u(pep440_version(str(version).replace('==', '')))


class HackedPythonVersion(object):
    """A Beautiful hack, which allows us to tell pip which version of Python we're using."""

    def __init__(self, python_version, python_path):
        self.python_version = python_version
        self.python_path = python_path

    def __enter__(self):
        os.environ['PIP_PYTHON_VERSION'] = str(self.python_version)
        os.environ['PIP_PYTHON_PATH'] = str(self.python_path)

    def __exit__(self, *args):
        # Restore original Python version information.
        del os.environ['PIP_PYTHON_VERSION']


def prepare_pip_source_args(sources, pip_args=None):
    if pip_args is None:
        pip_args = []
    if sources:
        # Add the source to pip9.
        pip_args.extend(['-i', sources[0]['url']])
        # Trust the host if it's not verified.
        if not sources[0].get('verify_ssl', True):
            pip_args.extend(
                [
                    '--trusted-host',
                    urlparse(sources[0]['url']).netloc.split(':')[0],
                ]
            )
        # Add additional sources as extra indexes.
        if len(sources) > 1:
            for source in sources[1:]:
                pip_args.extend(['--extra-index-url', source['url']])
                # Trust the host if it's not verified.
                if not source.get('verify_ssl', True):
                    pip_args.extend(
                        [
                            '--trusted-host',
                            urlparse(source['url']).hostname,
                        ]
                    )
    return pip_args


def actually_resolve_reps(
    deps, index_lookup, markers_lookup, project, sources, verbose, clear, pre
):
    from pip9 import basecommand, req
    from pip9._vendor import requests as pip_requests
    from pip9.exceptions import DistributionNotFound
    from pip9._vendor.requests.exceptions import HTTPError
    from pipenv.patched.piptools.resolver import Resolver
    from pipenv.patched.piptools.repositories.pypi import PyPIRepository
    from pipenv.patched.piptools.scripts.compile import get_pip_command
    from pipenv.patched.piptools import logging as piptools_logging
    from pipenv.patched.piptools.exceptions import NoCandidateFound

    class PipCommand(basecommand.Command):
        """Needed for pip-tools."""
        name = 'PipCommand'

    constraints = []
    req_dir = tempfile.mkdtemp(prefix='pipenv-', suffix='-requirements')
    for dep in deps:
        if dep:
            if dep.startswith('-e '):
                constraint = req.InstallRequirement.from_editable(
                    dep[len('-e '):]
                )
            else:
                fd, t = tempfile.mkstemp(
                    prefix='pipenv-', suffix='-requirement.txt', dir=req_dir
                )
                with os.fdopen(fd, 'w') as f:
                    f.write(dep)
                constraint = [
                    c for c in req.parse_requirements(t, session=pip_requests)
                ][
                    0
                ]
            # extra_constraints = []
            if ' -i ' in dep:
                index_lookup[constraint.name] = project.get_source(
                    url=dep.split(' -i ')[1]
                ).get(
                    'name'
                )
            if constraint.markers:
                markers_lookup[constraint.name] = str(
                    constraint.markers
                ).replace(
                    '"', "'"
                )
            constraints.append(constraint)
    rmtree(req_dir)
    pip_command = get_pip_command()
    pip_args = []
    if sources:
        pip_args = prepare_pip_source_args(sources, pip_args)
    if verbose:
        print('Using pip: {0}'.format(' '.join(pip_args)))
    pip_options, _ = pip_command.parse_args(pip_args)
    session = pip_command._build_session(pip_options)
    pypi = PyPIRepository(
        pip_options=pip_options, use_json=False, session=session
    )
    if verbose:
        logging.log.verbose = True
        piptools_logging.log.verbose = True
    resolved_tree = set()
    resolver = Resolver(
        constraints=constraints,
        repository=pypi,
        clear_caches=clear,
        prereleases=pre,
    )
    # pre-resolve instead of iterating to avoid asking pypi for hashes of editable packages
    try:
        resolved_tree.update(resolver.resolve(max_rounds=PIPENV_MAX_ROUNDS))
    except (NoCandidateFound, DistributionNotFound, HTTPError) as e:
        click_echo(
            '{0}: Your dependencies could not be resolved. You likely have a mismatch in your sub-dependencies.\n  '
            'You can use {1} to bypass this mechanism, then run {2} to inspect the situation.'
            ''
            'Hint: try {3} if it is a pre-release dependency'
            ''.format(
                crayons.red('Warning', bold=True),
                crayons.red('$ pipenv install --skip-lock'),
                crayons.red('$ pipenv graph'),
                crayons.red('$ pipenv lock --pre'),
            ),
            err=True,
        )
        click_echo(crayons.blue(str(e)), err=True)
        if 'no version found at all' in str(e):
            click_echo(
                crayons.blue(
                    'Please check your version specifier and version number. See PEP440 for more information.'
                )
            )
        raise RuntimeError

    return resolved_tree, resolver


def venv_resolve_deps(
    deps, which, project, pre=False, verbose=False, clear=False, allow_global=False
):
    import delegator
    from . import resolver
    import json

    resolver = escape_grouped_arguments(resolver.__file__.rstrip('co'))
    cmd = '{0} {1} {2} {3} {4} {5}'.format(
        escape_grouped_arguments(which('python', allow_global=allow_global)),
        resolver,
        '--pre' if pre else '',
        '--verbose' if verbose else '',
        '--clear' if clear else '',
        '--system' if allow_global else '',
    )
    os.environ['PIPENV_PACKAGES'] = '\n'.join(deps)
    c = delegator.run(cmd, block=True)
    del os.environ['PIPENV_PACKAGES']
    try:
        assert c.return_code == 0
    except AssertionError:
        if verbose:
            click_echo(c.out, err=True)
            click_echo(c.err, err=True)
        else:
            click_echo(c.err[int(len(c.err) / 2) - 1:], err=True)
        sys.exit(c.return_code)
    if verbose:
        click_echo(c.out.split('RESULTS:')[0], err=True)
    try:
        return json.loads(c.out.split('RESULTS:')[1].strip())

    except IndexError:
        raise RuntimeError('There was a problem with locking.')


def resolve_deps(
    deps,
    which,
    project,
    sources=None,
    verbose=False,
    python=False,
    clear=False,
    pre=False,
    allow_global=False,
):
    """Given a list of dependencies, return a resolved list of dependencies,
    using pip-tools -- and their hashes, using the warehouse API / pip9.
    """
    from pip9._vendor.requests.exceptions import ConnectionError

    index_lookup = {}
    markers_lookup = {}
    python_path = which('python', allow_global=allow_global)
    backup_python_path = sys.executable
    results = []
    # First (proper) attempt:
    with HackedPythonVersion(python_version=python, python_path=python_path):
        try:
            resolved_tree, resolver = actually_resolve_reps(
                deps,
                index_lookup,
                markers_lookup,
                project,
                sources,
                verbose,
                clear,
                pre,
            )
        except RuntimeError:
            # Don't exit here, like usual.
            resolved_tree = None
    # Second (last-resort) attempt:
    if resolved_tree is None:
        with HackedPythonVersion(
            python_version='.'.join([str(s) for s in sys.version_info[:3]]),
            python_path=backup_python_path,
        ):
            try:
                # Attempt to resolve again, with different Python version information,
                # particularly for particularly particular packages.
                resolved_tree, resolver = actually_resolve_reps(
                    deps,
                    index_lookup,
                    markers_lookup,
                    project,
                    sources,
                    verbose,
                    clear,
                    pre,
                )
            except RuntimeError:
                sys.exit(1)
    for result in resolved_tree:
        if not result.editable:
            name = pep423_name(result.name)
            version = clean_pkg_version(result.specifier)
            index = index_lookup.get(result.name)
            if not markers_lookup.get(result.name):
                markers = str(
                    result.markers
                ) if result.markers and 'extra' not in str(
                    result.markers
                ) else None
            else:
                markers = markers_lookup.get(result.name)
            collected_hashes = []
            if any('python.org' in source['url'] or 'pypi.org' in source['url']
                   for source in sources):
                try:
                    # Grab the hashes from the new warehouse API.
                    r = _get_requests_session().get(
                        'https://pypi.org/pypi/{0}/json'.format(name),
                        timeout=10,
                    )
                    api_releases = r.json()['releases']
                    cleaned_releases = {}
                    for api_version, api_info in api_releases.items():
                        cleaned_releases[
                            clean_pkg_version(api_version)
                        ] = api_info
                    for release in cleaned_releases[version]:
                        collected_hashes.append(release['digests']['sha256'])
                    collected_hashes = [
                        'sha256:' + s for s in collected_hashes
                    ]
                except (ValueError, KeyError, ConnectionError):
                    if verbose:
                        click_echo(
                            '{0}: Error generating hash for {1}'.format(
                                crayons.red('Warning', bold=True), name
                            )
                        )
            # Collect un-collectable hashes (should work with devpi).
            try:
                collected_hashes = collected_hashes + list(
                    list(resolver.resolve_hashes([result]).items())[0][1]
                )
            except (ValueError, KeyError, ConnectionError, IndexError):
                if verbose:
                    print('Error generating hash for {}'.format(name))
            collected_hashes = sorted(set(collected_hashes))
            d = {'name': name, 'version': version, 'hashes': collected_hashes}
            if index:
                d.update({'index': index})
            if markers:
                d.update({'markers': markers.replace('"', "'")})
            results.append(d)
    return results


def multi_split(s, split):
    """Splits on multiple given separators."""
    for r in split:
        s = s.replace(r, '|')
    return [i for i in s.split('|') if len(i) > 0]


def convert_deps_from_pip(dep):
    """"Converts a pip-formatted dependency to a Pipfile-formatted one."""
    dependency = {}
    req = get_requirement(dep)
    extras = {'extras': req.extras}
    # File installs.
    if (req.uri or req.path or is_installable_file(req.name)) and not req.vcs:
        # Assign a package name to the file, last 7 of it's sha256 hex digest.

        if not req.uri and not req.path:
            req.path = os.path.abspath(req.name)

        hashable_path = req.uri if req.uri else req.path
        if not req.name:
            req.name = hashlib.sha256(hashable_path.encode('utf-8')).hexdigest()
            req.name = req.name[len(req.name) - 7:]
        # {path: uri} TOML (spec 4 I guess...)
        if req.uri:
            dependency[req.name] = {'file': hashable_path}
        else:
            dependency[req.name] = {'path': hashable_path}
        if req.extras:
            dependency[req.name].update(extras)
        # Add --editable if applicable
        if req.editable:
            dependency[req.name].update({'editable': True})
    # VCS Installs.
    elif req.vcs:
        if req.name is None:
            raise ValueError(
                'pipenv requires an #egg fragment for version controlled '
                'dependencies. Please install remote dependency '
                'in the form {0}#egg=<package-name>.'.format(req.uri)
            )

        # Crop off the git+, etc part.
        if req.uri.startswith('{0}+'.format(req.vcs)):
            req.uri = req.uri[len(req.vcs) + 1:]
        dependency.setdefault(req.name, {}).update({req.vcs: req.uri})
        # Add --editable, if it's there.
        if req.editable:
            dependency[req.name].update({'editable': True})
        # Add subdirectory, if it's there
        if req.subdirectory:
            dependency[req.name].update({'subdirectory': req.subdirectory})
        # Add the specifier, if it was provided.
        if req.revision:
            dependency[req.name].update({'ref': req.revision})
        # Extras: e.g. #egg=requests[security]
        if req.extras:
            dependency[req.name].update({'extras': req.extras})
    elif req.extras or req.specs or hasattr(req, 'markers'):
        specs = None
        # Comparison operators: e.g. Django>1.10
        if req.specs:
            r = multi_split(dep, '!=<>~')
            specs = dep[len(r[0]):]
            dependency[req.name] = specs
        # Extras: e.g. requests[socks]
        if req.extras:
            dependency[req.name] = extras
            if specs:
                dependency[req.name].update({'version': specs})
        if hasattr(req, 'markers'):
            if isinstance(dependency[req.name], six.string_types):
                dependency[req.name] = {'version': specs}
            dependency[req.name].update({'markers': req.markers})
    # Bare dependencies: e.g. requests
    else:
        dependency[dep] = '*'
    # Cleanup when there's multiple values, e.g. -e.
    if len(dependency) > 1:
        for key in dependency.copy():
            if not hasattr(dependency[key], 'keys'):
                del dependency[key]
    return dependency


def is_star(val):
    return isinstance(val, six.string_types) and val == '*'


def is_pinned(val):
    return isinstance(val, six.string_types) and val.startswith('==')


def convert_deps_to_pip(deps, project=None, r=True, include_index=False):
    """"Converts a Pipfile-formatted dependency to a pip-formatted one."""
    dependencies = []
    for dep in deps.keys():
        # Default (e.g. '>1.10').
        extra = deps[dep] if isinstance(deps[dep], six.string_types) else ''
        version = ''
        index = ''
        # Get rid of '*'.
        if is_star(deps[dep]) or str(extra) == '{}':
            extra = ''
        hash = ''
        # Support for single hash (spec 1).
        if 'hash' in deps[dep]:
            hash = ' --hash={0}'.format(deps[dep]['hash'])
        # Support for multiple hashes (spec 2).
        if 'hashes' in deps[dep]:
            hash = '{0} '.format(
                ''.join(
                    [' --hash={0} '.format(h) for h in deps[dep]['hashes']]
                )
            )
        # Support for extras (e.g. requests[socks])
        if 'extras' in deps[dep]:
            extra = '[{0}]'.format(','.join(deps[dep]['extras']))
        if 'version' in deps[dep]:
            if not is_star(deps[dep]['version']):
                version = deps[dep]['version']
        # For lockfile format.
        if 'markers' in deps[dep]:
            specs = '; {0}'.format(deps[dep]['markers'])
        else:
            # For pipfile format.
            specs = []
            for specifier in specifiers:
                if specifier in deps[dep]:
                    if not is_star(deps[dep][specifier]):
                        specs.append(
                            '{0} {1}'.format(specifier, deps[dep][specifier])
                        )
            if specs:
                specs = '; {0}'.format(' and '.join(specs))
            else:
                specs = ''
        if include_index and not is_file(deps[dep]) and not is_vcs(deps[dep]):
            pip_src_args = []
            if 'index' in deps[dep]:
                pip_src_args = [project.get_source(deps[dep]['index'])]
                for idx in project.sources:
                    if idx['url'] != pip_src_args[0]['url']:
                        pip_src_args.append(idx)
            else:
                pip_src_args = project.sources
            pip_args = prepare_pip_source_args(pip_src_args)
            index = ' '.join(pip_args)
        # Support for version control
        maybe_vcs = [vcs for vcs in VCS_LIST if vcs in deps[dep]]
        vcs = maybe_vcs[0] if maybe_vcs else None
        # Support for files.
        if 'file' in deps[dep]:
            extra = '{1}{0}'.format(extra, deps[dep]['file']).strip()
            # Flag the file as editable if it is a local relative path
            if 'editable' in deps[dep]:
                dep = '-e '
            else:
                dep = ''
        # Support for paths.
        elif 'path' in deps[dep]:
            extra = '{1}{0}'.format(extra, deps[dep]['path']).strip()
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
        s = '{0}{1}{2}{3}{4} {5}'.format(
            dep, extra, version, specs, hash, index
        ).strip()
        dependencies.append(s)
    if not r:
        return dependencies

    # Write requirements.txt to tmp directory.
    f = tempfile.NamedTemporaryFile(suffix='-requirements.txt', delete=False)
    f.write('\n'.join(dependencies).encode('utf-8'))
    f.close()
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
        raise OSError(
            "a file with the same name as the desired dir, '{0}', already exists.".format(
                newdir
            )
        )

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


def strip_ssh_from_git_uri(uri):
    """Return git+ssh:// formatted URI to git+git@ format"""
    if isinstance(uri, six.string_types):
        uri = uri.replace('git+ssh://', 'git+')
    return uri


def clean_git_uri(uri):
    """Cleans VCS uris from pip9 format"""
    if isinstance(uri, six.string_types):
        # Add scheme for parsing purposes, this is also what pip does
        if uri.startswith('git+') and '://' not in uri:
            uri = uri.replace('git+', 'git+ssh://')
    return uri


def is_editable(pipfile_entry):
    if hasattr(pipfile_entry, 'get'):
        return pipfile_entry.get('editable', False) and any(
            pipfile_entry.get(key) for key in ('file', 'path') + VCS_LIST
        )
    return False


def is_vcs(pipfile_entry):
    from .vendor import requirements

    """Determine if dictionary entry from Pipfile is for a vcs dependency."""
    if hasattr(pipfile_entry, 'keys'):
        return any(key for key in pipfile_entry.keys() if key in VCS_LIST)

    elif isinstance(pipfile_entry, six.string_types):
        return bool(
            requirements.requirement.VCS_REGEX.match(
                clean_git_uri(pipfile_entry)
            )
        )

    return False


def is_installable_file(path):
    """Determine if a path can potentially be installed"""
    from .vendor.pip9.utils import is_installable_dir
    from .vendor.pip9.utils.packaging import specifiers
    from .vendor.pip9.download import is_archive_file

    if hasattr(path, 'keys') and any(
        key for key in path.keys() if key in ['file', 'path']
    ):
        path = urlparse(path['file']).path if 'file' in path else path['path']
    if not isinstance(path, six.string_types) or path == '*':
        return False

    # If the string starts with a valid specifier operator, test if it is a valid
    # specifier set before making a path object (to avoid breaking windows)
    if any(path.startswith(spec) for spec in '!=<>~'):
        try:
            specifiers.SpecifierSet(path)
        # If this is not a valid specifier, just move on and try it as a path
        except specifiers.InvalidSpecifier:
            pass
        else:
            return False

    if not os.path.exists(os.path.abspath(path)):
        return False

    lookup_path = Path(path)
    absolute_path = '{0}'.format(lookup_path.absolute())
    if lookup_path.is_dir() and is_installable_dir(absolute_path):
        return True

    elif lookup_path.is_file() and is_archive_file(absolute_path):
        return True

    return False


def is_file(package):
    """Determine if a package name is for a File dependency."""
    if hasattr(package, 'keys'):
        return any(key for key in package.keys() if key in ['file', 'path'])

    if os.path.exists(str(package)):
        return True

    for start in SCHEME_LIST:
        if str(package).startswith(start):
            return True

    return False


def pep440_version(version):
    """Normalize version to PEP 440 standards"""
    from .vendor.pip9.index import parse_version

    # Use pip built-in version parser.
    return str(parse_version(version))


def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""
    name = name.lower()
    if any(i not in name for i in (VCS_LIST + SCHEME_LIST)):
        return name.replace('_', '-')

    else:
        return name


def proper_case(package_name):
    """Properly case project name from pypi.org."""
    # Hit the simple API.
    r = _get_requests_session().get(
        'https://pypi.org/pypi/{0}/json'.format(package_name),
        timeout=0.3,
        stream=True,
    )
    if not r.ok:
        raise IOError(
            'Unable to find package {0} in PyPI repository.'.format(
                package_name
            )
        )

    r = parse.parse('https://pypi.org/pypi/{name}/json', r.url)
    good_name = r['name']
    return good_name


def split_section(input_file, section_suffix, test_function):
    """
    Split a pipfile or a lockfile section out by section name and test function

        :param dict input_file: A dictionary containing either a pipfile or lockfile
        :param str section_suffix: A string of the name of the section
        :param func test_function: A test function to test against the value in the key/value pair

    >>> split_section(my_lockfile, 'vcs', is_vcs)
    {
        'default': {
            "six": {
                "hashes": [
                    "sha256:832dc0e10feb1aa2c68dcc57dbb658f1c7e65b9b61af69048abc87a2db00a0eb",
                    "sha256:70e8a77beed4562e7f14fe23a786b54f6296e34344c23bc42f07b15018ff98e9"
                ],
                "version": "==1.11.0"
            }
        },
        'default-vcs': {
            "e1839a8": {
                "editable": true,
                "path": "."
            }
        }
    }
    """
    pipfile_sections = ('packages', 'dev-packages')
    lockfile_sections = ('default', 'develop')
    if any(section in input_file for section in pipfile_sections):
        sections = pipfile_sections
    elif any(section in input_file for section in lockfile_sections):
        sections = lockfile_sections
    else:
        # return the original file if we can't find any pipfile or lockfile sections
        return input_file

    for section in sections:
        split_dict = {}
        entries = input_file.get(section, {})
        for k in list(entries.keys()):
            if test_function(entries.get(k)):
                split_dict[k] = entries.pop(k)
        input_file['-'.join([section, section_suffix])] = split_dict
    return input_file


def split_file(file_dict):
    """Split VCS and editable dependencies out from file."""
    sections = {
        'vcs': is_vcs,
        'editable': lambda x: hasattr(x, 'keys') and x.get('editable'),
    }
    for k, func in sections.items():
        file_dict = split_section(file_dict, k, func)
    return file_dict


def merge_deps(
    file_dict,
    project,
    dev=False,
    requirements=False,
    ignore_hashes=False,
    blocking=False,
    only=False,
):
    """
    Given a file_dict, merges dependencies and converts them to pip dependency lists.
        :param dict file_dict: The result of calling :func:`pipenv.utils.split_file`
        :param :class:`pipenv.project.Project` project: Pipenv project
        :param bool dev=False: Flag indicating whether dev dependencies are to be installed
        :param bool requirements=False: Flag indicating whether to use a requirements file
        :param bool ignore_hashes=False:
        :param bool blocking=False:
        :param bool only=False:
        :return: Pip-converted 3-tuples of [deps, requirements_deps]
    """
    deps = []
    requirements_deps = []
    for section in list(file_dict.keys()):
        # Turn develop-vcs into ['develop', 'vcs']
        section_name, suffix = section.rsplit(
            '-', 1
        ) if '-' in section and not section == 'dev-packages' else (
            section, None
        )
        if not file_dict[section] or section_name not in (
            'dev-packages', 'packages', 'default', 'develop'
        ):
            continue

        is_dev = section_name in ('dev-packages', 'develop')
        if is_dev and not dev:
            continue

        if ignore_hashes:
            for k, v in file_dict[section]:
                if 'hash' in v:
                    del v['hash']
        # Block and ignore hashes for all suffixed sections (vcs/editable)
        no_hashes = True if suffix else ignore_hashes
        block = True if suffix else blocking
        include_index = True if not suffix else False
        converted = convert_deps_to_pip(
            file_dict[section], project, r=False, include_index=include_index
        )
        deps.extend((d, no_hashes, block) for d in converted)
        if dev and is_dev and requirements:
            requirements_deps.extend((d, no_hashes, block) for d in converted)
    return deps, requirements_deps


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


def get_windows_path(*args):
    """Sanitize a path for windows environments

    Accepts an arbitrary list of arguments and makes a clean windows path"""
    return os.path.normpath(os.path.join(*args))


def find_windows_executable(bin_path, exe_name):
    """Given an executable name, search the given location for an executable"""
    requested_path = get_windows_path(bin_path, exe_name)
    if os.path.exists(requested_path):
        return requested_path

    # Ensure we aren't adding two layers of file extensions
    exe_name = os.path.splitext(exe_name)[0]
    files = [
        '{0}.{1}'.format(exe_name, ext) for ext in ['', 'py', 'exe', 'bat']
    ]
    exec_paths = [get_windows_path(bin_path, f) for f in files]
    exec_files = [
        filename for filename in exec_paths if os.path.isfile(filename)
    ]
    if exec_files:
        return exec_files[0]

    return find_executable(exe_name)


def path_to_url(path):
    return Path(normalize_drive(os.path.abspath(path))).as_uri()


def get_converted_relative_path(path, relative_to=os.curdir):
    """Given a vague relative path, return the path relative to the given location"""
    return os.path.join('.', os.path.relpath(path, start=relative_to))


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


# Borrowed from pew to avoid importing pew which imports psutil
# See https://github.com/berdario/pew/blob/master/pew/_utils.py#L82
@contextmanager
def temp_environ():
    """Allow the ability to set os.environ temporarily"""
    environ = dict(os.environ)
    try:
        yield

    finally:
        os.environ.clear()
        os.environ.update(environ)


def is_valid_url(url):
    """Checks if a given string is an url"""
    pieces = urlparse(url)
    return all([pieces.scheme, pieces.netloc])


def download_file(url, filename):
    """Downloads file from url to a path with filename"""
    r = _get_requests_session().get(url, stream=True)
    if not r.ok:
        raise IOError('Unable to download file')

    with open(filename, 'wb') as f:
        f.write(r.content)


def need_update_check():
    """Determines whether we need to check for updates."""
    mkdir_p(PIPENV_CACHE_DIR)
    p = os.sep.join((PIPENV_CACHE_DIR, '.pipenv_update_check'))
    if not os.path.exists(p):
        return True

    out_of_date_time = time() - (24 * 60 * 60)
    if os.path.isfile(p) and os.path.getmtime(p) <= out_of_date_time:
        return True

    else:
        return False


def touch_update_stamp():
    """Touches PIPENV_CACHE_DIR/.pipenv_update_check"""
    mkdir_p(PIPENV_CACHE_DIR)
    p = os.sep.join((PIPENV_CACHE_DIR, '.pipenv_update_check'))
    try:
        os.utime(p, None)
    except OSError:
        with open(p, 'w') as fh:
            fh.write('')


def normalize_drive(path):
    """Normalize drive in path so they stay consistent.

    This currently only affects local drives on Windows, which can be
    identified with either upper or lower cased drive names. The case is
    always converted to uppercase because it seems to be preferred.

    See: <https://github.com/pypa/pipenv/issues/1218>
    """
    if os.name != 'nt' or not isinstance(path, six.string_types):
        return path

    drive, tail = os.path.splitdrive(path)
    # Only match (lower cased) local drives (e.g. 'c:'), not UNC mounts.
    if drive.islower() and len(drive) == 2 and drive[1] == ':':
        return '{}{}'.format(drive.upper(), tail)

    return path


def is_readonly_path(fn):
    """Check if a provided path exists and is readonly.

    Permissions check is `bool(path.stat & stat.S_IREAD)` or `not os.access(path, os.W_OK)`
    """
    if os.path.exists(fn):
        return (os.stat(fn).st_mode & stat.S_IREAD) or not os.access(
            fn, os.W_OK
        )

    return False


def set_write_bit(fn):
    if os.path.exists(fn):
        os.chmod(fn, stat.S_IWRITE | stat.S_IWUSR)
    return


def rmtree(directory, ignore_errors=False):
    shutil.rmtree(
        directory, ignore_errors=ignore_errors, onerror=handle_remove_readonly
    )


def handle_remove_readonly(func, path, exc):
    """Error handler for shutil.rmtree.

    Windows source repo folders are read-only by default, so this error handler
    attempts to set them as writeable and then proceed with deletion."""
    # Check for read-only attribute
    default_warning_message = 'Unable to remove file due to permissions restriction: {!r}'
    # split the initial exception out into its type, exception, and traceback
    exc_type, exc_exception, exc_tb = exc
    if is_readonly_path(path):
        # Apply write permission and call original function
        set_write_bit(path)
        try:
            func(path)
        except (OSError, IOError) as e:
            if e.errno in [errno.EACCES, errno.EPERM]:
                warnings.warn(
                    default_warning_message.format(path), ResourceWarning
                )
                return

    if exc_exception.errno in [errno.EACCES, errno.EPERM]:
        warnings.warn(default_warning_message.format(path), ResourceWarning)
        return

    raise


class TemporaryDirectory(object):
    """Create and return a temporary directory.  This has the same
    behavior as mkdtemp but can be used as a context manager.  For
    example:

        with TemporaryDirectory() as tmpdir:
            ...

    Upon exiting the context, the directory and everything contained
    in it are removed.
    """

    def __init__(self, suffix, prefix, dir=None):
        if 'RAM_DISK' in os.environ:
            import uuid

            name = uuid.uuid4().hex
            dir_name = os.path.join(os.environ['RAM_DISK'].strip(), name)
            os.mkdir(dir_name)
            self.name = dir_name
        else:
            self.name = tempfile.mkdtemp(suffix, prefix, dir)
        self._finalizer = finalize(
            self,
            self._cleanup,
            self.name,
            warn_message="Implicitly cleaning up {!r}".format(self),
        )

    @classmethod
    def _cleanup(cls, name, warn_message):
        rmtree(name)
        warnings.warn(warn_message, ResourceWarning)

    def __repr__(self):
        return "<{} {!r}>".format(self.__class__.__name__, self.name)

    def __enter__(self):
        return self

    def __exit__(self, exc, value, tb):
        self.cleanup()

    def cleanup(self):
        if self._finalizer.detach():
            rmtree(self.name)


def split_argument(req, short=None, long_=None):
    """Split an argument from a string (finds None if not present).

    Uses -short <arg>, --long <arg>, and --long=arg as permutations.

    returns string, index
    """
    index_entries = []
    if long_:
        long_ = ' --{0}'.format(long_)
        index_entries.extend(['{0}{1}'.format(long_, s) for s in [' ', '=']])
    if short:
        index_entries.append(' -{0} '.format(short))
    index = None
    index_entry = first([entry for entry in index_entries if entry in req])
    if index_entry:
        req, index = req.split(index_entry)
        remaining_line = index.split()
        if len(remaining_line) > 1:
            index, more_req = remaining_line[0], ' '.join(remaining_line[1:])
            req = '{0} {1}'.format(req, more_req)
    return req, index
