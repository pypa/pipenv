# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import copy
import hashlib
import json
import os
import sys

import vistir

from appdirs import user_cache_dir
from pip_shims.shims import FAVORITE_HASH, SafeFileCache
from packaging.requirements import Requirement

from .utils import as_tuple, key_from_req, lookup_table, get_pinned_version

from ..exceptions import FileExistsError


CACHE_DIR = os.environ.get("PIPENV_CACHE_DIR", user_cache_dir("pipenv"))


# Pip-tools cache implementation
class CorruptCacheError(Exception):
    def __init__(self, path):
        self.path = path

    def __str__(self):
        lines = [
            'The dependency cache seems to have been corrupted.',
            'Inspect, or delete, the following file:',
            '  {}'.format(self.path),
        ]
        return os.linesep.join(lines)


def read_cache_file(cache_file_path):
    with open(cache_file_path, 'r') as cache_file:
        try:
            doc = json.load(cache_file)
        except ValueError:
            raise CorruptCacheError(cache_file_path)

        # Check version and load the contents
        assert doc['__format__'] == 1, 'Unknown cache file format'
        return doc['dependencies']


class DependencyCache(object):
    """
    Creates a new persistent dependency cache for the current Python version.
    The cache file is written to the appropriate user cache dir for the
    current platform, i.e.

        ~/.cache/pip-tools/depcache-pyX.Y.json

    Where X.Y indicates the Python version.
    """
    def __init__(self, cache_dir=None):
        if cache_dir is None:
            cache_dir = CACHE_DIR
        if not vistir.compat.Path(CACHE_DIR).absolute().is_dir():
            try:
                vistir.path.mkdir_p(os.path.abspath(cache_dir))
            except (FileExistsError, OSError):
                pass

        py_version = '.'.join(str(digit) for digit in sys.version_info[:2])
        cache_filename = 'depcache-py{}.json'.format(py_version)

        self._cache_file = os.path.join(cache_dir, cache_filename)
        self._cache = None

    @property
    def cache(self):
        """
        The dictionary that is the actual in-memory cache.  This property
        lazily loads the cache from disk.
        """
        if self._cache is None:
            self.read_cache()
        return self._cache

    def as_cache_key(self, ireq):
        """
        Given a requirement, return its cache key. This behavior is a little weird in order to allow backwards
        compatibility with cache files. For a requirement without extras, this will return, for example:

        ("ipython", "2.1.0")

        For a requirement with extras, the extras will be comma-separated and appended to the version, inside brackets,
        like so:

        ("ipython", "2.1.0[nbconvert,notebook]")
        """
        name, version, extras = as_tuple(ireq)
        if not extras:
            extras_string = ""
        else:
            extras_string = "[{}]".format(",".join(extras))
        return name, "{}{}".format(version, extras_string)

    def read_cache(self):
        """Reads the cached contents into memory."""
        if os.path.exists(self._cache_file):
            self._cache = read_cache_file(self._cache_file)
        else:
            self._cache = {}

    def write_cache(self):
        """Writes the cache to disk as JSON."""
        doc = {
            '__format__': 1,
            'dependencies': self._cache,
        }
        with open(self._cache_file, 'w') as f:
            json.dump(doc, f, sort_keys=True)

    def clear(self):
        self._cache = {}
        self.write_cache()

    def __contains__(self, ireq):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        return pkgversion_and_extras in self.cache.get(pkgname, {})

    def __getitem__(self, ireq):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        return self.cache[pkgname][pkgversion_and_extras]

    def __setitem__(self, ireq, values):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        self.cache.setdefault(pkgname, {})
        self.cache[pkgname][pkgversion_and_extras] = values
        self.write_cache()

    def __delitem__(self, ireq):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        try:
            del self.cache[pkgname][pkgversion_and_extras]
        except KeyError:
            return
        self.write_cache()

    def get(self, ireq, default=None):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        return self.cache.get(pkgname, {}).get(pkgversion_and_extras, default)

    def reverse_dependencies(self, ireqs):
        """
        Returns a lookup table of reverse dependencies for all the given ireqs.

        Since this is all static, it only works if the dependency cache
        contains the complete data, otherwise you end up with a partial view.
        This is typically no problem if you use this function after the entire
        dependency tree is resolved.
        """
        ireqs_as_cache_values = [self.as_cache_key(ireq) for ireq in ireqs]
        return self._reverse_dependencies(ireqs_as_cache_values)

    def _reverse_dependencies(self, cache_keys):
        """
        Returns a lookup table of reverse dependencies for all the given cache keys.

        Example input:

            [('pep8', '1.5.7'),
             ('flake8', '2.4.0'),
             ('mccabe', '0.3'),
             ('pyflakes', '0.8.1')]

        Example output:

            {'pep8': ['flake8'],
             'flake8': [],
             'mccabe': ['flake8'],
             'pyflakes': ['flake8']}

        """
        # First, collect all the dependencies into a sequence of (parent, child) tuples, like [('flake8', 'pep8'),
        # ('flake8', 'mccabe'), ...]
        return lookup_table((key_from_req(Requirement(dep_name)), name)
                            for name, version_and_extras in cache_keys
                            for dep_name in self.cache[name][version_and_extras])


class HashCache(SafeFileCache):
    """Caches hashes of PyPI artifacts so we do not need to re-download them.

    Hashes are only cached when the URL appears to contain a hash in it and the
    cache key includes the hash value returned from the server). This ought to
    avoid ssues where the location on the server changes.
    """
    def __init__(self, *args, **kwargs):
        session = kwargs.pop("session", None)
        if not session:
            import requests
            session = requests.session()
        cache_dir = kwargs.pop('cache_dir', CACHE_DIR)
        self.session = session
        kwargs.setdefault('directory', os.path.join(cache_dir, 'hash-cache'))
        super(HashCache, self).__init__(*args, **kwargs)

    def get_hash(self, location):
        from pip_shims import VcsSupport
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
            hash_value = self._get_file_hash(new_location.url) if not new_location.url.startswith("ssh") else None
        if not hash_value:
            hash_value = self._get_file_hash(new_location)
            hash_value = hash_value.encode('utf8')
        if can_hash:
            self.set(new_location.url, hash_value)
        return hash_value.decode('utf8')

    def _get_file_hash(self, location):
        h = hashlib.new(FAVORITE_HASH)
        with vistir.contextmanagers.open_file(location, self.session) as fp:
            for chunk in iter(lambda: fp.read(8096), b""):
                h.update(chunk)
        return ":".join([FAVORITE_HASH, h.hexdigest()])


class _JSONCache(object):
    """A persistent cache backed by a JSON file.

    The cache file is written to the appropriate user cache dir for the
    current platform, i.e.

        ~/.cache/pip-tools/depcache-pyX.Y.json

    Where X.Y indicates the Python version.
    """
    filename_format = None

    def __init__(self, cache_dir=CACHE_DIR):
        vistir.mkdir_p(cache_dir)
        python_version = ".".join(str(digit) for digit in sys.version_info[:2])
        cache_filename = self.filename_format.format(
            python_version=python_version,
        )
        self._cache_file = os.path.join(cache_dir, cache_filename)
        self._cache = None

    @property
    def cache(self):
        """The dictionary that is the actual in-memory cache.

        This property lazily loads the cache from disk.
        """
        if self._cache is None:
            self.read_cache()
        return self._cache

    def as_cache_key(self, ireq):
        """Given a requirement, return its cache key.

        This behavior is a little weird in order to allow backwards
        compatibility with cache files. For a requirement without extras, this
        will return, for example::

            ("ipython", "2.1.0")

        For a requirement with extras, the extras will be comma-separated and
        appended to the version, inside brackets, like so::

            ("ipython", "2.1.0[nbconvert,notebook]")
        """
        extras = tuple(sorted(ireq.extras))
        if not extras:
            extras_string = ""
        else:
            extras_string = "[{}]".format(",".join(extras))
        name = key_from_req(ireq.req)
        version = get_pinned_version(ireq)
        return name, "{}{}".format(version, extras_string)

    def read_cache(self):
        """Reads the cached contents into memory.
        """
        if os.path.exists(self._cache_file):
            self._cache = read_cache_file(self._cache_file)
        else:
            self._cache = {}

    def write_cache(self):
        """Writes the cache to disk as JSON.
        """
        doc = {
            '__format__': 1,
            'dependencies': self._cache,
        }
        with open(self._cache_file, 'w') as f:
            json.dump(doc, f, sort_keys=True)

    def clear(self):
        self._cache = {}
        self.write_cache()

    def __contains__(self, ireq):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        return pkgversion_and_extras in self.cache.get(pkgname, {})

    def __getitem__(self, ireq):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        return self.cache[pkgname][pkgversion_and_extras]

    def __setitem__(self, ireq, values):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        self.cache.setdefault(pkgname, {})
        self.cache[pkgname][pkgversion_and_extras] = values
        self.write_cache()

    def __delitem__(self, ireq):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        try:
            del self.cache[pkgname][pkgversion_and_extras]
        except KeyError:
            return
        self.write_cache()

    def get(self, ireq, default=None):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        return self.cache.get(pkgname, {}).get(pkgversion_and_extras, default)


class RequiresPythonCache(_JSONCache):
    """Cache a candidate's Requires-Python information.
    """
    filename_format = "pyreqcache-py{python_version}.json"
