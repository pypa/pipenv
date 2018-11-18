# coding: utf-8
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import copy
import hashlib
import os
from contextlib import contextmanager
from shutil import rmtree

from .._compat import (
    is_file_url,
    url_to_path,
    PackageFinder,
    RequirementSet,
    Wheel,
    FAVORITE_HASH,
    TemporaryDirectory,
    PyPI,
    InstallRequirement,
    SafeFileCache
)
os.environ["PIP_SHIMS_BASE_MODULE"] = str("pipenv.patched.notpip")
from pip_shims.shims import do_import, VcsSupport, WheelCache
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet, Specifier
InstallationError = do_import(("exceptions.InstallationError", "7.0", "9999"))
from pipenv.patched.notpip._internal.resolve import Resolver as PipResolver


from pipenv.environments import PIPENV_CACHE_DIR as CACHE_DIR
from ..exceptions import NoCandidateFound
from ..utils import (fs_str, is_pinned_requirement, lookup_table, dedup,
                        make_install_requirement, clean_requires_python)
from .base import BaseRepository

try:
    from pipenv.patched.notpip._internal.req.req_tracker import RequirementTracker
except ImportError:
    @contextmanager
    def RequirementTracker():
        yield


class HashCache(SafeFileCache):
    """Caches hashes of PyPI artifacts so we do not need to re-download them

    Hashes are only cached when the URL appears to contain a hash in it and the cache key includes
    the hash value returned from the server). This ought to avoid ssues where the location on the
    server changes."""
    def __init__(self, *args, **kwargs):
        session = kwargs.pop('session')
        self.session = session
        kwargs.setdefault('directory', os.path.join(CACHE_DIR, 'hash-cache'))
        super(HashCache, self).__init__(*args, **kwargs)

    def get_hash(self, location):
        # if there is no location hash (i.e., md5 / sha256 / etc) we on't want to store it
        hash_value = None
        vcs = VcsSupport()
        orig_scheme = location.scheme
        new_location = copy.deepcopy(location)
        if orig_scheme in vcs.all_schemes:
            new_location.url = new_location.url.split("+", 1)[-1]
        can_hash = new_location.hash
        if can_hash:
            # hash url WITH fragment
            hash_value = self.get(new_location.url)
        if not hash_value:
            hash_value = self._get_file_hash(new_location) if not new_location.url.startswith("ssh") else None
            hash_value = hash_value.encode('utf8') if hash_value else None
        if can_hash:
            self.set(new_location.url, hash_value)
        return hash_value.decode('utf8') if hash_value else None

    def _get_file_hash(self, location):
        h = hashlib.new(FAVORITE_HASH)
        with open_local_or_remote_file(location, self.session) as fp:
            for chunk in iter(lambda: fp.read(8096), b""):
                h.update(chunk)
        return ":".join([FAVORITE_HASH, h.hexdigest()])


class PyPIRepository(BaseRepository):
    DEFAULT_INDEX_URL = PyPI.simple_url

    """
    The PyPIRepository will use the provided Finder instance to lookup
    packages.  Typically, it looks up packages on PyPI (the default implicit
    config), but any other PyPI mirror can be used if index_urls is
    changed/configured on the Finder.
    """
    def __init__(self, pip_options, session, use_json=False):
        self.session = session
        self.use_json = use_json
        self.pip_options = pip_options

        index_urls = [pip_options.index_url] + pip_options.extra_index_urls
        if pip_options.no_index:
            index_urls = []

        self.finder = PackageFinder(
            find_links=pip_options.find_links,
            index_urls=index_urls,
            trusted_hosts=pip_options.trusted_hosts,
            allow_all_prereleases=pip_options.pre,
            process_dependency_links=pip_options.process_dependency_links,
            session=self.session,
        )

        # Caches
        # stores project_name => InstallationCandidate mappings for all
        # versions reported by PyPI, so we only have to ask once for each
        # project
        self._available_candidates_cache = {}

        # stores InstallRequirement => list(InstallRequirement) mappings
        # of all secondary dependencies for the given requirement, so we
        # only have to go to disk once for each requirement
        self._dependencies_cache = {}
        self._json_dep_cache = {}

        # stores *full* path + fragment => sha256
        self._hash_cache = HashCache(session=session)

        # Setup file paths
        self.freshen_build_caches()
        self._download_dir = fs_str(os.path.join(CACHE_DIR, 'pkgs'))
        self._wheel_download_dir = fs_str(os.path.join(CACHE_DIR, 'wheels'))

    def freshen_build_caches(self):
        """
        Start with fresh build/source caches.  Will remove any old build
        caches from disk automatically.
        """
        self._build_dir = TemporaryDirectory(fs_str('build'))
        self._source_dir = TemporaryDirectory(fs_str('source'))

    @property
    def build_dir(self):
        return self._build_dir.name

    @property
    def source_dir(self):
        return self._source_dir.name

    def clear_caches(self):
        rmtree(self._download_dir, ignore_errors=True)
        rmtree(self._wheel_download_dir, ignore_errors=True)

    def find_all_candidates(self, req_name):
        if req_name not in self._available_candidates_cache:
            candidates = self.finder.find_all_candidates(req_name)
            self._available_candidates_cache[req_name] = candidates
        return self._available_candidates_cache[req_name]

    def find_best_match(self, ireq, prereleases=None):
        """
        Returns a Version object that indicates the best match for the given
        InstallRequirement according to the external repository.
        """
        if ireq.editable:
            return ireq  # return itself as the best match

        all_candidates = clean_requires_python(self.find_all_candidates(ireq.name))
        candidates_by_version = lookup_table(all_candidates, key=lambda c: c.version, unique=True)
        try:
            matching_versions = ireq.specifier.filter((candidate.version for candidate in all_candidates),
                                                  prereleases=prereleases)
        except TypeError:
            matching_versions = [candidate.version for candidate in all_candidates]

        # Reuses pip's internal candidate sort key to sort
        matching_candidates = [candidates_by_version[ver] for ver in matching_versions]
        if not matching_candidates:
            raise NoCandidateFound(ireq, all_candidates, self.finder)
        best_candidate = max(matching_candidates, key=self.finder._candidate_sort_key)

        # Turn the candidate into a pinned InstallRequirement
        return make_install_requirement(
            best_candidate.project, best_candidate.version, ireq.extras, ireq.markers,  constraint=ireq.constraint
         )

    def get_json_dependencies(self, ireq):

        if not (is_pinned_requirement(ireq)):
            raise TypeError('Expected pinned InstallRequirement, got {}'.format(ireq))

        def gen(ireq):
            if self.DEFAULT_INDEX_URL not in self.finder.index_urls:
                return

            url = 'https://pypi.org/pypi/{0}/json'.format(ireq.req.name)
            releases = self.session.get(url).json()['releases']

            matches = [
                r for r in releases
                if '=={0}'.format(r) == str(ireq.req.specifier)
            ]
            if not matches:
                return

            release_requires = self.session.get(
                'https://pypi.org/pypi/{0}/{1}/json'.format(
                    ireq.req.name, matches[0],
                ),
            ).json()
            try:
                requires_dist = release_requires['info']['requires_dist']
            except KeyError:
                return

            for requires in requires_dist:
                i = InstallRequirement.from_line(requires)
                if 'extra' not in repr(i.markers):
                    yield i

        try:
            if ireq not in self._json_dep_cache:
                self._json_dep_cache[ireq] = [g for g in gen(ireq)]

            return set(self._json_dep_cache[ireq])
        except Exception:
            return set()

    def get_dependencies(self, ireq):
        json_results = set()

        if self.use_json:
            try:
                json_results = self.get_json_dependencies(ireq)
            except TypeError:
                json_results = set()

        legacy_results = self.get_legacy_dependencies(ireq)
        json_results.update(legacy_results)

        return json_results

    def resolve_reqs(self, download_dir, ireq, wheel_cache, setup_requires={}, dist=None):
        results = None
        setup_requires = {}
        dist = None
        ireq.isolated = False
        ireq._wheel_cache = wheel_cache

        try:
            from pipenv.patched.notpip._internal.operations.prepare import RequirementPreparer
        except ImportError:
                # Pip 9 and below
            reqset = RequirementSet(
                self.build_dir,
                self.source_dir,
                download_dir=download_dir,
                wheel_download_dir=self._wheel_download_dir,
                session=self.session,
                ignore_installed=True,
                ignore_compatibility=False,
                wheel_cache=wheel_cache
            )
            results = reqset._prepare_file(self.finder, ireq, ignore_requires_python=True)
        else:
            # pip >= 10
            preparer_kwargs = {
                'build_dir': self.build_dir,
                'src_dir': self.source_dir,
                'download_dir': download_dir,
                'wheel_download_dir': self._wheel_download_dir,
                'progress_bar': 'off',
                'build_isolation': False
            }
            resolver_kwargs = {
                'finder': self.finder,
                'session': self.session,
                'upgrade_strategy': "to-satisfy-only",
                'force_reinstall': True,
                'ignore_dependencies': False,
                'ignore_requires_python': True,
                'ignore_installed': True,
                'isolated': False,
                'wheel_cache': wheel_cache,
                'use_user_site': False,
                'ignore_compatibility': False
            }
            resolver = None
            preparer = None
            with RequirementTracker() as req_tracker:
                # Pip 18 uses a requirement tracker to prevent fork bombs
                if req_tracker:
                    preparer_kwargs['req_tracker'] = req_tracker
                preparer = RequirementPreparer(**preparer_kwargs)
                resolver_kwargs['preparer'] = preparer
                reqset = RequirementSet()
                ireq.is_direct = True
                # reqset.add_requirement(ireq)
                resolver = PipResolver(**resolver_kwargs)
                resolver.require_hashes = False
                results = resolver._resolve_one(reqset, ireq)

        cleanup_fn = getattr(reqset, "cleanup_files", None)
        if cleanup_fn is not None:
            try:
                cleanup_fn()
            except OSError:
                pass

        if ireq.editable and (not ireq.source_dir or not os.path.exists(ireq.source_dir)):
            if ireq.editable:
                self._source_dir = TemporaryDirectory(fs_str("source"))
                ireq.ensure_has_source_dir(self.source_dir)

        if ireq.editable and (ireq.source_dir and os.path.exists(ireq.source_dir)):
            # Collect setup_requires info from local eggs.
            # Do this after we call the preparer on these reqs to make sure their
            # egg info has been created
            from pipenv.utils import chdir
            with chdir(ireq.setup_py_dir):
                try:
                    from setuptools.dist import distutils
                    dist = distutils.core.run_setup(ireq.setup_py)
                except InstallationError:
                    ireq.run_egg_info()
                except (TypeError, ValueError, AttributeError):
                    pass
                if not dist:
                    try:
                        dist = ireq.get_dist()
                    except (ImportError, ValueError, TypeError, AttributeError):
                        pass
        if ireq.editable and dist:
            setup_requires = getattr(dist, "extras_require", None)
            if not setup_requires:
                setup_requires = {"setup_requires": getattr(dist, "setup_requires", None)}
            if not getattr(ireq, 'req', None):
                try:
                    ireq.req = dist.as_requirement() if dist else None
                except (ValueError, TypeError) as e:
                    pass

            # Convert setup_requires dict into a somewhat usable form.
            if setup_requires:
                for section in setup_requires:
                    python_version = section
                    not_python = not (section.startswith('[') and ':' in section)

                    # This is for cleaning up :extras: formatted markers
                    # by adding them to the results of the resolver
                    # since any such extra would have been returned as a result anyway
                    for value in setup_requires[section]:
                        # This is a marker.
                        if value.startswith('[') and ':' in value:
                            python_version = value[1:-1]
                            not_python = False
                        # Strip out other extras.
                        if value.startswith('[') and ':' not in value:
                            not_python = True

                        if ':' not in value:
                            try:
                                if not not_python:
                                    results.add(InstallRequirement.from_line("{0}{1}".format(value, python_version).replace(':', ';')))
                            # Anything could go wrong here -- can't be too careful.
                            except Exception:
                                pass

            # this section properly creates 'python_version' markers for cross-python
            # virtualenv creation and for multi-python compatibility.
            requires_python = reqset.requires_python if hasattr(reqset, 'requires_python') else resolver.requires_python
            if requires_python:
                marker_str = ''
                # This corrects a logic error from the previous code which said that if
                # we Encountered any 'requires_python' attributes, basically only create a
                # single result no matter how many we resolved.  This should fix
                # a majority of the remaining non-deterministic resolution issues.
                if any(requires_python.startswith(op) for op in Specifier._operators.keys()):
                    # We are checking first if we have  leading specifier operator
                    # if not, we can assume we should be doing a == comparison
                    specifierset = SpecifierSet(requires_python)
                    # for multiple specifiers, the correct way to represent that in
                    # a specifierset is `Requirement('fakepkg; python_version<"3.0,>=2.6"')`
                    from passa.internals.specifiers import cleanup_pyspecs
                    marker_str = str(Marker(" and ".join(dedup([
                        "python_version {0[0]} '{0[1]}'".format(spec)
                        for spec in cleanup_pyspecs(specifierset)
                    ]))))
                # The best way to add markers to a requirement is to make a separate requirement
                # with only markers on it, and then to transfer the object istelf
                marker_to_add = Requirement('fakepkg; {0}'.format(marker_str)).marker
                if ireq in results:
                    results.remove(ireq)
                print(marker_to_add)
                ireq.req.marker = marker_to_add

        results = set(results) if results else set()
        return results, ireq

    def get_legacy_dependencies(self, ireq):
        """
        Given a pinned or an editable InstallRequirement, returns a set of
        dependencies (also InstallRequirements, but not necessarily pinned).
        They indicate the secondary dependencies for the given requirement.
        """
        if not (ireq.editable or is_pinned_requirement(ireq)):
            raise TypeError('Expected pinned or editable InstallRequirement, got {}'.format(ireq))

        if ireq not in self._dependencies_cache:
            if ireq.editable and (ireq.source_dir and os.path.exists(ireq.source_dir)):
                # No download_dir for locally available editable requirements.
                # If a download_dir is passed, pip will  unnecessarely
                # archive the entire source directory
                download_dir = None

            elif ireq.link and not ireq.link.is_artifact:
                # No download_dir for VCS sources.  This also works around pip
                # using git-checkout-index, which gets rid of the .git dir.
                download_dir = None
            else:
                download_dir = self._download_dir
                if not os.path.isdir(download_dir):
                    os.makedirs(download_dir)
            if not os.path.isdir(self._wheel_download_dir):
                os.makedirs(self._wheel_download_dir)

            wheel_cache = WheelCache(CACHE_DIR, self.pip_options.format_control)
            prev_tracker = os.environ.get('PIP_REQ_TRACKER')
            try:
                results, ireq = self.resolve_reqs(download_dir, ireq, wheel_cache)
                self._dependencies_cache[ireq] = results
            finally:
                if 'PIP_REQ_TRACKER' in os.environ:
                    if prev_tracker:
                        os.environ['PIP_REQ_TRACKER'] = prev_tracker
                    else:
                        del os.environ['PIP_REQ_TRACKER']
                try:
                    self.wheel_cache.cleanup()
                except AttributeError:
                    pass
        return self._dependencies_cache[ireq]

    def get_hashes(self, ireq):
        """
        Given an InstallRequirement, return a set of hashes that represent all
        of the files for a given requirement. Editable requirements return an
        empty set. Unpinned requirements raise a TypeError.
        """
        if ireq.editable:
            return set()

        vcs = VcsSupport()
        if ireq.link and ireq.link.scheme in vcs.all_schemes and 'ssh' in ireq.link.scheme:
            return set()

        if not is_pinned_requirement(ireq):
            raise TypeError(
                "Expected pinned requirement, got {}".format(ireq))

        # We need to get all of the candidates that match our current version
        # pin, these will represent all of the files that could possibly
        # satisfy this constraint.
        ### Modification -- this is much more efficient....
        ### modification again -- still more efficient
        matching_candidates = (
            c for c in clean_requires_python(self.find_all_candidates(ireq.name))
            if c.version in ireq.specifier
        )
        # candidates_by_version = lookup_table(all_candidates, key=lambda c: c.version)
        # matching_versions = list(
        #     ireq.specifier.filter((candidate.version for candidate in all_candidates)))
        # matching_candidates = candidates_by_version[matching_versions[0]]

        return {
            h for h in map(lambda c: self._hash_cache.get_hash(c.location),
                                matching_candidates) if h is not None
        }

    @contextmanager
    def allow_all_wheels(self):
        """
        Monkey patches pip.Wheel to allow wheels from all platforms and Python versions.

        This also saves the candidate cache and set a new one, or else the results from the
        previous non-patched calls will interfere.
        """
        def _wheel_supported(self, tags=None):
            # Ignore current platform. Support everything.
            return True

        def _wheel_support_index_min(self, tags=None):
            # All wheels are equal priority for sorting.
            return 0

        original_wheel_supported = Wheel.supported
        original_support_index_min = Wheel.support_index_min
        original_cache = self._available_candidates_cache

        Wheel.supported = _wheel_supported
        Wheel.support_index_min = _wheel_support_index_min
        self._available_candidates_cache = {}

        try:
            yield
        finally:
            Wheel.supported = original_wheel_supported
            Wheel.support_index_min = original_support_index_min
            self._available_candidates_cache = original_cache


@contextmanager
def open_local_or_remote_file(link, session):
    """
    Open local or remote file for reading.

    :type link: pip.index.Link
    :type session: requests.Session
    :raises ValueError: If link points to a local directory.
    :return: a context manager to the opened file-like object
    """
    url = link.url_without_fragment

    if is_file_url(link):
        # Local URL
        local_path = url_to_path(url)
        if os.path.isdir(local_path):
            raise ValueError("Cannot open directory for read: {}".format(url))
        else:
            with open(local_path, 'rb') as local_file:
                yield local_file
    else:
        # Remote URL
        headers = {"Accept-Encoding": "identity"}
        response = session.get(url, headers=headers, stream=True)
        try:
            yield response.raw
        finally:
            response.close()
