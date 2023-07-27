"""The command-line interface for the unearth package."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass

from pipenv.patched.pip._vendor.packaging.requirements import Requirement

from pipenv.vendor.unearth.evaluator import TargetPython
from pipenv.vendor.unearth.finder import PackageFinder
from pipenv.vendor.unearth.link import Link
from pipenv.vendor.unearth.utils import splitext


@dataclass(frozen=True)
class CLIArgs:
    requirement: Requirement
    verbose: bool
    index_urls: list[str]
    find_links: list[str]
    trusted_hosts: list[str]
    no_binary: bool
    only_binary: bool
    prefer_binary: bool
    all: bool
    link_only: bool
    download: str | None
    py_ver: tuple[int, ...] | None
    abis: list[str] | None
    impl: str | None
    platforms: list[str] | None


def _setup_logger(verbosity: bool) -> None:
    logger = logging.getLogger("unearth")
    logger.setLevel(logging.DEBUG if verbosity else logging.WARNING)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def comma_split(arg: str) -> list[str]:
    return arg.split(",")


def to_py_ver(arg: str) -> tuple[int, ...]:
    return tuple(int(i) for i in arg.split(".") if i.isdigit())


def cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find and download packages from a PEP 508 requirement string.",
    )
    parser.add_argument(
        "requirement",
        type=Requirement,
        help="A PEP 508 requirement string, e.g. 'requests>=2.18.4'.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging."
    )
    parser.add_argument(
        "--index-url",
        "-i",
        metavar="URL",
        dest="index_urls",
        action="append",
        help="(Multiple)(PEP 503)Simple Index URLs.",
    )
    parser.add_argument(
        "--find-link",
        "-f",
        dest="find_links",
        metavar="LOCATION",
        action="append",
        help="(Multiple)URLs or locations to find links from.",
    )
    parser.add_argument(
        "--trusted-host",
        dest="trusted_hosts",
        metavar="HOST",
        action="append",
        help="(Multiple)Trusted hosts that should skip the verification.",
    )
    parser.add_argument(
        "--no-binary",
        action="store_true",
        help="Exclude binary packages from the results.",
    )
    parser.add_argument(
        "--only-binary",
        action="store_true",
        help="Only include binary packages in the results.",
    )
    parser.add_argument(
        "--prefer-binary",
        action="store_true",
        help="Prefer binary packages even if sdist candidates of newer versions exist.",
    )
    parser.add_argument(
        "--all", action="store_true", help="Return all applicable versions."
    )
    parser.add_argument(
        "--link-only",
        "-L",
        action="store_true",
        help="Only return links instead of a JSON object.",
    )
    parser.add_argument(
        "--download",
        "-d",
        nargs="?",
        const=".",
        metavar="DIR",
        help="Download the package(s) to DIR.",
    )
    group = parser.add_argument_group("Target Python options")
    group.add_argument(
        "--python-version",
        "--py",
        dest="py_ver",
        type=to_py_ver,
        help="Target Python version. e.g. 3.11.0",
    )
    group.add_argument(
        "--abis", type=comma_split, help="Comma-separated list of ABIs. e.g. cp39,cp310"
    )
    group.add_argument(
        "--implementation",
        "--impl",
        dest="impl",
        help="Python implementation. e.g. cp,pp,jy,ip",
    )
    group.add_argument(
        "--platforms",
        type=comma_split,
        help="Comma-separated list of platforms. e.g. win_amd64,linux_x86_64",
    )
    return parser


def get_dest_for_package(dest: str, link: Link) -> str:
    if link.is_wheel:
        return dest
    filename = link.filename.rsplit("@", 1)[0]
    fn, _ = splitext(filename)
    return os.path.join(dest, fn)


def cli(argv: list[str] | None = None) -> None:
    parser = cli_parser()
    args = CLIArgs(**vars(parser.parse_args(argv)))
    _setup_logger(args.verbose)
    name = args.requirement.name
    target_python = TargetPython(args.py_ver, args.abis, args.impl, args.platforms)
    finder = PackageFinder(
        index_urls=args.index_urls or ["https://pypi.org/simple/"],
        find_links=args.find_links or [],
        trusted_hosts=args.trusted_hosts or [],
        target_python=target_python,
        no_binary=[name] if args.no_binary else [],
        only_binary=[name] if args.only_binary else [],
        prefer_binary=[name] if args.prefer_binary else [],
        verbosity=int(args.verbose),
    )
    matches = list(finder.find_matches(args.requirement))
    if not matches:
        print("No matches are found.", file=sys.stderr)
        sys.exit(1)
    if not args.all:
        matches = matches[:1]

    result = []
    if args.download:
        os.makedirs(args.download, exist_ok=True)
    with tempfile.TemporaryDirectory("unearth-download-") as download_dir:
        for match in matches:
            data = match.as_json()
            if args.download is not None:
                dest = get_dest_for_package(args.download, match.link)
                data["local_path"] = finder.download_and_unpack(
                    match.link,
                    dest,
                    download_dir,
                ).as_posix()
            result.append(data)
    if args.link_only:
        for item in result:
            print(item["link"]["url"])
            if "local_path" in item:
                print("  ==>", item["local_path"])
    else:
        print(json.dumps(result[0] if len(result) == 1 else result, indent=2))


if __name__ == "__main__":
    cli()
