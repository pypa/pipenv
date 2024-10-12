from __future__ import annotations

import ast
import site
import subprocess  # noqa: S404
import sys
from importlib.metadata import Distribution, distributions
from pathlib import Path
from typing import Iterable, Tuple

from pipenv.vendor.packaging.utils import canonicalize_name

from pipenv.vendor.pipdeptree._warning import get_warning_printer


def get_installed_distributions(
    interpreter: str = str(sys.executable),
    local_only: bool = False,  # noqa: FBT001, FBT002
    user_only: bool = False,  # noqa: FBT001, FBT002
) -> list[Distribution]:
    # We assign sys.path here as it used by both importlib.metadata.PathDistribution and pip by default.
    paths = sys.path

    # See https://docs.python.org/3/library/venv.html#how-venvs-work for more details.
    in_venv = sys.prefix != sys.base_prefix

    py_path = Path(interpreter).absolute()
    using_custom_interpreter = py_path != Path(sys.executable).absolute()

    if using_custom_interpreter:
        # We query the interpreter directly to get its `sys.path`. If both --python and --local-only are given, only
        # snatch metadata associated to the interpreter's environment.
        if local_only:
            cmd = "import sys; print([p for p in sys.path if p.startswith(sys.prefix)])"
        else:
            cmd = "import sys; print(sys.path)"

        args = [str(py_path), "-c", cmd]
        result = subprocess.run(args, stdout=subprocess.PIPE, check=False, text=True)  # noqa: S603
        paths = ast.literal_eval(result.stdout)
    elif local_only and in_venv:
        paths = [p for p in paths if p.startswith(sys.prefix)]

    if user_only:
        paths = [p for p in paths if p.startswith(site.getusersitepackages())]

    return filter_valid_distributions(distributions(path=paths))


def filter_valid_distributions(iterable_dists: Iterable[Distribution]) -> list[Distribution]:
    warning_printer = get_warning_printer()

    # Since importlib.metadata.distributions() can return duplicate packages, we need to handle this. pip's approach is
    # to keep track of each package metadata it finds, and if it encounters one again it will simply just ignore it. We
    # take it one step further and warn the user that there are duplicate packages in their environment.
    # See https://github.com/pypa/pip/blob/7c49d06ea4be4635561f16a524e3842817d1169a/src/pip/_internal/metadata/importlib/_envs.py#L34
    seen_dists: dict[str, Distribution] = {}
    first_seen_to_already_seen_dists_dict: dict[Distribution, list[Distribution]] = {}

    # We also need to handle invalid metadata, though we can't get paths to invalid distribution metadata directly since
    # importlib doesn't expose an API for it. We do have the directory they reside in, so let's use that.
    site_dir_with_invalid_metadata: set[str] = set()

    dists = []
    for dist in iterable_dists:
        if not has_valid_metadata(dist):
            site_dir = str(dist.locate_file(""))
            site_dir_with_invalid_metadata.add(site_dir)
            continue
        normalized_name = canonicalize_name(dist.metadata["Name"])
        if normalized_name not in seen_dists:
            seen_dists[normalized_name] = dist
            dists.append(dist)
            continue
        if warning_printer.should_warn():
            already_seen_dists = first_seen_to_already_seen_dists_dict.setdefault(seen_dists[normalized_name], [])
            already_seen_dists.append(dist)

    if warning_printer.should_warn():
        if site_dir_with_invalid_metadata:
            warning_printer.print_multi_line(
                "Missing or invalid metadata found in the following site dirs",
                lambda: render_invalid_metadata_text(site_dir_with_invalid_metadata),
            )
        if first_seen_to_already_seen_dists_dict:
            warning_printer.print_multi_line(
                "Duplicate package metadata found",
                lambda: render_duplicated_dist_metadata_text(first_seen_to_already_seen_dists_dict),
                ignore_fail=True,
            )

    return dists


def has_valid_metadata(dist: Distribution) -> bool:
    return "Name" in dist.metadata


def render_invalid_metadata_text(site_dirs_with_invalid_metadata: set[str]) -> None:
    for site_dir in site_dirs_with_invalid_metadata:
        print(site_dir, file=sys.stderr)  # noqa: T201


FirstSeenWithDistsPair = Tuple[Distribution, Distribution]


def render_duplicated_dist_metadata_text(
    first_seen_to_already_seen_dists_dict: dict[Distribution, list[Distribution]],
) -> None:
    entries_to_pairs_dict: dict[str, list[FirstSeenWithDistsPair]] = {}
    for first_seen, dists in first_seen_to_already_seen_dists_dict.items():
        for dist in dists:
            entry = str(dist.locate_file(""))
            dist_list = entries_to_pairs_dict.setdefault(entry, [])
            dist_list.append((first_seen, dist))

    for entry, pairs in entries_to_pairs_dict.items():
        print(f'"{entry}"', file=sys.stderr)  # noqa: T201
        for first_seen, dist in pairs:
            print(  # noqa: T201
                (
                    f"  {dist.metadata['Name']:<32} {dist.version:<16} (using {first_seen.version},"
                    f" \"{first_seen.locate_file('')}\")"
                ),
                file=sys.stderr,
            )


__all__ = [
    "get_installed_distributions",
]
