from __future__ import annotations

import re
from argparse import ArgumentParser

from pipenv.exceptions import PipenvUsageError
from pipenv.patched.pip._vendor.urllib3.util import parse_url
from pipenv.utils.internet import create_mirror_source, is_pypi_url


def prepare_pip_source_args(sources, pip_args=None):
    if pip_args is None:
        pip_args = []
    if sources:
        # Add the source to pip.
        package_url = sources[0].get("url")
        if not package_url:
            raise PipenvUsageError("[[source]] section does not contain a URL.")
        pip_args.extend(["-i", package_url])
        # Trust the host if it's not verified.
        if not sources[0].get("verify_ssl", True):
            url_parts = parse_url(package_url)
            url_port = f":{url_parts.port}" if url_parts.port else ""
            pip_args.extend(["--trusted-host", f"{url_parts.host}{url_port}"])
        # Add additional sources as extra indexes.
        if len(sources) > 1:
            for source in sources[1:]:
                url = source.get("url")
                if not url:  # not harmless, just don't continue
                    continue
                pip_args.extend(["--extra-index-url", url])
                # Trust the host if it's not verified.
                if not source.get("verify_ssl", True):
                    url_parts = parse_url(url)
                    url_port = f":{url_parts.port}" if url_parts.port else ""
                    pip_args.extend(["--trusted-host", f"{url_parts.host}{url_port}"])
    return pip_args


def get_source_list(
    project,
    pypi_mirror: str | None = None,
) -> list[dict[str, str | bool]]:
    sources = project.sources[:]

    if pypi_mirror:
        sources = [
            create_mirror_source(pypi_mirror, source["name"])
            if is_pypi_url(source["url"])
            else source
            for source in sources
        ]
    return sources


def parse_indexes(line, strict=False):
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
