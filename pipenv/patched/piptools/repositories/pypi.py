# coding: utf-8
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import hashlib
import os
from contextlib import contextmanager
from shutil import rmtree

from notpip.download import is_file_url, url_to_path
from notpip.index import PackageFinder
from notpip.req.req_set import RequirementSet
from notpip.wheel import Wheel
from notpip.req.req_install import InstallRequirement
from pip9._vendor.packaging.requirements import InvalidRequirement
from pip9._vendor.pyparsing import ParseException
from notpip.download import SafeFileCache
from notpip.utils.hashes import FAVORITE_HASH

from .._compat import TemporaryDirectory
from ..cache import CACHE_DIR
from pipenv.environments import PIPENV_CACHE_DIR
from ..exceptions import NoCandidateFound
from ..utils import (fs_str, is_pinned_requirement, lookup_table,
                     make_install_requirement)
from .base import BaseRepository


class HashCache(SafeFileCache):
    """Caches hashes of PyPI artifacts so we do not need to re-download them

    Hashes are only cached when the URL appears to contain a hash in it (and the cache key includes
    the hash value returned from the server). This ought to avoid issues where the location on the
    server changes."""
    def __init__(self, *args, **kwargs):
        session = kwargs.pop('session')
        self.session = session
        kwargs.setdefault('directory', os.path.join(PIPENV_CACHE_DIR, 'hash-cache'))
        super(HashCache, self).__init__(*args, **kwargs)

    def get_hash(self, location):
        # if there is no location hash (i.e., md5 / sha256 / etc) we don't want to store it
        hash_value = None
        can_hash = location.hash
        if can_hash:
            # hash url WITH fragment
            hash_value = self.get(location.url)
        if not hash_value:
            hash_value = self._get_file_hash(location)
            hash_value = hash_value.encode('utf8')
        if can_hash:
            self.set(location.url, hash_value)
        return hash_value.decode('utf8')

    def _get_file_hash(self, location):
        h = hashlib.new(FAVORITE_HASH)
        with open_local_or_remote_file(location, self.session) as fp:
            for chunk in iter(lambda: fp.read(8096), b""):
                h.update(chunk)
        return ":".join([FAVORITE_HASH, h.hexdigest()])


class PyPIRepository(BaseRepository):
    DEFAULT_INDEX_URL = 'https://pypi.org/simple'

    """
    The PyPIRepository will use the provided Finder instance to lookup
    packages.  Typically, it looks up packages on PyPI (the default implicit
    config), but any other PyPI mirror can be used if index_urls is
    changed/configured on the Finder.
    """
    def __init__(self, pip_options, session, use_json=False):
        self.session = session
        self.use_json = use_json

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

        all_candidates = self.find_all_candidates(ireq.name)
        candidates_by_version = lookup_table(all_candidates, key=lambda c: c.version, unique=True)
        matching_versions = ireq.specifier.filter((candidate.version for candidate in all_candidates),
                                                  prereleases=prereleases)

        # Reuses pip's internal candidate sort key to sort
        matching_candidates = [candidates_by_version[ver] for ver in matching_versions]
        if not matching_candidates:
            raise NoCandidateFound(ireq, all_candidates, self.finder.index_urls)
        best_candidate = max(matching_candidates, key=self.finder._candidate_sort_key)

        # Turn the candidate into a pinned InstallRequirement
        new_req = make_install_requirement(
            best_candidate.project, best_candidate.version, ireq.extras, ireq.markers, constraint=ireq.constraint
         )

        # KR TODO: Marker here?

        return new_req

    def get_json_dependencies(self, ireq):

        if not (is_pinned_requirement(ireq)):
            raise TypeError('Expected pinned InstallRequirement, got {}'.format(ireq))

        def gen(ireq):
            if self.DEFAULT_INDEX_URL in self.finder.index_urls:

                url = 'https://pypi.org/pypi/{0}/json'.format(ireq.req.name)
                r = self.session.get(url)

                # TODO: Latest isn't always latest.
                latest = list(r.json()['releases'].keys())[-1]
                if str(ireq.req.specifier) == '=={0}'.format(latest):

                    for requires in r.json().get('info', {}).get('requires_dist', {}):
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


    def get_legacy_dependencies(self, ireq):
        """
        Given a pinned or an editable InstallRequirement, returns a set of
        dependencies (also InstallRequirements, but not necessarily pinned).
        They indicate the secondary dependencies for the given requirement.
        """
        if not (ireq.editable or is_pinned_requirement(ireq)):
            raise TypeError('Expected pinned or editable InstallRequirement, got {}'.format(ireq))

        # Collect setup_requires info from local eggs.
        setup_requires = {}
        if ireq.editable:
            try:
                dist = ireq.get_dist()
                if dist.has_metadata('requires.txt'):
                    setup_requires = self.finder.get_extras_links(
                        dist.get_metadata_lines('requires.txt')
                    )
            except TypeError:
                pass


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

            reqset = RequirementSet(self.build_dir,
                                    self.source_dir,
                                    download_dir=download_dir,
                                    wheel_download_dir=self._wheel_download_dir,
                                    session=self.session,
                                    ignore_installed=True,
                                    ignore_compatibility=False
                                    )

            result = reqset._prepare_file(self.finder, ireq, ignore_requires_python=True)

            # Convert setup_requires dict into a somewhat usable form.
            if setup_requires:
                for section in setup_requires:
                    python_version = section
                    not_python = not (section.startswith('[') and ':' in section)

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
                                    result = result + [InstallRequirement.from_line("{0}{1}".format(value, python_version).replace(':', ';'))]
                            # Anything could go wrong here — can't be too careful.
                            except Exception:
                                pass

            if reqset.requires_python:

                marker = 'python_version=="{0}"'.format(reqset.requires_python.replace(' ', ''))
                new_req = InstallRequirement.from_line('{0}; {1}'.format(str(ireq.req), marker))
                result = [new_req]

            self._dependencies_cache[ireq] = result
        return set(self._dependencies_cache[ireq])

    def get_hashes(self, ireq):
        """
        Given an InstallRequirement, return a set of hashes that represent all
        of the files for a given requirement. Editable requirements return an
        empty set. Unpinned requirements raise a TypeError.
        """
        if ireq.editable:
            return set()

        if not is_pinned_requirement(ireq):
            raise TypeError(
                "Expected pinned requirement, got {}".format(ireq))

        # We need to get all of the candidates that match our current version
        # pin, these will represent all of the files that could possibly
        # satisfy this constraint.
        all_candidates = self.find_all_candidates(ireq.name)
        candidates_by_version = lookup_table(all_candidates, key=lambda c: c.version)
        matching_versions = list(
            ireq.specifier.filter((candidate.version for candidate in all_candidates)))
        matching_candidates = candidates_by_version[matching_versions[0]]

        return {
            self._hash_cache.get_hash(candidate.location)
            for candidate in matching_candidates
        }

    @contextmanager
    def allow_all_wheels(self):
        """
        Monkey patches pip9.Wheel to allow wheels from all platforms and Python versions.

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

    :type link: pip9.index.Link
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
