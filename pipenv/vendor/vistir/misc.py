# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import json
import logging
import locale
import os
import subprocess
import sys

from collections import OrderedDict
from functools import partial
from itertools import islice

import six

from .cmdparse import Script
from .compat import Path, fs_str, partialmethod, to_native_string
from .contextmanagers import spinner as spinner

if os.name != "nt":
    class WindowsError(OSError):
        pass


__all__ = [
    "shell_escape",
    "unnest",
    "dedup",
    "run",
    "load_path",
    "partialclass",
    "to_text",
    "to_bytes",
    "locale_encoding",
    "chunked",
    "take",
    "divide"
]


def _get_logger(name=None, level="ERROR"):
    if not name:
        name = __name__
    if isinstance(level, six.string_types):
        level = getattr(logging, level.upper())
    logger = logging.getLogger(name)
    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s"
    )
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def shell_escape(cmd):
    """Escape strings for use in :func:`~subprocess.Popen` and :func:`run`.

    This is a passthrough method for instantiating a :class:`~vistir.cmdparse.Script`
    object which can be used to escape commands to output as a single string.
    """
    cmd = Script.parse(cmd)
    return cmd.cmdify()


def unnest(elem):
    """Flatten an arbitrarily nested iterable

    :param elem: An iterable to flatten
    :type elem: :class:`~collections.Iterable`

    >>> nested_iterable = (1234, (3456, 4398345, (234234)), (2396, (23895750, 9283798, 29384, (289375983275, 293759, 2347, (2098, 7987, 27599)))))
    >>> list(vistir.misc.unnest(nested_iterable))
    [1234, 3456, 4398345, 234234, 2396, 23895750, 9283798, 29384, 289375983275, 293759, 2347, 2098, 7987, 27599]
    """

    if _is_iterable(elem):
        for item in elem:
            if _is_iterable(item):
                for sub_item in unnest(item):
                    yield sub_item
            else:
                yield item
    else:
        raise ValueError("Expecting an iterable, got %r" % elem)


def _is_iterable(elem):
    if getattr(elem, "__iter__", False):
        return True
    return False


def dedup(iterable):
    """Deduplicate an iterable object like iter(set(iterable)) but
    order-reserved.
    """
    return iter(OrderedDict.fromkeys(iterable))


def _spawn_subprocess(script, env=None, block=True, cwd=None, combine_stderr=True):
    from distutils.spawn import find_executable

    if not env:
        env = {}
    command = find_executable(script.command)
    options = {
        "env": env,
        "universal_newlines": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE if not combine_stderr else subprocess.STDOUT,
        "shell": False,
    }
    if not block:
        options["stdin"] = subprocess.PIPE
    if cwd:
        options["cwd"] = cwd
    # Command not found, maybe this is a shell built-in?
    cmd = [command] + script.args
    if not command:  # Try to use CreateProcess directly if possible.
        cmd = script.cmdify()
        options["shell"] = True

    # Try to use CreateProcess directly if possible. Specifically catch
    # Windows error 193 "Command is not a valid Win32 application" to handle
    # a "command" that is non-executable. See pypa/pipenv#2727.
    try:
        return subprocess.Popen(cmd, **options)
    except WindowsError as e:
        if getattr(e, "winerror", 9999) != 193:
            raise
    options["shell"] = True
    # Try shell mode to use Windows's file association for file launch.
    return subprocess.Popen(script.cmdify(), **options)


def _create_subprocess(
    cmd,
    env=None,
    block=True,
    return_object=False,
    cwd=os.curdir,
    verbose=False,
    spinner=None,
    combine_stderr=False,
    display_limit=200,
    start_text=""
):
    if not env:
        env = {}
    try:
        c = _spawn_subprocess(cmd, env=env, block=block, cwd=cwd,
                                                    combine_stderr=combine_stderr)
    except Exception as exc:
        print("Error %s while executing command %s", exc, " ".join(cmd._parts))
        raise
    if not block:
        c.stdin.close()
        output = []
        err = []
        spinner_orig_text = None
        if spinner:
            spinner_orig_text = getattr(spinner, "text", None)
        if spinner_orig_text is None:
            spinner_orig_text = start_text if start_text is not None else ""
        streams = {
            "stdout": c.stdout,
            "stderr": c.stderr
        }
        while True:
            stdout_line = None
            stderr_line = None
            for outstream in streams.keys():
                stream = streams[outstream]
                if not stream:
                    continue
                line = to_text(stream.readline())
                if not line:
                    continue
                line = to_text("{0}".format(line.rstrip()))
                if outstream == "stderr":
                    stderr_line = line
                else:
                    stdout_line = line
            if not (stdout_line or stderr_line):
                break
            if stderr_line is not None:
                err.append(stderr_line)
                err_line = fs_str("{0}".format(stderr_line))
                if verbose and err_line is not None:
                    if spinner:
                        spinner._hide_cursor()
                        spinner.write_err(err_line)
                        spinner._show_cursor()
                    else:
                        sys.stderr.write(err_line)
                        sys.stderr.flush()
            if stdout_line is not None:
                output.append(stdout_line)
                display_line = fs_str("{0}".format(stdout_line))
                if len(stdout_line) > display_limit:
                    display_line = "{0}...".format(stdout_line[:display_limit])
                if verbose and display_line is not None:
                    if spinner:
                        spinner._hide_cursor()
                        spinner.write_err(display_line)
                        spinner._show_cursor()
                    else:
                        sys.stderr.write(display_line)
                        sys.stderr.flush()
                if spinner:
                    spinner.text = to_native_string("{0} {1}".format(spinner_orig_text, display_line))
                continue
        try:
            c.wait()
        finally:
            if c.stdout:
                c.stdout.close()
            if c.stderr:
                c.stderr.close()
        if spinner:
            if c.returncode > 0:
                spinner.fail(to_native_string("Failed...cleaning up..."))
            if not os.name == "nt":
                spinner.ok(to_native_string("✔ Complete"))
            else:
                spinner.ok(to_native_string("Complete"))
        c.out = "\n".join(output) if output else ""
        c.err = "\n".join(err) if err else ""
    else:
        c.out, c.err = c.communicate()
    if not block:
        c.wait()
    c.out = to_text("{0}".format(c.out)) if c.out else fs_str("")
    c.err = to_text("{0}".format(c.err)) if c.err else fs_str("")
    if not return_object:
        return c.out.strip(), c.err.strip()
    return c


def run(
    cmd,
    env=None,
    return_object=False,
    block=True,
    cwd=None,
    verbose=False,
    nospin=False,
    spinner_name=None,
    combine_stderr=True,
    display_limit=200
):
    """Use `subprocess.Popen` to get the output of a command and decode it.

    :param list cmd: A list representing the command you want to run.
    :param dict env: Additional environment settings to pass through to the subprocess.
    :param bool return_object: When True, returns the whole subprocess instance
    :param bool block: When False, returns a potentially still-running :class:`subprocess.Popen` instance
    :param str cwd: Current working directory contect to use for spawning the subprocess.
    :param bool verbose: Whether to print stdout in real time when non-blocking.
    :param bool nospin: Whether to disable the cli spinner.
    :param str spinner_name: The name of the spinner to use if enabled, defaults to bouncingBar
    :param bool combine_stderr: Optionally merge stdout and stderr in the subprocess, false if nonblocking.
    :param int dispay_limit: The max width of output lines to display when using a spinner.
    :returns: A 2-tuple of (output, error) or a :class:`subprocess.Popen` object.

    .. Warning:: Merging standard out and standarad error in a nonblocking subprocess
        can cause errors in some cases and may not be ideal. Consider disabling
        this functionality.
    """

    _env = os.environ.copy()
    if env:
        _env.update(env)
    env = _env
    if six.PY2:
        fs_encode = partial(to_bytes, encoding=locale_encoding)
        _env = {fs_encode(k): fs_encode(v) for k, v in os.environ.items()}
        for key, val in env.items():
            _env[fs_encode(key)] = fs_encode(val)
    else:
        _env = {k: fs_str(v) for k, v in os.environ.items()}
    if not spinner_name:
        spinner_name = "bouncingBar"
    if six.PY2:
        if isinstance(cmd, six.string_types):
            cmd = cmd.encode("utf-8")
        elif isinstance(cmd, (list, tuple)):
            cmd = [c.encode("utf-8") for c in cmd]
    if not isinstance(cmd, Script):
        cmd = Script.parse(cmd)
    if block or not return_object:
        combine_stderr = False
    start_text = ""
    with spinner(spinner_name=spinner_name, start_text=start_text, nospin=nospin) as sp:
        return _create_subprocess(
            cmd,
            env=_env,
            return_object=return_object,
            block=block,
            cwd=cwd,
            verbose=verbose,
            spinner=sp,
            combine_stderr=combine_stderr,
            start_text=start_text
        )


def load_path(python):
    """Load the :mod:`sys.path` from the given python executable's environment as json

    :param str python: Path to a valid python executable
    :return: A python representation of the `sys.path` value of the given python executable.
    :rtype: list

    >>> load_path("/home/user/.virtualenvs/requirementslib-5MhGuG3C/bin/python")
    ['', '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python37.zip', '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python3.7', '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python3.7/lib-dynload', '/home/user/.pyenv/versions/3.7.0/lib/python3.7', '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python3.7/site-packages', '/home/user/git/requirementslib/src']
    """

    python = Path(python).as_posix()
    out, err = run([python, "-c", "import json, sys; print(json.dumps(sys.path))"],
                        nospin=True)
    if out:
        return json.loads(out)
    else:
        return []


def partialclass(cls, *args, **kwargs):
    """Returns a partially instantiated class

    :return: A partial class instance
    :rtype: cls

    >>> source = partialclass(Source, url="https://pypi.org/simple")
    >>> source
    <class '__main__.Source'>
    >>> source(name="pypi")
    >>> source.__dict__
    mappingproxy({'__module__': '__main__', '__dict__': <attribute '__dict__' of 'Source' objects>, '__weakref__': <attribute '__weakref__' of 'Source' objects>, '__doc__': None, '__init__': functools.partialmethod(<function Source.__init__ at 0x7f23af429bf8>, , url='https://pypi.org/simple')})
    >>> new_source = source(name="pypi")
    >>> new_source
    <__main__.Source object at 0x7f23af189b38>
    >>> new_source.__dict__
    {'url': 'https://pypi.org/simple', 'verify_ssl': True, 'name': 'pypi'}
    """

    name_attrs = [
        n
        for n in (getattr(cls, name, str(cls)) for name in ("__name__", "__qualname__"))
        if n is not None
    ]
    name_attrs = name_attrs[0]
    type_ = type(
        name_attrs, (cls,), {"__init__": partialmethod(cls.__init__, *args, **kwargs)}
    )
    # Swiped from attrs.make_class
    try:
        type_.__module__ = sys._getframe(1).f_globals.get("__name__", "__main__")
    except (AttributeError, ValueError):
        pass
    return type_


# Borrowed from django -- force bytes and decode -- see link for details:
# https://github.com/django/django/blob/fc6b90b/django/utils/encoding.py#L112
def to_bytes(string, encoding="utf-8", errors="ignore"):
    """Force a value to bytes.

    :param string: Some input that can be converted to a bytes.
    :type string: str or bytes unicode or a memoryview subclass
    :param encoding: The encoding to use for conversions, defaults to "utf-8"
    :param encoding: str, optional
    :return: Corresponding byte representation (for use in filesystem operations)
    :rtype: bytes
    """

    if not errors:
        if encoding.lower() == "utf-8":
            errors = "surrogateescape" if six.PY3 else "ignore"
        else:
            errors = "strict"
    if isinstance(string, bytes):
        if encoding.lower() == "utf-8":
            return string
        else:
            return string.decode("utf-8").encode(encoding, errors)
    elif isinstance(string, memoryview):
        return bytes(string)
    elif not isinstance(string, six.string_types):
        try:
            if six.PY3:
                return six.text_type(string).encode(encoding, errors)
            else:
                return bytes(string)
        except UnicodeEncodeError:
            if isinstance(string, Exception):
                return b" ".join(to_bytes(arg, encoding, errors) for arg in string)
            return six.text_type(string).encode(encoding, errors)
    else:
        return string.encode(encoding, errors)


def to_text(string, encoding="utf-8", errors=None):
    """Force a value to a text-type.

    :param string: Some input that can be converted to a unicode representation.
    :type string: str or bytes unicode
    :param encoding: The encoding to use for conversions, defaults to "utf-8"
    :param encoding: str, optional
    :return: The unicode representation of the string
    :rtype: str
    """

    if not errors:
        if encoding.lower() == "utf-8":
            errors = "surrogateescape" if six.PY3 else "ignore"
        else:
            errors = "strict"
    if issubclass(type(string), six.text_type):
        return string
    try:
        if not issubclass(type(string), six.string_types):
            if six.PY3:
                if isinstance(string, bytes):
                    string = six.text_type(string, encoding, errors)
                else:
                    string = six.text_type(string)
            elif hasattr(string, "__unicode__"):
                string = six.text_type(string)
            else:
                string = six.text_type(bytes(string), encoding, errors)
        else:
            string = string.decode(encoding, errors)
    except UnicodeDecodeError as e:
        string = " ".join(to_text(arg, encoding, errors) for arg in string)
    return string


def divide(n, iterable):
    """
    split an iterable into n groups, per https://more-itertools.readthedocs.io/en/latest/api.html#grouping

    :param int n: Number of unique groups
    :param iter iterable: An iterable to split up
    :return: a list of new iterables derived from the original iterable
    :rtype: list
    """

    seq = tuple(iterable)
    q, r = divmod(len(seq), n)

    ret = []
    for i in range(n):
        start = (i * q) + (i if i < r else r)
        stop = ((i + 1) * q) + (i + 1 if i + 1 < r else r)
        ret.append(iter(seq[start:stop]))

    return ret


def take(n, iterable):
    """Take n elements from the supplied iterable without consuming it.

    :param int n: Number of unique groups
    :param iter iterable: An iterable to split up

    from https://github.com/erikrose/more-itertools/blob/master/more_itertools/recipes.py
    """

    return list(islice(iterable, n))


def chunked(n, iterable):
    """Split an iterable into lists of length *n*.

    :param int n: Number of unique groups
    :param iter iterable: An iterable to split up

    from https://github.com/erikrose/more-itertools/blob/master/more_itertools/more.py
    """

    return iter(partial(take, n, iter(iterable)), [])


try:
    locale_encoding = locale.getdefaultencoding()[1] or "ascii"
except Exception:
    locale_encoding = "ascii"


def getpreferredencoding():
    import locale
    # Borrowed from Invoke
    # (see https://github.com/pyinvoke/invoke/blob/93af29d/invoke/runners.py#L881)
    _encoding = locale.getpreferredencoding(False)
    if six.PY2 and not sys.platform == "win32":
        _default_encoding = locale.getdefaultlocale()[1]
        if _default_encoding is not None:
            _encoding = _default_encoding
    return _encoding


PREFERRED_ENCODING = getpreferredencoding()


def decode_for_output(output):
    """Given a string, decode it for output to a terminal

    :param str output: A string to print to a terminal
    :return: A re-encoded string using the preferred encoding
    :rtype: str
    """

    if not isinstance(output, six.string_types):
        return output
    try:
        output = output.encode(PREFERRED_ENCODING)
    except AttributeError:
        pass
    output = output.decode(PREFERRED_ENCODING)
    return output
