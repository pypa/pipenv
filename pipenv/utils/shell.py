import errno
import os
import posixpath
import re
import shlex
import shutil
import stat
import sys
import warnings
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from pipenv.vendor import click
from pipenv.vendor.pythonfinder.utils import ensure_path
from pipenv.vendor.requirementslib.fileutils import normalize_drive, normalize_path

from .constants import FALSE_VALUES, SCHEME_LIST, TRUE_VALUES
from .processes import subprocess_run


@lru_cache()
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
    starts_with_sep = path.startswith(os.path.sep)
    separated = normalize_path(path).split(os.path.sep)
    if isinstance(separated, (list, tuple)):
        path = posixpath.join(*separated)
        if starts_with_sep:
            path = f"/{path}"
    return path


@contextmanager
def chdir(path):
    """Context manager to change working directories."""
    if not path:
        return
    prev_cwd = Path.cwd().as_posix()
    if isinstance(path, Path):
        path = path.as_posix()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(prev_cwd)


def looks_like_dir(path):
    seps = (sep for sep in (os.path.sep, os.path.altsep) if sep is not None)
    return any(sep in path for sep in seps)


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
    return Path(normalize_drive(os.path.abspath(path))).as_uri()


def get_windows_path(*args):
    """Sanitize a path for windows environments

    Accepts an arbitrary list of arguments and makes a clean windows path"""
    return os.path.normpath(os.path.join(*args))


def find_windows_executable(bin_path, exe_name):
    """Given an executable name, search the given location for an executable"""
    requested_path = get_windows_path(bin_path, exe_name)
    if os.path.isfile(requested_path):
        return requested_path

    try:
        pathext = os.environ["PATHEXT"]
    except KeyError:
        pass
    else:
        for ext in pathext.split(os.pathsep):
            path = get_windows_path(bin_path, exe_name + ext.strip().lower())
            if os.path.isfile(path):
                return path

    return shutil.which(exe_name)


def walk_up(bottom):
    """Mimic os.walk, but walk 'up' instead of down the directory tree.
    From: https://gist.github.com/zdavkeos/1098474
    """
    bottom = os.path.realpath(bottom)
    # Get files in current dir.
    try:
        names = os.listdir(bottom)
    except Exception:
        return

    dirs, nondirs = [], []
    for name in names:
        if os.path.isdir(os.path.join(bottom, name)):
            dirs.append(name)
        else:
            nondirs.append(name)
    yield bottom, dirs, nondirs

    new_path = os.path.realpath(os.path.join(bottom, ".."))
    # See if we are at the top.
    if new_path == bottom:
        return

    yield from walk_up(new_path)


def find_requirements(max_depth=3):
    """Returns the path of a requirements.txt file in parent directories."""
    i = 0
    for c, _, _ in walk_up(os.getcwd()):
        i += 1
        if i < max_depth:
            r = os.path.join(c, "requirements.txt")
            if os.path.isfile(r):
                return r

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
    """Call os.path.expandvars if value is a string, otherwise do nothing."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    return value


def cmd_list_to_shell(args):
    """Convert a list of arguments to a quoted shell command."""
    return " ".join(shlex.quote(str(token)) for token in args)


def get_workon_home():
    workon_home = os.environ.get("WORKON_HOME")
    if not workon_home:
        if os.name == "nt":
            workon_home = "~/.virtualenvs"
        else:
            workon_home = os.path.join(
                os.environ.get("XDG_DATA_HOME", "~/.local/share"), "virtualenvs"
            )
    # Create directory if it does not already exist
    expanded_path = Path(os.path.expandvars(workon_home)).expanduser()
    expanded_path = ensure_path(expanded_path)
    os.makedirs(expanded_path, exist_ok=True)
    return expanded_path


def is_file(package):
    """Determine if a package name is for a File dependency."""
    if hasattr(package, "keys"):
        return any(key for key in package.keys() if key in ["file", "path"])

    if os.path.exists(str(package)):
        return True

    for start in SCHEME_LIST:
        if str(package).startswith(start):
            return True

    return False


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
        if (
            os.name == "nt"
            and not os.path.exists(modified_line)
            and not modified_line.lower().endswith(".exe")
        ):
            modified_line += ".exe"
        if os.path.exists(modified_line) and shutil.which(modified_line):
            return modified_line

    if not finder:
        from pipenv.vendor.pythonfinder import Finder

        finder = Finder(global_search=True)
    if not line:
        result = next(iter(finder.find_all_python_versions()), None)
    elif line and line[0].isdigit() or re.match(r"^\d+(\.\d+)*$", line):
        result = finder.find_python_version(line)
    else:
        result = finder.find_python_version(name=line)
    if not result:
        result = finder.which(line)
    if not result and not line.startswith("python"):
        line = f"python{line}"
        result = find_python(finder, line)

    if result:
        if not isinstance(result, str):
            return result.path.as_posix()
        return result
    return


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
    path = [p for p in sys.path]
    try:
        yield
    finally:
        sys.path = [p for p in path]


def is_readonly_path(fn):
    """Check if a provided path exists and is readonly.

    Permissions check is `bool(path.stat & stat.S_IREAD)` or `not os.access(path, os.W_OK)`
    """
    if os.path.exists(fn):
        return (os.stat(fn).st_mode & stat.S_IREAD) or not os.access(fn, os.W_OK)

    return False


def set_write_bit(fn):
    if isinstance(fn, str) and not os.path.exists(fn):
        return
    os.chmod(fn, stat.S_IWRITE | stat.S_IWUSR | stat.S_IRUSR)
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
                warnings.warn(default_warning_message.format(path), ResourceWarning)
                return

    if exc_exception.errno in [errno.EACCES, errno.EPERM]:
        warnings.warn(default_warning_message.format(path), ResourceWarning)
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
    return env_to_bool(os.getenv(name, False))  # noqa: PLW1508


def project_python(project, system=False):
    if not system:
        python = project._which("python")
    else:
        interpreters = [system_which(p) for p in ("python3", "python")]
        interpreters = [i for i in interpreters if i]  # filter out not found interpreters
        python = interpreters[0] if interpreters else None
    if not python:
        click.secho("The Python interpreter can't be found.", fg="red", err=True)
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
            click.echo(
                "{}: the {} system utility is required for Pipenv to find Python installations properly."
                "\n  Please install it.".format(
                    click.style("Warning", fg="red", bold=True),
                    click.style(_which, fg="yellow"),
                ),
                err=True,
            )
        if c.returncode == 0:
            result = next(iter(c.stdout.splitlines()), None)
    return result


def shorten_path(location, bold=False):
    """Returns a visually shorter representation of a given system path."""
    original = location
    short = os.sep.join(
        [s[0] if len(s) > (len("2long4")) else s for s in location.split(os.sep)]
    )
    short = short.split(os.sep)
    short[-1] = original.split(os.sep)[-1]
    if bold:
        short[-1] = str(click.style(short[-1], bold=True))
    return os.sep.join(short)


def isatty(stream):
    try:
        is_a_tty = stream.isatty()
    except Exception:  # pragma: no cover
        is_a_tty = False
    return is_a_tty
