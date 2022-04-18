import re

from urllib3.util import parse_url

from pipenv import environments
from pipenv.exceptions import PipenvUsageError
from pipenv.vendor.vistir.compat import Mapping

from .internet import create_mirror_source, is_pypi_url

if environments.MYPY_RUNNING:
    from typing import List, Optional, Union  # noqa

    from pipenv.project import Project, TSource  # noqa


def prepare_pip_source_args(sources, pip_args=None):
    if pip_args is None:
        pip_args = []
    if sources:
        # Add the source to notpip.
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


def get_project_index(project, index=None, trusted_hosts=None):
    # type: (Optional[Union[str, TSource]], Optional[List[str]], Optional[Project]) -> TSource
    from pipenv.project import SourceNotFound

    if trusted_hosts is None:
        trusted_hosts = []
    if isinstance(index, Mapping):
        return project.find_source(index.get("url"))
    try:
        source = project.find_source(index)
    except SourceNotFound:
        index_url = parse_url(index)
        src_name = project.src_name_from_url(index)
        verify_ssl = index_url.host not in trusted_hosts
        source = {"url": index, "verify_ssl": verify_ssl, "name": src_name}
    return source


def get_source_list(
    project,  # type: Project
    index=None,  # type: Optional[Union[str, TSource]]
    extra_indexes=None,  # type: Optional[List[str]]
    trusted_hosts=None,  # type: Optional[List[str]]
    pypi_mirror=None,  # type: Optional[str]
):
    # type: (...) -> List[TSource]
    sources = []  # type: List[TSource]
    if index:
        sources.append(get_project_index(project, index))
    if extra_indexes:
        if isinstance(extra_indexes, str):
            extra_indexes = [extra_indexes]
        for source in extra_indexes:
            extra_src = get_project_index(project, source)
            if not sources or extra_src["url"] != sources[0]["url"]:
                sources.append(extra_src)
        else:
            for source in project.pipfile_sources:
                if not sources or source["url"] != sources[0]["url"]:
                    sources.append(source)
    if not sources:
        sources = project.pipfile_sources[:]
    if pypi_mirror:
        sources = [
            create_mirror_source(pypi_mirror) if is_pypi_url(source["url"]) else source
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
