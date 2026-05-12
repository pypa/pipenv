"""The ``Sources`` subsystem of :class:`pipenv.project.Project`.

This module is the first of the Initiative D extractions: the
``Sources``-classified methods on ``pipenv.project.Project`` have been
relocated into a dedicated ``Sources`` class accessed via the
``@cached_property`` ``Project.sources``. ``Sources`` holds a reference
back to the owning ``Project`` for two reasons:

1. Reading sources requires read access to ``project.pipfile.parsed``
   (and, for the ``all`` property, ``project.lockfile.content``).
2. The single writer in this subsystem
   (:meth:`Sources.add_index_to_pipfile`) needs to call
   ``project.pipfile.write_toml`` so that the Pipfile cache is invalidated
   correctly.

Behaviour is preserved verbatim from the previous in-``Project``
implementation; this is a relocation, not a rewrite. See
``docs/dev/initiative-d-inventory.md`` for the full T_D.1 inventory
that motivated the cluster boundary.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
from random import randint
from urllib import parse
from urllib.parse import urljoin

from pipenv.patched.pip._internal.models.link import Link
from pipenv.patched.pip._internal.utils.hashes import FAVORITE_HASH
from pipenv.utils import err
from pipenv.utils.dependencies import clean_pkg_version, pep423_name
from pipenv.utils.fileutils import open_file
from pipenv.utils.internet import (
    PackageIndexHTMLParser,
    get_requests_session,
    get_url_name,
    is_pypi_url,
    is_valid_url,
)
from pipenv.utils.shell import expand_url_credentials, safe_expandvars
from pipenv.vendor import tomlkit


class SourceNotFound(KeyError):
    """Raised by :meth:`Sources.get_source` when no source matches.

    Subclasses :class:`KeyError` so ``except KeyError`` catches it.
    """


class Sources:
    """Indexes / [[source]] subsystem of :class:`Project`.

    Constructed with a back-reference to its owning ``Project``. Caches
    nothing of its own beyond the URL→session map on the project's
    ``sessions`` dict (kept on ``Project`` so that future per-subsystem
    refactors can move it together with this class).
    """

    def __init__(self, project):
        self._project = project

    # --- requests-session caching ---------------------------------------

    def get_requests_session_for_source(self, source):
        project = self._project
        if not (source and source.get("name")):
            return None
        if project.sessions.get(source["name"]):
            session = project.sessions[source["name"]]
        else:
            session = get_requests_session(
                project.s.PIPENV_MAX_RETRIES,
                source.get("verify_ssl", True),
                cache_dir=project.s.PIPENV_CACHE_DIR,
                source=source.get("url"),
            )
            project.sessions[source["name"]] = session
        return session

    # --- hashing from indexes -------------------------------------------

    @staticmethod
    def _prepend_hash_types(checksums, hash_type):
        cleaned_checksums = set()
        for checksum in checksums:
            if not checksum:
                continue
            if not checksum.startswith(f"{hash_type}:"):
                checksum = f"{hash_type}:{checksum}"
            cleaned_checksums.add(checksum)
        return sorted(cleaned_checksums)

    @staticmethod
    def _get_file_hash(session, link):
        h = hashlib.new(FAVORITE_HASH)
        err.print(f"Downloading file {link.filename} to obtain hash...")
        with open_file(link.url, session) as fp:
            if fp is None:
                return None
            for chunk in iter(lambda: fp.read(8096), b""):
                h.update(chunk)
        return f"{h.name}:{h.hexdigest()}"

    def get_hash_from_link(self, hash_cache, link):
        if link.hash and link.hash_name == FAVORITE_HASH:
            return f"{link.hash_name}:{link.hash}"
        return hash_cache.get_hash(link)

    def get_hashes_from_pypi(self, ireq, source):
        project = self._project
        pkg_url = f"https://pypi.org/pypi/{ireq.name}/json"
        session = self.get_requests_session_for_source(source)
        if not session:
            return None
        try:
            collected_hashes = set()
            # Grab the hashes from the new warehouse API.
            r = session.get(pkg_url, timeout=project.s.PIPENV_REQUESTS_TIMEOUT)
            api_releases = r.json()["releases"]
            cleaned_releases = {}
            for api_version, api_info in api_releases.items():
                api_version = clean_pkg_version(api_version)
                cleaned_releases[api_version] = api_info
            version = ""
            if ireq.specifier:
                spec = next(iter(s for s in ireq.specifier), None)
                if spec:
                    version = spec.version
            for release in cleaned_releases[version]:
                collected_hashes.add(release["digests"][FAVORITE_HASH])
            return self._prepend_hash_types(collected_hashes, FAVORITE_HASH)
        except (ValueError, KeyError, ConnectionError):
            return None

    def get_hashes_from_remote_index_urls(self, ireq, source):
        project = self._project
        normalized_name = pep423_name(ireq.name)
        url_name = normalized_name.replace(".", "-")
        pkg_url = f"{source['url']}/{url_name}/"
        session = self.get_requests_session_for_source(source)

        try:
            collected_hashes = set()
            response = session.get(pkg_url, timeout=project.s.PIPENV_REQUESTS_TIMEOUT)
            parser = PackageIndexHTMLParser()
            parser.feed(response.text)
            hrefs = parser.urls

            version = ""
            if ireq.specifier:
                spec = next(iter(s for s in ireq.specifier), None)
                if spec:
                    version = spec.version

            # We'll check if the href looks like a version-specific page (i.e., ends with '/')
            for package_url in hrefs:
                parsed_url = parse.urlparse(package_url)
                if version in parsed_url.path and parsed_url.path.endswith("/"):
                    # This might be a version-specific page. Fetch and parse it
                    version_url = urljoin(pkg_url, package_url)
                    version_response = session.get(
                        version_url, timeout=project.s.PIPENV_REQUESTS_TIMEOUT
                    )
                    version_parser = PackageIndexHTMLParser()
                    version_parser.feed(version_response.text)
                    version_hrefs = version_parser.urls

                    # Process these new hrefs as potential wheels
                    for v_package_url in version_hrefs:
                        url_params = parse.urlparse(v_package_url).fragment
                        params_dict = parse.parse_qs(url_params)
                        if params_dict.get(FAVORITE_HASH):
                            collected_hashes.add(params_dict[FAVORITE_HASH][0])
                        else:  # Fallback to downloading the file to obtain hash
                            v_package_full_url = urljoin(version_url, v_package_url)
                            link = Link(v_package_full_url)
                            file_hash = self._get_file_hash(session, link)
                            if file_hash:
                                collected_hashes.add(file_hash)
                elif version in parse.unquote(package_url):
                    # Process the current href as a potential wheel from the main page
                    url_params = parse.urlparse(package_url).fragment
                    params_dict = parse.parse_qs(url_params)
                    if params_dict.get(FAVORITE_HASH):
                        collected_hashes.add(params_dict[FAVORITE_HASH][0])
                    else:  # Fallback to downloading the file to obtain hash
                        package_full_url = urljoin(pkg_url, package_url)
                        link = Link(package_full_url)
                        file_hash = self._get_file_hash(session, link)
                        if file_hash:
                            collected_hashes.add(file_hash)

            return self._prepend_hash_types(collected_hashes, FAVORITE_HASH)

        except Exception:
            return None

    # --- source list accessors ------------------------------------------

    @classmethod
    def populate_source(cls, source):
        """Derive missing values of source from the existing fields."""
        # Only URL parameter is mandatory, let the KeyError be thrown.
        if "name" not in source:
            source["name"] = get_url_name(source["url"])
        if "verify_ssl" not in source:
            source["verify_ssl"] = "https://" in source["url"]
        if not isinstance(source["verify_ssl"], bool):
            source["verify_ssl"] = str(source["verify_ssl"]).lower() == "true"
        return source

    def pipfile_sources(self, expand_vars=True):
        project = self._project
        if project.pipfile.is_empty or "source" not in project.pipfile.parsed:
            sources = [project.default_source]
            if os.environ.get("PIPENV_PYPI_MIRROR"):
                sources[0]["url"] = os.environ["PIPENV_PYPI_MIRROR"]
            return sources
        # Expand environment variables in the source URLs.
        # For the "url" field we use expand_url_credentials() which URL-encodes
        # the expanded credential values so that passwords with special characters
        # (e.g. '@', ':', '%') produce a valid URL (#4868).
        sources = [
            {
                k: (
                    (expand_url_credentials(v) if k == "url" else safe_expandvars(v))
                    if expand_vars
                    else v
                )
                for k, v in source.items()
            }
            for source in project.pipfile.parsed["source"]
        ]
        for source in sources:
            if os.environ.get("PIPENV_PYPI_MIRROR") and is_pypi_url(source.get("url")):
                source["url"] = os.environ["PIPENV_PYPI_MIRROR"]
        return sources

    def get_default_index(self):
        return self.populate_source(self.pipfile_sources()[0])

    def get_index_by_name(self, index_name):
        for source in self.pipfile_sources():
            if source.get("name") == index_name:
                return source

    def get_index_by_url(self, index_url):
        for source in self.pipfile_sources():
            if source.get("url") == index_url:
                return source

    @property
    def all(self):
        """The active source list.

        Prefers the lockfile's ``_meta.sources`` if a lockfile exists
        (so resolves use the locked-in source set), otherwise falls back
        to the Pipfile's ``[[source]]`` tables.

        This is the data-bearing accessor that replaces the old
        ``Project.sources`` property.
        """
        project = self._project
        if project.lockfile.any_exists and hasattr(project.lockfile.content, "keys"):
            meta_ = project.lockfile.content.get("_meta", {})
            sources_ = meta_.get("sources")
            if sources_:
                return sources_
        # Lockfile absent OR present-but-empty-meta — fall back to the
        # Pipfile's [[source]] tables so callers (default/index_urls/
        # get_source) always see a list, never None.
        return self.pipfile_sources()

    @property
    def default(self):
        """First entry of :attr:`all` — replaces ``Project.sources_default``."""
        return self.all[0]

    @property
    def index_urls(self):
        return [src.get("url") for src in self.all]

    def find_source(self, source):
        """
        Given a source, find it.

        source can be a url or an index name.
        """
        if not is_valid_url(source):
            try:
                source = self.get_source(name=source)
            except SourceNotFound:
                source = self.get_source(url=source)
        else:
            source = self.get_source(url=source)
        return source

    def get_source(self, name=None, url=None, refresh=False):
        from pipenv.utils.internet import is_url_equal

        def find_source(sources, name=None, url=None):
            source = None
            if name:
                source = next(
                    iter(s for s in sources if "name" in s and s["name"] == name),
                    None,
                )
            elif url:
                source = next(
                    iter(
                        s
                        for s in sources
                        if "url" in s and is_url_equal(url, s.get("url", ""))
                    ),
                    None,
                )
            if source is not None:
                return source

        sources = (self.all, self.pipfile_sources())
        if refresh:
            sources = reversed(sources)
        found = None
        for _src in sources:
            _result = find_source(_src, name=name, url=url)
            if _result is not None:
                found = _result
                break
        target = next(iter(t for t in (name, url) if t is not None))
        if found is None:
            raise SourceNotFound(target)
        return found

    def src_name_from_url(self, index_url):
        location = parse.urlsplit(index_url).netloc
        if "." in location:
            name, _, _tld_guess = location.rpartition(".")
        else:
            name = location
        src_name = name.replace(".", "").replace(":", "")
        try:
            self.get_source(name=src_name)
        except SourceNotFound:
            name = src_name
        else:
            name = f"{src_name}-{randint(1, 1000)}"
        return name

    def add_index_to_pipfile(self, index, verify_ssl=True):
        """
        Adds a given index to the Pipfile if it doesn't already exist.
        Returns the source name regardless of whether it was newly added or already existed.

        Raises PipenvUsageError if the index is not a valid URL and doesn't exist
        as a named source in the Pipfile.
        """
        from pipenv.exceptions import PipenvUsageError

        project = self._project
        # Read and append Pipfile.
        p = project.pipfile.parsed
        source = None

        # Try to find existing source by URL or name
        try:
            source = self.get_source(url=index)
        except SourceNotFound:
            with contextlib.suppress(SourceNotFound):
                source = self.get_source(name=index)

        # If we found an existing source with a name, return it
        if source is not None and source.get("name"):
            return source["name"]

        # Check if the URL already exists in any source
        if "source" in p:
            for existing_source in p["source"]:
                if existing_source.get("url") == index:
                    return existing_source.get("name")

        # If we reach here, the source doesn't exist - validate it's a valid URL
        if not is_valid_url(index):
            available_sources = ", ".join(
                f"'{s.get('name')}'" for s in self.all if s.get("name")
            )
            raise PipenvUsageError(
                f"Index '{index}' was not found in Pipfile sources and is not a valid URL.\n"
                f"Available sources: {available_sources or 'none'}\n"
                f"Hint: Use a valid URL or add the index to your Pipfile [[source]] section."
            )

        # Create and add the new source
        source = {
            "url": index,
            "verify_ssl": verify_ssl,
            "name": self.src_name_from_url(index),
        }

        # Add the source to the group
        if "source" not in p:
            p["source"] = [tomlkit.item(source)]
        else:
            p["source"].append(tomlkit.item(source))

        # Write Pipfile (and invalidate parsed-pipfile cache via project).
        project.pipfile.write_toml(p)
        return source["name"]
