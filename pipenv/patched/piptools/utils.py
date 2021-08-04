import collections
import itertools
import json
import os
import shlex
from typing import (
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

import click
from click.utils import LazyFile
from pip._internal.req import InstallRequirement
from pip._internal.req.constructors import install_req_from_line
from pip._internal.utils.misc import redact_auth_from_url
from pip._internal.vcs import is_url
from pip._vendor.packaging.markers import Marker
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.version import Version
from pip._vendor.pkg_resources import get_distribution

from piptools.subprocess_utils import run_python_snippet

_KT = TypeVar("_KT")
_VT = TypeVar("_VT")
_T = TypeVar("_T")
_S = TypeVar("_S")

UNSAFE_PACKAGES = {"setuptools", "distribute", "pip"}
COMPILE_EXCLUDE_OPTIONS = {
    "--dry-run",
    "--quiet",
    "--rebuild",
    "--upgrade",
    "--upgrade-package",
    "--verbose",
    "--cache-dir",
    "--no-reuse-hashes",
}


def key_from_ireq(ireq: InstallRequirement) -> str:
    """Get a standardized key for an InstallRequirement."""
    if ireq.req is None and ireq.link is not None:
        return str(ireq.link)
    else:
        return key_from_req(ireq.req)


def key_from_req(req: InstallRequirement) -> str:
    """Get an all-lowercase version of the requirement's name."""
    if hasattr(req, "key"):
        # from pkg_resources, such as installed dists for pip-sync
        key = req.key
    else:
        # from packaging, such as install requirements from requirements.txt
        key = req.name
    assert isinstance(key, str)
    key = key.replace("_", "-").lower()
    return key


def comment(text: str) -> str:
    return click.style(text, fg="green")


def make_install_requirement(
    name: str, version: Union[str, Version], ireq: InstallRequirement
) -> InstallRequirement:
    # If no extras are specified, the extras string is blank
    extras_string = ""
    extras = ireq.extras
    if extras:
        # Sort extras for stability
        extras_string = f"[{','.join(sorted(extras))}]"

    version_pin_operator = "=="
    version_as_str = str(version)
    for specifier in ireq.specifier:
        if specifier.operator == "===" and specifier.version == version_as_str:
            version_pin_operator = "==="
            break

    return install_req_from_line(
        str(f"{name}{extras_string}{version_pin_operator}{version}"),
        constraint=ireq.constraint,
    )


def is_url_requirement(ireq: InstallRequirement) -> bool:
    """
    Return True if requirement was specified as a path or URL.
    ireq.original_link will have been set by InstallRequirement.__init__
    """
    return bool(ireq.original_link)


def format_requirement(
    ireq: InstallRequirement,
    marker: Optional[Marker] = None,
    hashes: Optional[Set[str]] = None,
) -> str:
    """
    Generic formatter for pretty printing InstallRequirements to the terminal
    in a less verbose way than using its `__str__` method.
    """
    if ireq.editable:
        line = f"-e {ireq.link.url}"
    elif is_url_requirement(ireq):
        line = ireq.link.url
    else:
        line = str(ireq.req).lower()

    if marker:
        line = f"{line} ; {marker}"

    if hashes:
        for hash_ in sorted(hashes):
            line += f" \\\n    --hash={hash_}"

    return line


def format_specifier(ireq: InstallRequirement) -> str:
    """
    Generic formatter for pretty printing the specifier part of
    InstallRequirements to the terminal.
    """
    # TODO: Ideally, this is carried over to the pip library itself
    specs = ireq.specifier if ireq.req is not None else SpecifierSet()
    # FIXME: remove ignore type marker once the following issue get fixed
    #        https://github.com/python/mypy/issues/9656
    specs = sorted(specs, key=lambda x: x.version)  # type: ignore
    return ",".join(str(s) for s in specs) or "<any>"


def is_pinned_requirement(ireq: InstallRequirement) -> bool:
    """
    Returns whether an InstallRequirement is a "pinned" requirement.

    An InstallRequirement is considered pinned if:

    - Is not editable
    - It has exactly one specifier
    - That specifier is "=="
    - The version does not contain a wildcard

    Examples:
        django==1.8   # pinned
        django>1.8    # NOT pinned
        django~=1.8   # NOT pinned
        django==1.*   # NOT pinned
    """
    if ireq.editable:
        return False

    if ireq.req is None or len(ireq.specifier) != 1:
        return False

    spec = next(iter(ireq.specifier))
    return spec.operator in {"==", "==="} and not spec.version.endswith(".*")


def as_tuple(ireq: InstallRequirement) -> Tuple[str, str, Tuple[str, ...]]:
    """
    Pulls out the (name: str, version:str, extras:(str)) tuple from
    the pinned InstallRequirement.
    """
    if not is_pinned_requirement(ireq):
        raise TypeError(f"Expected a pinned InstallRequirement, got {ireq}")

    name = key_from_ireq(ireq)
    version = next(iter(ireq.specifier)).version
    extras = tuple(sorted(ireq.extras))
    return name, version, extras


def flat_map(
    fn: Callable[[_T], Iterable[_S]], collection: Iterable[_T]
) -> Iterator[_S]:
    """Map a function over a collection and flatten the result by one-level"""
    return itertools.chain.from_iterable(map(fn, collection))


def lookup_table_from_tuples(values: Iterable[Tuple[_KT, _VT]]) -> Dict[_KT, Set[_VT]]:
    """
    Builds a dict-based lookup table (index) elegantly.
    """
    lut: Dict[_KT, Set[_VT]] = collections.defaultdict(set)
    for k, v in values:
        lut[k].add(v)
    return dict(lut)


def lookup_table(
    values: Iterable[_VT], key: Callable[[_VT], _KT]
) -> Dict[_KT, Set[_VT]]:
    """
    Builds a dict-based lookup table (index) elegantly.
    """
    return lookup_table_from_tuples((key(v), v) for v in values)


def dedup(iterable: Iterable[_T]) -> Iterable[_T]:
    """Deduplicate an iterable object like iter(set(iterable)) but
    order-preserved.
    """
    return iter(dict.fromkeys(iterable))


def drop_extras(ireq: InstallRequirement) -> None:
    """Remove "extra" markers (PEP-508) from requirement."""
    if ireq.markers is None:
        return
    ireq.markers._markers = _drop_extras(ireq.markers._markers)
    if not ireq.markers._markers:
        ireq.markers = None


def _drop_extras(markers: List[_T]) -> List[_T]:
    # drop `extra` tokens
    to_remove: List[int] = []
    for i, token in enumerate(markers):
        # operator (and/or)
        if isinstance(token, str):
            continue
        # sub-expression (inside braces)
        if isinstance(token, list):
            markers[i] = _drop_extras(token)  # type: ignore
            if markers[i]:
                continue
            to_remove.append(i)
            continue
        # test expression (like `extra == "dev"`)
        assert isinstance(token, tuple)
        if token[0].value == "extra":
            to_remove.append(i)
    for i in reversed(to_remove):
        markers.pop(i)

    # drop duplicate bool operators (and/or)
    to_remove = []
    for i, (token1, token2) in enumerate(zip(markers, markers[1:])):
        if not isinstance(token1, str):
            continue
        if not isinstance(token2, str):
            continue
        if token1 == "and":
            to_remove.append(i)
        else:
            to_remove.append(i + 1)
    for i in reversed(to_remove):
        markers.pop(i)
    if markers and isinstance(markers[0], str):
        markers.pop(0)
    if markers and isinstance(markers[-1], str):
        markers.pop(-1)

    return markers


def get_hashes_from_ireq(ireq: InstallRequirement) -> Set[str]:
    """
    Given an InstallRequirement, return a set of string hashes in the format
    "{algorithm}:{hash}". Return an empty set if there are no hashes in the
    requirement options.
    """
    result = set()
    for algorithm, hexdigests in ireq.hash_options.items():
        for hash_ in hexdigests:
            result.add(f"{algorithm}:{hash_}")
    return result


def get_compile_command(click_ctx: click.Context) -> str:
    """
    Returns a normalized compile command depending on cli context.

    The command will be normalized by:
        - expanding options short to long
        - removing values that are already default
        - sorting the arguments
        - removing one-off arguments like '--upgrade'
        - removing arguments that don't change build behaviour like '--verbose'
    """
    from piptools.scripts.compile import cli

    # Map of the compile cli options (option name -> click.Option)
    compile_options = {option.name: option for option in cli.params}

    left_args = []
    right_args = []

    for option_name, value in click_ctx.params.items():
        option = compile_options[option_name]

        # Collect variadic args separately, they will be added
        # at the end of the command later
        if option.nargs < 0:
            # These will necessarily be src_files
            # Re-add click-stripped '--' if any start with '-'
            if any(val.startswith("-") and val != "-" for val in value):
                right_args.append("--")
            right_args.extend([shlex.quote(val) for val in value])
            continue

        assert isinstance(option, click.Option)

        # Get the latest option name (usually it'll be a long name)
        option_long_name = option.opts[-1]

        # Exclude one-off options (--upgrade/--upgrade-package/--rebuild/...)
        # or options that don't change compile behaviour (--verbose/--dry-run/...)
        if option_long_name in COMPILE_EXCLUDE_OPTIONS:
            continue

        # Skip options without a value
        if option.default is None and not value:
            continue

        # Skip options with a default value
        if option.default == value:
            continue

        # Use a file name for file-like objects
        if isinstance(value, LazyFile):
            value = value.name

        # Convert value to the list
        if not isinstance(value, (tuple, list)):
            value = [value]

        for val in value:
            # Flags don't have a value, thus add to args true or false option long name
            if option.is_flag:
                # If there are false-options, choose an option name depending on a value
                if option.secondary_opts:
                    # Get the latest false-option
                    secondary_option_long_name = option.secondary_opts[-1]
                    arg = option_long_name if val else secondary_option_long_name
                # There are no false-options, use true-option
                else:
                    arg = option_long_name
                left_args.append(shlex.quote(arg))
            # Append to args the option with a value
            else:
                if isinstance(val, str) and is_url(val):
                    val = redact_auth_from_url(val)
                if option.name == "pip_args_str":
                    # shlex.quote() would produce functional but noisily quoted results,
                    # e.g. --pip-args='--cache-dir='"'"'/tmp/with spaces'"'"''
                    # Instead, we try to get more legible quoting via repr:
                    left_args.append(f"{option_long_name}={repr(val)}")
                else:
                    left_args.append(f"{option_long_name}={shlex.quote(str(val))}")

    return " ".join(["pip-compile", *sorted(left_args), *sorted(right_args)])


def get_required_pip_specification() -> SpecifierSet:
    """
    Returns pip version specifier requested by current pip-tools installation.
    """
    project_dist = get_distribution("pip-tools")
    requirement = next(  # pragma: no branch
        (r for r in project_dist.requires() if r.name == "pip"), None
    )
    assert (
        requirement is not None
    ), "'pip' is expected to be in the list of pip-tools requirements"
    return requirement.specifier


def get_pip_version_for_python_executable(python_executable: str) -> Version:
    """
    Returns pip version for the given python executable.
    """
    str_version = run_python_snippet(
        python_executable, "import pip;print(pip.__version__)"
    )
    return Version(str_version)


def get_sys_path_for_python_executable(python_executable: str) -> List[str]:
    """
    Returns sys.path list for the given python executable.
    """
    result = run_python_snippet(
        python_executable, "import sys;import json;print(json.dumps(sys.path))"
    )

    paths = json.loads(result)
    assert isinstance(paths, list)
    assert all(isinstance(i, str) for i in paths)
    return [os.path.abspath(path) for path in paths]
