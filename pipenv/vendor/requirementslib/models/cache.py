import atexit
import copy
import hashlib
import json
import os

from pipenv.patched.pip._internal.utils.hashes import FAVORITE_HASH
from pipenv.patched.pip._internal.vcs.versioncontrol import VcsSupport
from pipenv.patched.pip._vendor.cachecontrol.cache import DictCache
from pipenv.patched.pip._vendor.packaging.requirements import Requirement
from pipenv.patched.pip._vendor.platformdirs import user_cache_dir

from ..fileutils import open_file
from .utils import as_tuple, get_pinned_version, key_from_req, lookup_table

CACHE_DIR = os.environ.get("PIPENV_CACHE_DIR", user_cache_dir("pipenv"))


class DependencyCache(object):
    """Creates a new in memory dependency cache for the current Python
    version."""

    def __init__(self):
        self.cache = {}

    def as_cache_key(self, ireq):
        """Given a requirement, return its cache key. This behavior is a little
        weird in order to allow backwards compatibility with cache files. For a
        requirement without extras, this will return, for example:

        ("ipython", "2.1.0")

        For a requirement with extras, the extras will be comma-separated and appended to the
        version, inside brackets,
        like so:

        ("ipython", "2.1.0[nbconvert,notebook]")
        """
        name, version, extras = as_tuple(ireq)
        if not extras:
            extras_string = ""
        else:
            extras_string = "[{}]".format(",".join(extras))
        return name, "{}{}".format(version, extras_string)

    def write_cache(self):
        """Writes the cache to disk as JSON."""
        doc = {
            "__format__": 1,
            "dependencies": self._cache,
        }
        with open(self._cache_file, "w") as f:
            json.dump(doc, f, sort_keys=True)

    def clear(self):
        self._cache = {}

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

    def __delitem__(self, ireq):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        try:
            del self.cache[pkgname][pkgversion_and_extras]
        except KeyError:
            return

    def get(self, ireq, default=None):
        pkgname, pkgversion_and_extras = self.as_cache_key(ireq)
        return self.cache.get(pkgname, {}).get(pkgversion_and_extras, default)

    def reverse_dependencies(self, ireqs):
        """Returns a lookup table of reverse dependencies for all the given
        ireqs.

        Since this is all static, it only works if the dependency cache
        contains the complete data, otherwise you end up with a partial
        view. This is typically no problem if you use this function
        after the entire dependency tree is resolved.
        """
        ireqs_as_cache_values = [self.as_cache_key(ireq) for ireq in ireqs]
        return self._reverse_dependencies(ireqs_as_cache_values)

    def _reverse_dependencies(self, cache_keys):
        """Returns a lookup table of reverse dependencies for all the given
        cache keys.

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
        return lookup_table(
            (key_from_req(Requirement(dep_name)), name)
            for name, version_and_extras in cache_keys
            for dep_name in self.cache[name][version_and_extras]
        )


class HashCache(DictCache):
    """Caches hashes of PyPI artifacts so we do not need to re-download them.

    Hashes are only cached when the URL appears to contain a hash in it
    and the cache key includes the hash value returned from the server).
    This ought to avoid ssues where the location on the server changes.
    """

    def __init__(self, *args, **kwargs):
        session = kwargs.pop("session", None)
        if not session:
            import pipenv.patched.pip._vendor.requests as requests

            session = requests.session()
            atexit.register(session.close)
        self.session = session
        super(HashCache, self).__init__(*args, **kwargs)

    def get_hash(self, location):
        # if there is no location hash (i.e., md5 / sha256 / etc) we don't want to store it
        hash_value = None
        vcs = VcsSupport()
        orig_scheme = location.scheme
        new_location = copy.deepcopy(location)
        if orig_scheme in vcs.all_schemes:
            new_location.url = new_location.url.split("+", 1)[-1]
        can_hash = new_location.hash
        if can_hash:
            # hash url WITH fragment
            hash_value = (
                self._get_file_hash(new_location.url)
                if not new_location.url.startswith("ssh")
                else None
            )
        if not hash_value:
            hash_value = self._get_file_hash(new_location)
            hash_value = hash_value.encode("utf8")
        if can_hash:
            self.set(new_location.url, hash_value)
        return hash_value.decode("utf8")

    def _get_file_hash(self, location):
        h = hashlib.new(FAVORITE_HASH)
        with open_file(location, self.session) as fp:
            for chunk in iter(lambda: fp.read(8096), b""):
                h.update(chunk)
        return ":".join([FAVORITE_HASH, h.hexdigest()])
