from __future__ import annotations

import re
from collections.abc import Mapping

from pipenv.exceptions import PipenvUsageError
from pipenv.patched.pip._vendor.urllib3.util import parse_url
from pipenv.utils.constants import MYPY_RUNNING

from .internet import _strip_credentials_from_url, create_mirror_source, is_pypi_url

if MYPY_RUNNING:
    from pipenv.project import Project, TSource  # noqa


def get_insecure_source_host(url, verify_ssl):
    """Return the ``--trusted-host`` value for a source, or ``None``.

    ``--trusted-host`` is a hostname allowlist; it's meaningless for a
    hostless URL (file:// has no host to trust or distrust) and pip's own
    source-is-verified bookkeeping (verify_ssl) has no way to express "not
    applicable" - it's a plain bool (see
    plette.models.sources.Source.__SCHEMA__). Skipping on a missing host
    avoids emitting the nonsensical literal "--trusted-host None" regardless
    of what verify_ssl says.

    Only the hostname and optional port are returned, never URL credentials.
    Keep the name descriptive of that value: CodeQL treats names containing
    ``trusted`` as sources of secrets (code-scanning alert #27).
    """
    if verify_ssl:
        return None
    url_parts = parse_url(url)
    host = url_parts.host
    if not host:
        return None
    if "$" in host:
        # parse_url lowercases the host, which breaks a ${ENV_VAR} placeholder.
        authority = url.partition("//")[2].partition("/")[0]
        start = authority.lower().rfind(host)
        if start != -1:
            host = authority[start : start + len(host)]
    port = f":{url_parts.port}" if url_parts.port else ""
    return f"{host}{port}"


def prepare_pip_source_args(sources, pip_args=None):
    """Build pip CLI args for ``sources``.

    Credentials embedded in source URLs are stripped before they are added
    to the argument list — argv is exposed to other local users via
    ``ps aux`` and ``/proc/<pid>/cmdline``, so passing secrets there leaks
    them.  Pip recovers the credentials from a netrc file that pipenv
    writes alongside the subprocess invocation (or from any user-configured
    keyring/netrc).  See GHSA-8xgg-v3jj-95m2.
    """
    def _add_trusted_host_if_needed(url, verify_ssl):
        host_and_port = get_insecure_source_host(url, verify_ssl)
        if host_and_port:
            pip_args.extend(["--trusted-host", host_and_port])

    if pip_args is None:
        pip_args = []
    if sources:
        # Add the source to pip.
        package_url = sources[0].get("url")
        if not package_url:
            raise PipenvUsageError("[[source]] section does not contain a URL.")
        sanitized_url, _ = _strip_credentials_from_url(package_url)
        pip_args.extend(["-i", sanitized_url])
        _add_trusted_host_if_needed(sanitized_url, sources[0].get("verify_ssl", True))
        # Add additional sources as extra indexes.
        if len(sources) > 1:
            for source in sources[1:]:
                url = source.get("url")
                if not url:  # not harmless, just don't continue
                    continue
                sanitized_extra_url, _ = _strip_credentials_from_url(url)
                pip_args.extend(["--extra-index-url", sanitized_extra_url])
                _add_trusted_host_if_needed(
                    sanitized_extra_url, source.get("verify_ssl", True)
                )
    return pip_args


def get_project_index(
    project: Project,
    index: str | TSource | None = None,
    trusted_hosts: list[str] | None = None,
) -> TSource:
    from pipenv.utils.internet import is_valid_url
    from pipenv.utils.sources import SourceNotFound

    if trusted_hosts is None:
        trusted_hosts = []
    if isinstance(index, Mapping):
        return project.sources.find_source(index.get("url"))
    try:
        source = project.sources.find_source(index)
    except SourceNotFound:
        # If the index is not found and it's not a valid URL, raise an error
        if not is_valid_url(index):
            available_sources = ", ".join(
                f"'{s.get('name')}'" for s in project.sources.all if s.get("name")
            )
            raise PipenvUsageError(
                f"Index '{index}' was not found in Pipfile sources and is not a valid URL.\n"
                f"Available sources: {available_sources or 'none'}\n"
                f"Hint: Use a valid URL or add the index to your Pipfile [[source]] section."
            )
        index_url = parse_url(index)
        src_name = project.sources.src_name_from_url(index)
        verify_ssl = index_url.host not in trusted_hosts
        source = {"url": index, "verify_ssl": verify_ssl, "name": src_name}
    return source


def get_source_list(
    project: Project,
    index: str | TSource | None = None,
    extra_indexes: str | list[str] | None = None,
    trusted_hosts: list[str] | None = None,
    pypi_mirror: str | None = None,
) -> list[TSource]:
    sources = project.sources.all[:]
    if index:
        sources.append(get_project_index(project, index))
    if extra_indexes:
        if isinstance(extra_indexes, str):
            extra_indexes = [extra_indexes]

        for source in extra_indexes:
            extra_src = get_project_index(project, source)
            if not sources or extra_src["url"] != sources[0]["url"]:
                sources.append(extra_src)

        for source in project.sources.all:
            if not sources or source["url"] != sources[0]["url"]:
                sources.append(source)

    if pypi_mirror:
        sources = [
            (
                create_mirror_source(pypi_mirror, source["name"])
                if is_pypi_url(source["url"])
                else source
            )
            for source in sources
        ]
    return sources


def parse_indexes(line, strict=False):
    from argparse import ArgumentParser

    comment_re = re.compile(r"(?:^|\s+)#.*$")
    line = comment_re.sub("", line)
    parser = ArgumentParser("indexes", allow_abbrev=False)
    parser.add_argument("-i", "--index-url", dest="index")
    parser.add_argument("--extra-index-url", dest="extra_index")
    parser.add_argument("--trusted-host", dest="trusted_host")
    args, remainder = parser.parse_known_args(line.split())
    index = args.index
    extra_index = args.extra_index
    trusted_host = args.trusted_host
    if (
        strict
        and sum(bool(arg) for arg in (index, extra_index, trusted_host, remainder)) > 1
    ):
        raise ValueError("Index arguments must be on their own lines.")
    return index, extra_index, trusted_host, remainder
