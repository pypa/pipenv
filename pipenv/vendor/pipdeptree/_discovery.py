from __future__ import annotations

import ast
import site
import subprocess  # noqa: S404
import sys
from importlib.metadata import Distribution, distributions
from pathlib import Path
from typing import Iterable, Tuple

from pipenv.vendor.packaging.utils import canonicalize_name


def get_installed_distributions(
    interpreter: str = str(sys.executable),
    local_only: bool = False,  # noqa: FBT001, FBT002
    user_only: bool = False,  # noqa: FBT001, FBT002
) -> list[Distribution]:
    # See https://docs.python.org/3/library/venv.html#how-venvs-work for more details.
    in_venv = sys.prefix != sys.base_prefix
    original_dists: Iterable[Distribution] = []
    py_path = Path(interpreter).absolute()
    using_custom_interpreter = py_path != Path(sys.executable).absolute()

    if user_only:
        original_dists = distributions(path=[site.getusersitepackages()])
    elif using_custom_interpreter:
        # We query the interpreter directly to get its `sys.path` list to be used by `distributions()`.
        # If --python and --local-only are given, we ensure that we are only using paths associated to the interpreter's
        # environment.
        if local_only:
            cmd = "import sys; print([p for p in sys.path if p.startswith(sys.prefix)])"
        else:
            cmd = "import sys; print(sys.path)"

        args = [str(py_path), "-c", cmd]
        result = subprocess.run(args, stdout=subprocess.PIPE, check=False, text=True)  # noqa: S603
        original_dists = distributions(path=ast.literal_eval(result.stdout))
    elif local_only and in_venv:
        venv_site_packages = [p for p in sys.path if p.startswith(sys.prefix)]
        original_dists = distributions(path=venv_site_packages)
    else:
        original_dists = distributions()

    # Since importlib.metadata.distributions() can return duplicate packages, we need to handle this. pip's approach is
    # to keep track of each package metadata it finds, and if it encounters one again it will simply just ignore it. We
    # take it one step further and warn the user that there are duplicate packages in their environment.
    # See https://github.com/pypa/pip/blob/7c49d06ea4be4635561f16a524e3842817d1169a/src/pip/_internal/metadata/importlib/_envs.py#L34
    seen_dists: dict[str, Distribution] = {}
    first_seen_to_already_seen_dists_dict: dict[Distribution, list[Distribution]] = {}
    dists = []
    for dist in original_dists:
        normalized_name = canonicalize_name(dist.metadata["Name"])
        if normalized_name not in seen_dists:
            seen_dists[normalized_name] = dist
            dists.append(dist)
            continue
        already_seen_dists = first_seen_to_already_seen_dists_dict.setdefault(seen_dists[normalized_name], [])
        already_seen_dists.append(dist)

    if first_seen_to_already_seen_dists_dict:
        render_duplicated_dist_metadata_text(first_seen_to_already_seen_dists_dict)

    return dists


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

    print("Warning!!! Duplicate package metadata found:", file=sys.stderr)  # noqa: T201
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
    print("-" * 72, file=sys.stderr)  # noqa: T201


__all__ = [
    "get_installed_distributions",
]
