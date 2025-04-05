import errno
import os
import re
import shlex
import shutil
import stat
import sys
import warnings
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path, PurePath

from pipenv.utils import err
from pipenv.utils.fileutils import normalize_drive
from pipenv.vendor import click
from pipenv.vendor.pythonfinder.utils import ensure_path, parse_python_version

from .constants import FALSE_VALUES, SCHEME_LIST, TRUE_VALUES
from .processes import subprocess_run


@lru_cache
def make_posix(path: str) -> str:
    """
    Convert a path with possible windows-style separators to a posix-style path
    (with **/** separators instead of **\\** separators).

    :param Text path: A path to convert.
    :return: A converted posix-style path
    :rtype: Text

    >>> make_posix("c:/users/user/venvs/some_venv\\Lib\\site-packages")
    "c:/users/user/venvs/some_venv/Lib/site-packages"

    >>> make_posix("c:\\users\\user\\venvs\\some_venv")
    "c:/users/user/venvs/some_venv"
    """
    if not isinstance(path, str):
        raise TypeError(f"Expected a string for path, received {path!r}...")
    return Path(path).as_posix()


@contextmanager
def chdir(path):
    """Context manager to change working directories."""
    if not path:
        return

    # Store the current working directory
    prev_cwd = Path.cwd()

    # Convert input path to Path object if it's not already
    path_obj = Path(path) if not isinstance(path, Path) else path

    # Change directory using the resolved path
    os.chdir(path_obj.resolve())

    try:
        yield
    finally:
        # Change back to previous directory
        os.chdir(prev_cwd)


def looks_like_dir(path):
    """
    Determine if a path looks like a directory by checking for path separators
    or if it's already a Path object.

    :param path: A string path or Path object
    :return: True if the path appears to be a directory, False otherwise
    """
    # If it's already a Path or PurePath object, it's directory-like
    if isinstance(path, (Path, PurePath)):
        return True

    # Convert to string if needed
    path_str = str(path)

    # Check if it has a trailing slash which would indicate a directory
    if path_str.endswith(os.path.sep) or (
        os.path.altsep and path_str.endswith(os.path.altsep)
    ):
        return True

    # Create a PurePath which won't access the filesystem
    pure_path = PurePath(path_str)

    # If it has multiple parts, it likely has directory separators
    return len(pure_path.parts) > 1


def load_path(python):
    import json
    from pathlib import Path

    python = Path(python).as_posix()
    c = subprocess_run([python, "-c", "import json, sys; print(json.dumps(sys.path))"])
    if c.returncode == 0:
        return json.loads(c.stdout.strip())
    else:
        return []


def path_to_url(path):
    """
    Convert a file system path to a URI.

    First normalizes drive letter case on Windows, then converts to absolute path,
    and finally to a URI.
    """
    path_obj = Path(path).resolve()
    normalized_path = normalize_drive(str(path_obj))
    return Path(normalized_path).as_uri()


def get_windows_path(*args):
    """Sanitize a path for windows environments

    Accepts an arbitrary list of arguments and makes a clean windows path

    Returns a fully resolved windows path as a string
    """
    # Create and resolve the path
    path = Path(*args).resolve()

    # Return the string representation of the path (Windows-friendly)
    return str(path)


def find_windows_executable(bin_path, exe_name):
    """Given an executable name, search the given location for an executable"""
    bin_path = Path(bin_path)
    requested_path = get_windows_path(str(bin_path), exe_name)
    requested_path_obj = Path(requested_path)

    if requested_path_obj.is_file():
        return requested_path_obj

    try:
        pathext = os.environ["PATHEXT"]
    except KeyError:
        pass
    else:
        for ext in pathext.split(os.pathsep):
            path_str = get_windows_path(str(bin_path), exe_name + ext.strip().lower())
            path = Path(path_str)
            if path.is_file():
                return path

    # shutil.which returns a string or None
    which_result = shutil.which(exe_name)
    return Path(which_result) if which_result else None


def walk_up(bottom):
    """Mimic os.walk, but walk 'up' instead of down the directory tree."""
    # Convert to Path object and resolve to absolute path
    bottom_path = Path(bottom).resolve()

    # Get files in current dir
    try:
        # Path.iterdir() returns Path objects for all children
        path_objects = list(bottom_path.iterdir())
    except Exception:
        return

    # Sort into directories and non-directories
    dirs, nondirs = [], []
    for path in path_objects:
        if path.is_dir():
            dirs.append(path.name)
        else:
            nondirs.append(path.name)

    yield str(bottom_path), dirs, nondirs

    # Get parent directory
    new_path = bottom_path.parent.resolve()

    # See if we are at the top (parent is same as current)
    if new_path == bottom_path:
        return

    yield from walk_up(new_path)


def find_requirements(max_depth=3):
    """Returns the path of a requirements.txt file in parent directories."""
    i = 0
    for c, _, _ in walk_up(os.getcwd()):
        i += 1
        if i < max_depth:
            r = Path(c) / "requirements.txt"
            if r.is_file():
                return str(r)

    raise RuntimeError("No requirements.txt found!")


# Borrowed from Pew.
# See https://github.com/berdario/pew/blob/master/pew/_utils.py#L82
@contextmanager
def temp_environ():
    """Allow the ability to set os.environ temporarily"""
    environ = dict(os.environ)
    try:
        yield

    finally:
        os.environ.clear()
        os.environ.update(environ)


def escape_cmd(cmd):
    if any(special_char in cmd for special_char in ["<", ">", "&", ".", "^", "|", "?"]):
        cmd = f'"{cmd}"'
    return cmd


def safe_expandvars(value):
    """
    Expand environment variables in a string value, do nothing for non-strings.

    Note: pathlib.Path doesn't have an expandvars method, so we still use os.path.expandvars
    for the actual expansion.
    """
    if isinstance(value, str):
        return os.path.expandvars(value)
    # Handle Path objects
    elif isinstance(value, Path):
        expanded_str = os.path.expandvars(str(value))
        return Path(expanded_str)
    return value


def cmd_list_to_shell(args):
    """Convert a list of arguments to a quoted shell command."""
    return " ".join(shlex.quote(str(token)) for token in args)


def get_workon_home():
    workon_home = os.environ.get("WORKON_HOME")
    if not workon_home:
        if os.name == "nt":
            workon_home = Path("~/.virtualenvs")
        else:
            xdg_data_home = os.environ.get("XDG_DATA_HOME", "~/.local/share")
            workon_home = Path(xdg_data_home) / "virtualenvs"
    else:
        workon_home = Path(workon_home)

    # Expand environment variables if present in the path string
    if isinstance(workon_home, Path):
        path_str = str(workon_home)
        if "$" in path_str:
            workon_home = safe_expandvars(path_str)

    # Expand user directory and ensure path is absolute
    expanded_path = workon_home.expanduser()
    expanded_path = ensure_path(expanded_path)

    # Create directory if it does not already exist
    expanded_path.mkdir(parents=True, exist_ok=True)
    return expanded_path


def is_file(package):
    """Determine if a package name is for a File dependency."""
    # Check if it's a dictionary-like object with keys
    if hasattr(package, "keys"):
        return any(key for key in package if key in ["file", "path"])

    # Convert to string if it's a Path object, or use as is
    package_str = str(package)

    # Check if the path exists as a file
    try:
        return Path(package_str).exists()
    except (OSError, ValueError):
        # Handle invalid path syntax
        pass

    # Check if the string starts with any of the scheme prefixes
    return any(package_str.startswith(start) for start in SCHEME_LIST)


def is_virtual_environment(path):
    """Check if a given path is a virtual environment's root.

    This is done by checking if the directory contains a Python executable in
    its bin/Scripts directory. Not technically correct, but good enough for
    general usage.
    """
    if not path.is_dir():
        return False
    for bindir_name in ("bin", "Scripts"):
        for python in path.joinpath(bindir_name).glob("python*"):
            try:
                exeness = python.is_file() and os.access(str(python), os.X_OK)
            except OSError:
                exeness = False
            if exeness:
                return True
    return False


def find_python(finder, line=None):
    """
    Given a `pythonfinder.Finder` instance and an optional line, find a corresponding python

    :param finder: A :class:`pythonfinder.Finder` instance to use for searching
    :type finder: :class:pythonfinder.Finder`
    :param str line: A version, path, name, or nothing, defaults to None
    :return: A path to python
    :rtype: str
    """
    if line and not isinstance(line, str):
        raise TypeError(f"Invalid python search type: expected string, received {line!r}")

    if line:
        modified_line = line
        path_obj = Path(modified_line)

        # Add .exe extension on Windows if needed
        if (
            os.name == "nt"
            and not path_obj.exists()
            and not modified_line.lower().endswith(".exe")
        ):
            modified_line += ".exe"
            path_obj = Path(modified_line)

        if path_obj.exists() and shutil.which(modified_line):
            return str(path_obj)

    if not finder:
        from pipenv.vendor.pythonfinder import Finder

        finder = Finder(global_search=True)

    if not line:
        result = next(iter(finder.find_all_python_versions()), None)
    elif line and line[0].isdigit() or re.match(r"^\d+(\.\d+)*$", line):
        version_info = parse_python_version(line)
        result = finder.find_python_version(
            major=version_info.get("major"),
            minor=version_info.get("minor"),
            patch=version_info.get("patch"),
            pre=version_info.get("is_prerelease"),
            dev=version_info.get("is_devrelease"),
        )
    else:
        result = finder.find_python_version(name=line)

    if not result:
        result = finder.which(line)

    if not result and "python" not in line.lower():
        line = f"python{line}"
        result = find_python(finder, line)

    if result:
        if not isinstance(result, str):
            if hasattr(result, "path"):  # It's a PythonInfo object
                # Already using .as_posix() which is pathlib-friendly
                return result.path.as_posix()
            else:  # It's a Path object
                return str(result)
        return result
    return None


def is_python_command(line):
    """
    Given an input, checks whether the input is a request for python or notself.

    This can be a version, a python runtime name, or a generic 'python' or 'pythonX.Y'

    :param str line: A potential request to find python
    :returns: Whether the line is a python lookup
    :rtype: bool
    """

    if not isinstance(line, str):
        raise TypeError(f"Not a valid command to check: {line!r}")

    from pipenv.vendor.pythonfinder.utils import PYTHON_IMPLEMENTATIONS

    is_version = re.match(r"\d+(\.\d+)*", line)
    if (
        line.startswith("python")
        or is_version
        or any(line.startswith(v) for v in PYTHON_IMPLEMENTATIONS)
    ):
        return True
    # we are less sure about this but we can guess
    if line.startswith("py"):
        return True
    return False


@contextmanager
def temp_path():
    """Allow the ability to set os.environ temporarily"""
    path = list(sys.path)
    try:
        yield
    finally:
        sys.path = list(path)


def is_readonly_path(fn):
    """Check if a provided path exists and is readonly.

    Permissions check is `bool(path.stat & stat.S_IREAD)` or `not os.access(path, os.W_OK)`
    """
    path = Path(fn) if not isinstance(fn, Path) else fn
    if path.exists():
        return (path.stat().st_mode & stat.S_IREAD) or not os.access(path, os.W_OK)

    return False


def set_write_bit(fn):
    path = Path(fn) if not isinstance(fn, Path) else fn
    if not path.exists():
        return
    path.chmod(stat.S_IWRITE | stat.S_IWUSR | stat.S_IRUSR)
    return


def handle_remove_readonly(func, path, exc):
    """Error handler for shutil.rmtree.

    Windows source repo folders are read-only by default, so this error handler
    attempts to set them as writeable and then proceed with deletion."""
    # Check for read-only attribute
    default_warning_message = "Unable to remove file due to permissions restriction: {!r}"
    # split the initial exception out into its type, exception, and traceback
    exc_type, exc_exception, exc_tb = exc
    if is_readonly_path(path):
        # Apply write permission and call original function
        set_write_bit(path)
        try:
            func(path)
        except OSError as e:
            if e.errno in [errno.EACCES, errno.EPERM]:
                warnings.warn(
                    default_warning_message.format(path), ResourceWarning, stacklevel=1
                )
                return

    if exc_exception.errno in [errno.EACCES, errno.EPERM]:
        warnings.warn(default_warning_message.format(path), ResourceWarning, stacklevel=1)
        return

    raise exc


def style_no_color(text, fg=None, bg=None, **kwargs) -> str:
    """Wrap click style to ignore colors."""
    if hasattr(click, "original_style"):
        return click.original_style(text, **kwargs)
    return click.style(text, **kwargs)


def env_to_bool(val):
    """
    Convert **val** to boolean, returning True if truthy or False if falsey

    :param Any val: The value to convert
    :return: False if falsey, True if truthy
    :rtype: bool
    :raises:
        ValueError: if val is not a valid boolean-like
    """
    if val is None:
        return False
    if isinstance(val, bool):
        return val

    try:
        if val.lower() in FALSE_VALUES:
            return False
        if val.lower() in TRUE_VALUES:
            return True
    except AttributeError:
        pass

    raise ValueError(f"Value is not a valid boolean-like: {val}")


def is_env_truthy(name):
    """An environment variable is truthy if it exists and isn't one of (0, false, no, off)"""
    value = os.getenv(name)
    if value is None:
        return False
    return env_to_bool(value)


def project_python(project, system=False):
    if not system:
        python = project._which("python")
    else:
        interpreters = [system_which(p) for p in ("python3", "python")]
        interpreters = [i for i in interpreters if i]  # filter out not found interpreters
        python = interpreters[0] if interpreters else None
    if not python:
        err.print("The Python interpreter can't be found.", style="red")
        sys.exit(1)
    return Path(python).as_posix()


def system_which(command, path=None):
    """Emulates the system's which. Returns None if not found."""
    import shutil

    result = shutil.which(command, path=path)
    if result is None:
        _which = "where" if os.name == "nt" else "which -a"
        env = {"PATH": path} if path else None
        c = subprocess_run(f"{_which} {command}", shell=True, env=env)
        if c.returncode == 127:
            err.print(
                f"[bold][red]Warning[/red][/bold]: the [yellow]{_which}[/yellow]"
                "system utility is required for Pipenv to find Python installations properly."
                "\nPlease install it."
            )
        if c.returncode == 0:
            result = next(iter(c.stdout.splitlines()), None)
    return result


def shorten_path(location, bold=False):
    """Returns a visually shorter representation of a given system path."""
    path = Path(location) if not isinstance(location, Path) else location
    path_parts = list(path.parts)
    short_parts = [p[0] if len(p) > len("2long4") else p for p in path_parts[:-1]]
    short_parts.append(path_parts[-1])
    if bold:
        short_parts[-1] = f"[bold]{short_parts[-1]}[/bold]"
    return os.sep.join(short_parts)


def isatty(stream):
    try:
        is_a_tty = stream.isatty()
    except Exception:  # pragma: no cover
        is_a_tty = False
    return is_a_tty
