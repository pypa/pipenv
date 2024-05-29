from __future__ import annotations

import itertools
import os
import re
import subprocess
from builtins import TimeoutError
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterator

from pipenv.vendor.packaging.version import InvalidVersion, Version

from .environment import PYENV_ROOT
from .exceptions import InvalidPythonVersion

version_re_str = (
    r"(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>(?<=\.)[0-9]+))?\.?"
    r"(?:(?P<prerel>[abc]|rc|dev)(?:(?P<prerelversion>\d+(?:\.\d+)*))?)"
    r"?(?P<postdev>(\.post(?P<post>\d+))?(\.dev(?P<dev>\d+))?)?"
)
version_re = re.compile(version_re_str)


PYTHON_IMPLEMENTATIONS = (
    "python",
    "ironpython",
    "jython",
    "pypy",
    "anaconda",
    "miniconda",
    "stackless",
    "activepython",
    "pyston",
    "micropython",
)
if os.name == "nt":
    KNOWN_EXTS = {"exe", "py", "bat", ""}
else:
    KNOWN_EXTS = {"sh", "bash", "csh", "zsh", "fish", "py", ""}
KNOWN_EXTS = KNOWN_EXTS | set(
    filter(None, os.environ.get("PATHEXT", "").split(os.pathsep))
)
PY_MATCH_STR = (
    r"((?P<implementation>{})(?:\d?(?:\.\d[cpm]{{,3}}))?(?:-?[\d\.]+)*(?!w))".format(
        "|".join(PYTHON_IMPLEMENTATIONS)
    )
)
EXE_MATCH_STR = r"{}(?:\.(?P<ext>{}))?".format(PY_MATCH_STR, "|".join(KNOWN_EXTS))
RE_MATCHER = re.compile(rf"({version_re_str}|{PY_MATCH_STR})")
EXE_MATCHER = re.compile(EXE_MATCH_STR)
RULES_BASE = [
    "*{0}",
    "*{0}?",
    "*{0}?.?",
    "*{0}?.?m",
    "{0}?-?.?",
    "{0}?-?.?.?",
    "{0}?.?-?.?.?",
]
RULES = [rule.format(impl) for impl in PYTHON_IMPLEMENTATIONS for rule in RULES_BASE]

MATCH_RULES = []
for rule in RULES:
    MATCH_RULES.extend([f"{rule}.{ext}" if ext else f"{rule}" for ext in KNOWN_EXTS])


def get_python_version(path) -> str:
    """Get python version string using subprocess from a given path."""
    version_cmd = [
        path,
        "-c",
        "import sys; print('.'.join([str(i) for i in sys.version_info[:3]]))",
    ]
    subprocess_kwargs = {
        "env": os.environ.copy(),
        "universal_newlines": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
    }
    c = subprocess.Popen(version_cmd, **subprocess_kwargs)

    try:
        out, _ = c.communicate()
    except (SystemExit, KeyboardInterrupt, TimeoutError):
        c.terminate()
        out, _ = c.communicate()
        raise
    except OSError:
        raise InvalidPythonVersion("%s is not a valid python path" % path)
    if not out:
        raise InvalidPythonVersion("%s is not a valid python path" % path)
    return out.strip()


def parse_python_version(version_str: str) -> dict[str, str | int | Version]:
    from pipenv.vendor.packaging.version import parse as parse_version

    is_debug = False
    if version_str.endswith("-debug"):
        is_debug = True
        version_str, _, _ = version_str.rpartition("-")
    match = version_re.match(version_str)
    if not match:
        raise InvalidPythonVersion("%s is not a python version" % version_str)
    version_dict = match.groupdict()
    major = int(version_dict.get("major", 0)) if version_dict.get("major") else None
    minor = int(version_dict.get("minor", 0)) if version_dict.get("minor") else None
    patch = int(version_dict.get("patch", 0)) if version_dict.get("patch") else None
    is_postrelease = True if version_dict.get("post") else False
    is_prerelease = True if version_dict.get("prerel") else False
    is_devrelease = True if version_dict.get("dev") else False
    if patch:
        patch = int(patch)

    try:
        version = parse_version(version_str)
    except (TypeError, InvalidVersion):
        version = None

    if version is None:
        v_dict = version_dict.copy()
        pre = ""
        if v_dict.get("prerel") and v_dict.get("prerelversion"):
            pre = v_dict.pop("prerel")
            pre = "{}{}".format(pre, v_dict.pop("prerelversion"))
        v_dict["pre"] = pre
        keys = ["major", "minor", "patch", "pre", "postdev", "post", "dev"]
        values = [v_dict.get(val) for val in keys]
        version_str = ".".join([str(v) for v in values if v])
        version = parse_version(version_str)
    return {
        "major": major,
        "minor": minor,
        "patch": patch,
        "is_postrelease": is_postrelease,
        "is_prerelease": is_prerelease,
        "is_devrelease": is_devrelease,
        "is_debug": is_debug,
        "version": version,
    }


def path_is_executable(path) -> bool:
    """
    Determine whether the supplied path is executable.

    :return: Whether the provided path is executable.
    """

    return os.access(str(path), os.X_OK)


def path_is_known_executable(path: Path) -> bool:
    """
    Returns whether a given path is a known executable from known executable extensions
    or has the executable bit toggled.

    :param path: The path to the target executable.
    :return: True if the path has chmod +x, or is a readable, known executable extension.
    """

    return (
        path_is_executable(path)
        or os.access(str(path), os.R_OK)
        and path.suffix in KNOWN_EXTS
    )


def looks_like_python(name: str) -> bool:
    """
    Determine whether the supplied filename looks like a possible name of python.

    :param str name: The name of the provided file.
    :return: Whether the provided name looks like python.
    """

    if not any(name.lower().startswith(py_name) for py_name in PYTHON_IMPLEMENTATIONS):
        return False
    match = RE_MATCHER.match(name)
    if match:
        return any(fnmatch(name, rule) for rule in MATCH_RULES)
    return False


def path_is_python(path: Path) -> bool:
    """
    Determine whether the supplied path is executable and looks like a possible path to python.

    :param path: The path to an executable.
    :type path: :class:`~Path`
    :return: Whether the provided path is an executable path to python.
    """

    return path_is_executable(path) and looks_like_python(path.name)


def guess_company(path: str) -> str | None:
    """Given a path to python, guess the company who created it

    :param str path: The path to guess about
    :return: The guessed company
    """
    non_core_pythons = [impl for impl in PYTHON_IMPLEMENTATIONS if impl != "python"]
    return next(
        iter(impl for impl in non_core_pythons if impl in path.lower()), "PythonCore"
    )


def path_is_pythoncore(path: str) -> bool:
    """Given a path, determine whether it appears to be pythoncore.

    Does not verify whether the path is in fact a path to python, but simply
    does an exclusionary check on the possible known python implementations
    to see if their names are present in the path (fairly dumb check).

    :param str path: The path to check
    :return: Whether that path is a PythonCore path or not
    """
    company = guess_company(path)
    if company:
        return company == "PythonCore"
    return False


def ensure_path(path: Path | str) -> Path:
    """
    Given a path (either a string or a Path object), expand variables and return a Path object.

    :param path: A string or a :class:`~pathlib.Path` object.
    :type path: str or :class:`~pathlib.Path`
    :return: A fully expanded Path object.
    """
    if isinstance(path, Path):
        return path.absolute()
    # Expand environment variables and user tilde in the path
    expanded_path = os.path.expandvars(os.path.expanduser(path))
    return Path(expanded_path).absolute()


def resolve_path(path: Path | str) -> Path:
    """
    Resolves the path to an absolute path, expanding user variables and environment variables.
    """
    # Convert to Path object if it's a string
    if isinstance(path, str):
        path = Path(path)

    # Expand user and variables
    path = path.expanduser()
    path = Path(os.path.expandvars(str(path)))

    # Resolve to absolute path
    return path.resolve()


def filter_pythons(path: str | Path) -> Iterable | Path:
    """Return all valid pythons in a given path"""
    if not isinstance(path, Path):
        path = Path(str(path))
    if not path.is_dir():
        return path if path_is_python(path) else None
    return filter(path_is_python, path.iterdir())


def unnest(item) -> Iterable[Any]:
    if isinstance(item, Iterable) and not isinstance(item, str):
        item, target = itertools.tee(item, 2)
    else:
        target = item
    if getattr(target, "__iter__", None):
        for el in target:
            if isinstance(el, Iterable) and not isinstance(el, str):
                el, el_copy = itertools.tee(el, 2)
                for sub in unnest(el_copy):
                    yield sub
            else:
                yield el
    else:
        yield target


def parse_pyenv_version_order(filename="version") -> list[str]:
    version_order_file = resolve_path(os.path.join(PYENV_ROOT, filename))
    if os.path.exists(version_order_file) and os.path.isfile(version_order_file):
        with open(version_order_file, encoding="utf-8") as fh:
            contents = fh.read()
        version_order = [v for v in contents.splitlines()]
        return version_order
    return []


def parse_asdf_version_order(filename: str = ".tool-versions") -> list[str]:
    version_order_file = resolve_path(os.path.join("~", filename))
    if os.path.exists(version_order_file) and os.path.isfile(version_order_file):
        with open(version_order_file, encoding="utf-8") as fh:
            contents = fh.read()
        python_section = next(
            iter(line for line in contents.splitlines() if line.startswith("python")),
            None,
        )
        if python_section:
            # python_key, _, versions
            _, _, versions = python_section.partition(" ")
            if versions:
                return versions.split()
    return []


def split_version_and_name(
    major: str | int | None = None,
    minor: str | int | None = None,
    patch: str | int | None = None,
    name: str | None = None,
) -> tuple[str | int | None, str | int | None, str | int | None, str | None,]:
    if isinstance(major, str) and not minor and not patch:
        # Only proceed if this is in the format "x.y.z" or similar
        if major.isdigit() or (major.count(".") > 0 and major[0].isdigit()):
            version = major.split(".", 2)
            if isinstance(version, (tuple, list)):
                if len(version) > 3:
                    major, minor, patch, _ = version
                elif len(version) == 3:
                    major, minor, patch = version
                elif len(version) == 2:
                    major, minor = version
                else:
                    major = major[0]
            else:
                major = major
                name = None
        else:
            name = f"{major!s}"
            major = None
    return (major, minor, patch, name)


def is_in_path(path, parent):
    return resolve_path(str(path)).startswith(resolve_path(str(parent)))


def expand_paths(path, only_python=True) -> Iterator:
    """
    Recursively expand a list or :class:`~pythonfinder.models.path.PathEntry` instance

    :param Union[Sequence, PathEntry] path: The path or list of paths to expand
    :param bool only_python: Whether to filter to include only python paths, default True
    :returns: An iterator over the expanded set of path entries
    """

    if path is not None and (
        isinstance(path, Sequence)
        and not getattr(path.__class__, "__name__", "") == "PathEntry"
    ):
        for p in path:
            if p is None:
                continue
            for expanded in itertools.chain.from_iterable(
                expand_paths(p, only_python=only_python)
            ):
                yield expanded
    elif path is not None and path.is_dir:
        for p in path.children_ref.values():
            if p is not None and p.is_python and p.as_python is not None:
                for sub_path in itertools.chain.from_iterable(
                    expand_paths(p, only_python=only_python)
                ):
                    yield sub_path
    else:
        if path is not None and (
            not only_python or (path.is_python and path.as_python is not None)
        ):
            yield path


def dedup(iterable: Iterable) -> Iterable:
    """Deduplicate an iterable object like iter(set(iterable)) but
    order-reserved.
    """
    return iter(OrderedDict.fromkeys(iterable))
