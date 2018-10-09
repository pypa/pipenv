# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import json
import locale
import os
import subprocess
import sys

from collections import OrderedDict
from contextlib import contextmanager
from functools import partial

import six

from .cmdparse import Script
from .compat import Path, fs_str, partialmethod


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
]


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


def _spawn_subprocess(script, env={}, block=True, cwd=None):
    from distutils.spawn import find_executable

    command = find_executable(script.command)
    options = {
        "env": env,
        "universal_newlines": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE if block else subprocess.STDOUT,
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
        if e.winerror != 193:
            raise
    options["shell"] = True
    # Try shell mode to use Windows's file association for file launch.
    return subprocess.Popen(script.cmdify(), **options)


def _create_subprocess(
    cmd,
    env={},
    block=True,
    return_object=False,
    cwd=os.curdir,
    verbose=False,
    spinner=None,
):
    try:
        c = _spawn_subprocess(cmd, env=env, block=block, cwd=cwd)
    except Exception as exc:
        print("Error %s while executing command %s", exc, " ".join(cmd._parts))
        raise
    if not block:
        c.stdin.close()
        output = []
        spinner_orig_text = ""
        if spinner:
            spinner_orig_text = spinner.text
        if c.stdout is not None:
            while True:
                line = to_text(c.stdout.readline())
                if not line:
                    break
                line = line.rstrip()
                output.append(line)
                display_line = line
                if len(line) > 200:
                    display_line = "{0}...".format(line[:200])
                if verbose:
                    spinner.write(display_line)
                else:
                    spinner.text = "{0} {1}".format(spinner_orig_text, display_line)
                    continue
        try:
            c.wait()
        finally:
            if c.stdout:
                c.stdout.close()
        if spinner:
            spinner.text = "Complete!"
            spinner.ok("✔")
        c.out = "".join(output)
        c.err = ""
    else:
        c.out, c.err = c.communicate()
    if not return_object:
        return c.out.strip(), c.err.strip()
    return c


def run(
    cmd,
    env={},
    return_object=False,
    block=True,
    cwd=None,
    verbose=False,
    nospin=False,
):
    """Use `subprocess.Popen` to get the output of a command and decode it.

    :param list cmd: A list representing the command you want to run.
    :param dict env: Additional environment settings to pass through to the subprocess.
    :param bool return_object: When True, returns the whole subprocess instance
    :param bool block: When False, returns a potentially still-running :class:`subprocess.Popen` instance
    :param str cwd: Current working directory contect to use for spawning the subprocess.
    :param bool verbose: Whether to print stdout in real time when non-blocking.
    :param bool nospin: Whether to disable the cli spinner.
    :returns: A 2-tuple of (output, error) or a :class:`subprocess.Popen` object.
    """
    if six.PY2:
        fs_encode = partial(to_bytes, encoding=locale_encoding)
        _env = {fs_encode(k): fs_encode(v) for k, v in os.environ.items()}
        for key, val in env.items():
            _env[fs_encode(key)] = fs_encode(val)
    else:
        _env = {k: fs_str(v) for k, v in os.environ.items()}
    if six.PY2:
        if isinstance(cmd, six.string_types):
            cmd = cmd.encode("utf-8")
        elif isinstance(cmd, (list, tuple)):
            cmd = [c.encode("utf-8") for c in cmd]
    if not isinstance(cmd, Script):
        cmd = Script.parse(cmd)
    if nospin is False:
        try:
            from yaspin import yaspin
            from yaspin import spinners
        except ImportError:
            raise RuntimeError(
                "Failed to import spinner! Reinstall vistir with command:"
                " pip install --upgrade vistir[spinner]"
            )
        else:
            spinner = yaspin
            animation = spinners.Spinners.bouncingBar
    else:

        @contextmanager
        def spinner(spin_type, text):
            class FakeClass(object):
                def __init__(self, text=""):
                    self.text = text

                def ok(self, text):
                    return

                def write(self, text):
                    print(text)

            myobj = FakeClass(text)
            yield myobj

        animation = None
    with spinner(animation, text="Running...") as sp:
        return _create_subprocess(
            cmd,
            env=_env,
            return_object=return_object,
            block=block,
            cwd=cwd,
            verbose=verbose,
            spinner=sp,
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
    out, err = run([python, "-c", "import json, sys; print(json.dumps(sys.path))"])
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


try:
    locale_encoding = locale.getdefaultencoding()[1] or "ascii"
except Exception:
    locale_encoding = "ascii"
