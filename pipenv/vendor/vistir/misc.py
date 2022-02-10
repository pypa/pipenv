# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import atexit
import io
import itertools
import json
import locale
import logging
import os
import subprocess
import sys
import threading
from collections import OrderedDict
from functools import partial
from itertools import islice, tee
from weakref import WeakKeyDictionary

import pipenv.vendor.six as six
from pipenv.vendor.six.moves.queue import Empty, Queue

from .cmdparse import Script
from .compat import (
    Iterable,
    Path,
    StringIO,
    TimeoutError,
    _fs_decode_errors,
    _fs_encode_errors,
    fs_str,
    is_bytes,
    partialmethod,
    to_native_string,
)
from .contextmanagers import spinner as spinner
from .environment import MYPY_RUNNING
from .termcolors import ANSI_REMOVAL_RE, colorize

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
    "divide",
    "getpreferredencoding",
    "decode_for_output",
    "get_canonical_encoding_name",
    "get_wrapped_stream",
    "StreamWrapper",
]


if MYPY_RUNNING:
    from typing import Any, Dict, Generator, IO, List, Optional, Text, Tuple, Union
    from .spin import VistirSpinner


def _get_logger(name=None, level="ERROR"):
    # type: (Optional[str], str) -> logging.Logger
    if not name:
        name = __name__
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
    # type: (Union[str, List[str]]) -> str
    """Escape strings for use in :func:`~subprocess.Popen` and :func:`run`.

    This is a passthrough method for instantiating a
    :class:`~vistir.cmdparse.Script` object which can be used to escape
    commands to output as a single string.
    """
    cmd = Script.parse(cmd)
    return cmd.cmdify()


def unnest(elem):
    # type: (Iterable) -> Any
    """Flatten an arbitrarily nested iterable.

    :param elem: An iterable to flatten
    :type elem: :class:`~collections.Iterable`

    >>> nested_iterable = (
            1234, (3456, 4398345, (234234)), (
                2396, (
                    23895750, 9283798, 29384, (
                        289375983275, 293759, 2347, (
                            2098, 7987, 27599
                        )
                    )
                )
            )
        )
    >>> list(vistir.misc.unnest(nested_iterable))
    [1234, 3456, 4398345, 234234, 2396, 23895750, 9283798, 29384, 289375983275, 293759,
     2347, 2098, 7987, 27599]
    """

    if isinstance(elem, Iterable) and not isinstance(elem, six.string_types):
        elem, target = tee(elem, 2)
    else:
        target = elem
    if not target or not _is_iterable(target):
        yield target
    else:
        for el in target:
            if isinstance(el, Iterable) and not isinstance(el, six.string_types):
                el, el_copy = tee(el, 2)
                for sub in unnest(el_copy):
                    yield sub
            else:
                yield el


def _is_iterable(elem):
    # type: (Any) -> bool
    if getattr(elem, "__iter__", False) or isinstance(elem, Iterable):
        return True
    return False


def dedup(iterable):
    # type: (Iterable) -> Iterable
    """Deduplicate an iterable object like iter(set(iterable)) but order-
    preserved."""
    return iter(OrderedDict.fromkeys(iterable))


def _spawn_subprocess(
    script,  # type: Union[str, List[str]]
    env=None,  # type: Optional[Dict[str, str]]
    block=True,  # type: bool
    cwd=None,  # type: Optional[Union[str, Path]]
    combine_stderr=True,  # type: bool
):
    # type: (...) -> subprocess.Popen
    from distutils.spawn import find_executable

    if not env:
        env = os.environ.copy()
    command = find_executable(script.command)
    options = {
        "env": env,
        "universal_newlines": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE if not combine_stderr else subprocess.STDOUT,
        "shell": False,
    }
    if sys.version_info[:2] > (3, 5):
        options.update({"universal_newlines": True, "encoding": "utf-8"})
    elif os.name != "nt":
        options["universal_newlines"] = True
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
    except WindowsError as e:  # pragma: no cover
        if getattr(e, "winerror", 9999) != 193:
            raise
    options["shell"] = True
    # Try shell mode to use Windows's file association for file launch.
    return subprocess.Popen(script.cmdify(), **options)


class SubprocessStreamWrapper(object):
    def __init__(
        self,
        display_stderr_maxlen=200,  # type: int
        display_line_for_loops=20,  # type: int
        subprocess=None,  # type: subprocess.Popen
        spinner=None,  # type: Optional[VistirSpinner]
        verbose=False,  # type: bool
        stdout_allowed=False,  # type: bool
    ):
        # type: (...) -> None
        stdout_encoding = None
        stderr_encoding = None
        preferred_encoding = getpreferredencoding()
        if subprocess is not None:
            stdout_encoding = self.get_subprocess_encoding(subprocess, "stdout")
            stderr_encoding = self.get_subprocess_encoding(subprocess, "stderr")
        self.stdout_encoding = stdout_encoding or preferred_encoding
        self.stderr_encoding = stderr_encoding or preferred_encoding
        self.stdout_lines = []
        self.text_stdout_lines = []
        self.stderr_lines = []
        self.text_stderr_lines = []
        self.display_line = ""
        self.display_line_loops_displayed = 0
        self.display_line_shown_for_loops = display_line_for_loops
        self.display_line_max_len = display_stderr_maxlen
        self.spinner = spinner
        self.stdout_allowed = stdout_allowed
        self.verbose = verbose
        self._iterated_stdout = None
        self._iterated_stderr = None
        self._subprocess = subprocess
        self._queues = {
            "streams": Queue(),
            "lines": Queue(),
        }
        self._threads = {
            stream_name: threading.Thread(
                target=self.enqueue_stream,
                args=(self._subprocess, stream_name, self._queues["streams"]),
            )
            for stream_name in ("stdout", "stderr")
        }
        self._threads["watcher"] = threading.Thread(
            target=self.process_output_lines,
            args=(self._queues["streams"], self._queues["lines"]),
        )
        self.start_threads()

    def enqueue_stream(self, proc, stream_name, queue):
        # type: (subprocess.Popen, str, Queue) -> None
        if not getattr(proc, stream_name, None):
            queue.put(("stderr", None))
        else:
            for line in iter(getattr(proc, stream_name).readline, ""):
                queue.put((stream_name, line))
            getattr(proc, stream_name).close()

    @property
    def stderr(self):
        return self._subprocess.stderr

    @property
    def stdout(self):
        return self._subprocess.stdout

    @classmethod
    def get_subprocess_encoding(cls, cmd_instance, stream_name):
        # type: (subprocess.Popen, str) -> Optional[str]
        stream = getattr(cmd_instance, stream_name, None)
        if stream is not None:
            return get_output_encoding(getattr(stream, "encoding", None))
        return None

    @property
    def stdout_iter(self):
        if self._iterated_stdout is None and self.stdout:
            self._iterated_stdout = iter(self.stdout.readline, "")
        return self._iterated_stdout

    @property
    def stderr_iter(self):
        if self._iterated_stderr is None and self.stderr:
            self._iterated_stderr = iter(self.stderr.readline, "")
        return self._iterated_stderr

    def _decode_line(self, line, encoding):
        # type: (Union[str, bytes], str) -> str
        if isinstance(line, six.binary_type):
            line = to_text(
                line.decode(encoding, errors=_fs_decode_errors).encode(
                    "utf-8", errors=_fs_encode_errors
                ),
                errors="backslashreplace",
            )
        else:
            line = to_text(line, encoding=encoding, errors=_fs_encode_errors)
        return line

    def start_threads(self):
        for thread in self._threads.values():
            thread.daemon = True
            thread.start()

    @property
    def subprocess(self):
        return self._subprocess

    @property
    def out(self):
        # type: () -> str
        return getattr(self.subprocess, "out", "")

    @out.setter
    def out(self, value):
        # type: (str) -> None
        self._subprocess.out = value

    @property
    def err(self):
        # type: () -> str
        return getattr(self.subprocess, "err", "")

    @err.setter
    def err(self, value):
        # type: (str) -> None
        self._subprocess.err = value

    def poll(self):
        # type: () -> Optional[int]
        return self.subprocess.poll()

    def wait(self, timeout=None):
        # type: (self, Optional[int]) -> Optional[int]
        kwargs = {}
        if sys.version_info[0] >= 3:
            kwargs = {"timeout": timeout}
        result = self._subprocess.wait(**kwargs)
        self.gather_output()
        return result

    @property
    def returncode(self):
        # type: () -> Optional[int]
        return self.subprocess.returncode

    @property
    def text_stdout(self):
        return os.linesep.join(self.text_stdout_lines)

    @property
    def text_stderr(self):
        return os.linesep.join(self.text_stderr_lines)

    @property
    def stderr_closed(self):
        # type: () -> bool
        return self.stderr is None or (self.stderr is not None and self.stderr.closed)

    @property
    def stdout_closed(self):
        # type: () -> bool
        return self.stdout is None or (self.stdout is not None and self.stdout.closed)

    @property
    def running(self):
        # type: () -> bool
        return any(t.is_alive() for t in self._threads.values()) or not all(
            [self.stderr_closed, self.stdout_closed, self.subprocess_finished]
        )

    @property
    def subprocess_finished(self):
        if self._subprocess is None:
            return False
        return (
            self._subprocess.poll() is not None or self._subprocess.returncode is not None
        )

    def update_display_line(self, new_line):
        # type: () -> None
        if self.display_line:
            if new_line != self.display_line:
                self.display_line_loops_displayed = 0
                new_line = fs_str("{}".format(new_line))
                if len(new_line) > self.display_line_max_len:
                    new_line = "{}...".format(new_line[: self.display_line_max_len])
                self.display_line = new_line
            elif self.display_line_loops_displayed >= self.display_line_shown_for_loops:
                self.display_line = ""
                self.display_line_loops_displayed = 0
            else:
                self.display_line_loops_displayed += 1
        return None

    @classmethod
    def check_line_content(cls, line):
        # type: (Optional[str]) -> bool
        return line is not None and line != ""

    def get_line(self, queue):
        # type: (Queue) -> Tuple[Optional[str], ...]
        stream, result = None, None
        try:
            stream, result = queue.get_nowait()
        except Empty:
            result = None
        return stream, result

    def process_output_lines(self, recv_queue, line_queue):
        # type: (Queue, Queue) -> None
        stream, line = self.get_line(recv_queue)
        while self.poll() is None or line is not None:
            if self.check_line_content(line):
                line = to_text("{}".format(line).rstrip())
                line_queue.put((stream, line))
            stream, line = self.get_line(recv_queue)

    def gather_output(self, spinner=None, stdout_allowed=False, verbose=False):
        # type: (Optional[VistirSpinner], bool, bool) -> None
        if not getattr(self._subprocess, "out", None):
            self._subprocess.out = ""
        if not getattr(self._subprocess, "err", None):
            self._subprocess.err = ""
        if not self._queues["streams"].empty():
            self.process_output_lines(self._queues["streams"], self._queues["lines"])
        while not self._queues["lines"].empty():
            try:
                stream_name, line = self._queues["lines"].get()
            except Empty:
                if not self._threads["watcher"].is_active():
                    break
                pass
            if stream_name == "stdout":
                text_line = self._decode_line(line, self.stdout_encoding)
                self.text_stdout_lines.append(text_line)
                self.out += "{}\n".format(text_line)
                if verbose:
                    _write_subprocess_result(
                        line, "stdout", spinner=spinner, stdout_allowed=stdout_allowed
                    )
            else:
                text_err = self._decode_line(line, self.stderr_encoding)
                self.text_stderr_lines.append(text_err)
                self.update_display_line(line)
                self.err += "{}\n".format(text_err)
                _write_subprocess_result(
                    line, "stderr", spinner=spinner, stdout_allowed=stdout_allowed
                )
            if spinner:
                spinner.text = to_native_string(
                    "{} {}".format(spinner.text, self.display_line)
                )
        self.out = self.out.strip()
        self.err = self.err.strip()


def _write_subprocess_result(result, stream_name, spinner=None, stdout_allowed=False):
    # type: (str, str, Optional[VistirSpinner], bool) -> None
    if not stdout_allowed and stream_name == "stdout":
        stream_name = "stderr"
    if spinner:
        spinner.hide_and_write(result, target=getattr(spinner, stream_name))
    else:
        target_stream = getattr(sys, stream_name)
        target_stream.write(result)
        target_stream.flush()
    return None


def attach_stream_reader(
    cmd_instance, verbose, maxlen, spinner=None, stdout_allowed=False
):
    streams = SubprocessStreamWrapper(
        subprocess=cmd_instance,
        display_stderr_maxlen=maxlen,
        spinner=spinner,
        verbose=verbose,
        stdout_allowed=stdout_allowed,
    )
    streams.gather_output(spinner=spinner, verbose=verbose, stdout_allowed=stdout_allowed)
    return streams


def _handle_nonblocking_subprocess(c, spinner=None):
    while c.running:
        c.wait()
    if spinner:
        if c.returncode != 0:
            spinner.fail(to_native_string("Failed...cleaning up..."))
        elif c.returncode == 0 and not os.name == "nt":
            spinner.ok(to_native_string("✔ Complete"))
        else:
            spinner.ok(to_native_string("Complete"))
    return c


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
    start_text="",
    write_to_stdout=True,
):
    if not env:
        env = os.environ.copy()
    try:
        c = _spawn_subprocess(
            cmd, env=env, block=block, cwd=cwd, combine_stderr=combine_stderr
        )
    except Exception as exc:  # pragma: no cover
        import traceback

        formatted_tb = "".join(traceback.format_exception(*sys.exc_info()))
        sys.stderr.write(
            "Error while executing command %s:" % to_native_string(" ".join(cmd._parts))
        )
        sys.stderr.write(formatted_tb)
        raise exc
    if not block:
        c.stdin.close()
        spinner_orig_text = ""
        if spinner and getattr(spinner, "text", None) is not None:
            spinner_orig_text = spinner.text
        if not spinner_orig_text and start_text is not None:
            spinner_orig_text = start_text
        c = attach_stream_reader(
            c,
            verbose=verbose,
            maxlen=display_limit,
            spinner=spinner,
            stdout_allowed=write_to_stdout,
        )
        _handle_nonblocking_subprocess(c, spinner)
    else:
        try:
            c.out, c.err = c.communicate()
        except (SystemExit, KeyboardInterrupt, TimeoutError):  # pragma: no cover
            c.terminate()
            c.out, c.err = c.communicate()
            raise
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
    display_limit=200,
    write_to_stdout=True,
):
    """Use `subprocess.Popen` to get the output of a command and decode it.

    :param list cmd: A list representing the command you want to run.
    :param dict env: Additional environment settings to pass through to the subprocess.
    :param bool return_object: When True, returns the whole subprocess instance
    :param bool block: When False, returns a potentially still-running
        :class:`subprocess.Popen` instance
    :param str cwd: Current working directory contect to use for spawning the subprocess.
    :param bool verbose: Whether to print stdout in real time when non-blocking.
    :param bool nospin: Whether to disable the cli spinner.
    :param str spinner_name: The name of the spinner to use if enabled, defaults to
        bouncingBar
    :param bool combine_stderr: Optionally merge stdout and stderr in the subprocess,
        false if nonblocking.
    :param int dispay_limit: The max width of output lines to display when using a
        spinner.
    :param bool write_to_stdout: Whether to write to stdout when using a spinner,
        defaults to True.
    :returns: A 2-tuple of (output, error) or a :class:`subprocess.Popen` object.

    .. Warning:: Merging standard out and standarad error in a nonblocking subprocess
        can cause errors in some cases and may not be ideal. Consider disabling
        this functionality.
    """

    _env = os.environ.copy()
    _env["PYTHONIOENCODING"] = str("utf-8")
    _env["PYTHONUTF8"] = str("1")
    if env:
        _env.update(env)
    if six.PY2:
        _fs_encode = partial(to_bytes, encoding=locale_encoding)
        _env = {_fs_encode(k): _fs_encode(v) for k, v in _env.items()}
    else:
        _env = {k: fs_str(v) for k, v in _env.items()}
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
    with spinner(
        spinner_name=spinner_name,
        start_text=start_text,
        nospin=nospin,
        write_to_stdout=write_to_stdout,
    ) as sp:
        return _create_subprocess(
            cmd,
            env=_env,
            return_object=return_object,
            block=block,
            cwd=cwd,
            verbose=verbose,
            spinner=sp,
            combine_stderr=combine_stderr,
            start_text=start_text,
            write_to_stdout=write_to_stdout,
        )


def load_path(python):
    """Load the :mod:`sys.path` from the given python executable's environment
    as json.

    :param str python: Path to a valid python executable
    :return: A python representation of the `sys.path` value of the given python
        executable.
    :rtype: list

    >>> load_path("/home/user/.virtualenvs/requirementslib-5MhGuG3C/bin/python")
    ['', '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python37.zip',
     '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python3.7',
     '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python3.7/lib-dynload',
     '/home/user/.pyenv/versions/3.7.0/lib/python3.7',
     '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python3.7/site-packages',
     '/home/user/git/requirementslib/src']
    """

    python = Path(python).as_posix()
    out, err = run(
        [python, "-c", "import json, sys; print(json.dumps(sys.path))"], nospin=True
    )
    if out:
        return json.loads(out)
    else:
        return []


def partialclass(cls, *args, **kwargs):
    """Returns a partially instantiated class.

    :return: A partial class instance
    :rtype: cls

    >>> source = partialclass(Source, url="https://pypi.org/simple")
    >>> source
    <class '__main__.Source'>
    >>> source(name="pypi")
    >>> source.__dict__
    mappingproxy({
        '__module__': '__main__',
        '__dict__': <attribute '__dict__' of 'Source' objects>,
        '__weakref__': <attribute '__weakref__' of 'Source' objects>,
        '__doc__': None,
        '__init__': functools.partialmethod(
            <function Source.__init__ at 0x7f23af429bf8>, , url='https://pypi.org/simple'
        )
    })
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
    except (AttributeError, ValueError):  # pragma: no cover
        pass  # pragma: no cover
    return type_


# Borrowed from django -- force bytes and decode -- see link for details:
# https://github.com/django/django/blob/fc6b90b/django/utils/encoding.py#L112
def to_bytes(string, encoding="utf-8", errors=None):
    """Force a value to bytes.

    :param string: Some input that can be converted to a bytes.
    :type string: str or bytes unicode or a memoryview subclass
    :param encoding: The encoding to use for conversions, defaults to "utf-8"
    :param encoding: str, optional
    :return: Corresponding byte representation (for use in filesystem operations)
    :rtype: bytes
    """

    unicode_name = get_canonical_encoding_name("utf-8")
    if not errors:
        if get_canonical_encoding_name(encoding) == unicode_name:
            if six.PY3 and os.name == "nt":
                errors = "surrogatepass"
            else:
                errors = "surrogateescape" if six.PY3 else "ignore"
        else:
            errors = "strict"
    if isinstance(string, bytes):
        if get_canonical_encoding_name(encoding) == unicode_name:
            return string
        else:
            return string.decode(unicode_name).encode(encoding, errors)
    elif isinstance(string, memoryview):
        return string.tobytes()
    elif not isinstance(string, six.string_types):  # pragma: no cover
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

    unicode_name = get_canonical_encoding_name("utf-8")
    if not errors:
        if get_canonical_encoding_name(encoding) == unicode_name:
            if six.PY3 and os.name == "nt":
                errors = "surrogatepass"
            else:
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
            elif hasattr(string, "__unicode__"):  # pragma: no cover
                string = six.text_type(string)
            else:
                string = six.text_type(bytes(string), encoding, errors)
        else:
            string = string.decode(encoding, errors)
    except UnicodeDecodeError:  # pragma: no cover
        string = " ".join(to_text(arg, encoding, errors) for arg in string)
    return string


def divide(n, iterable):
    """split an iterable into n groups, per https://more-
    itertools.readthedocs.io/en/latest/api.html#grouping.

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
    locale_encoding = locale.getdefaultlocale()[1] or "ascii"
except Exception:
    locale_encoding = "ascii"


def getpreferredencoding():
    """Determine the proper output encoding for terminal rendering."""

    # Borrowed from Invoke
    # (see https://github.com/pyinvoke/invoke/blob/93af29d/invoke/runners.py#L881)
    _encoding = sys.getdefaultencoding() or locale.getpreferredencoding(False)
    if six.PY2 and not sys.platform == "win32":
        _default_encoding = locale.getdefaultlocale()[1]
        if _default_encoding is not None:
            _encoding = _default_encoding
    return _encoding


PREFERRED_ENCODING = getpreferredencoding()


def get_output_encoding(source_encoding):
    """Given a source encoding, determine the preferred output encoding.

    :param str source_encoding: The encoding of the source material.
    :returns: The output encoding to decode to.
    :rtype: str
    """

    if source_encoding is not None:
        if get_canonical_encoding_name(source_encoding) == "ascii":
            return "utf-8"
        return get_canonical_encoding_name(source_encoding)
    return get_canonical_encoding_name(PREFERRED_ENCODING)


def _encode(output, encoding=None, errors=None, translation_map=None):
    if encoding is None:
        encoding = PREFERRED_ENCODING
    try:
        output = output.encode(encoding)
    except (UnicodeDecodeError, UnicodeEncodeError):
        if translation_map is not None:
            if six.PY2:
                output = unicode.translate(  # noqa: F821
                    to_text(output, encoding=encoding, errors=errors), translation_map
                )
            else:
                output = output.translate(translation_map)
        else:
            output = to_text(output, encoding=encoding, errors=errors)
    except AttributeError:
        pass
    return output


def decode_for_output(output, target_stream=None, translation_map=None):
    """Given a string, decode it for output to a terminal.

    :param str output: A string to print to a terminal
    :param target_stream: A stream to write to, we will encode to target this stream if
        possible.
    :param dict translation_map: A mapping of unicode character ordinals to replacement
        strings.
    :return: A re-encoded string using the preferred encoding
    :rtype: str
    """

    if not isinstance(output, six.string_types):
        return output
    encoding = None
    if target_stream is not None:
        encoding = getattr(target_stream, "encoding", None)
    encoding = get_output_encoding(encoding)
    try:
        output = _encode(output, encoding=encoding, translation_map=translation_map)
    except (UnicodeDecodeError, UnicodeEncodeError):
        output = to_native_string(output)
        output = _encode(
            output, encoding=encoding, errors="replace", translation_map=translation_map
        )
    return to_text(output, encoding=encoding, errors="replace")


def get_canonical_encoding_name(name):
    # type: (str) -> str
    """Given an encoding name, get the canonical name from a codec lookup.

    :param str name: The name of the codec to lookup
    :return: The canonical version of the codec name
    :rtype: str
    """

    import codecs

    try:
        codec = codecs.lookup(name)
    except LookupError:
        return name
    else:
        return codec.name


def _is_binary_buffer(stream):
    try:
        stream.write(b"")
    except Exception:
        try:
            stream.write("")
        except Exception:
            pass
        return False
    return True


def _get_binary_buffer(stream):
    if six.PY3 and not _is_binary_buffer(stream):
        stream = getattr(stream, "buffer", None)
        if stream is not None and _is_binary_buffer(stream):
            return stream
    return stream


def get_wrapped_stream(stream, encoding=None, errors="replace"):
    """Given a stream, wrap it in a `StreamWrapper` instance and return the
    wrapped stream.

    :param stream: A stream instance to wrap
    :param str encoding: The encoding to use for the stream
    :param str errors: The error handler to use, default "replace"
    :returns: A new, wrapped stream
    :rtype: :class:`StreamWrapper`
    """

    if stream is None:
        raise TypeError("must provide a stream to wrap")
    stream = _get_binary_buffer(stream)
    if stream is not None and encoding is None:
        encoding = "utf-8"
    if not encoding:
        encoding = get_output_encoding(getattr(stream, "encoding", None))
    else:
        encoding = get_canonical_encoding_name(encoding)
    return StreamWrapper(stream, encoding, errors, line_buffering=True)


class StreamWrapper(io.TextIOWrapper):

    """This wrapper class will wrap a provided stream and supply an interface
    for compatibility."""

    def __init__(self, stream, encoding, errors, line_buffering=True, **kwargs):
        self._stream = stream = _StreamProvider(stream)
        io.TextIOWrapper.__init__(
            self, stream, encoding, errors, line_buffering=line_buffering, **kwargs
        )

    # borrowed from click's implementation of stream wrappers, see
    # https://github.com/pallets/click/blob/6cafd32/click/_compat.py#L64
    if six.PY2:

        def write(self, x):
            if isinstance(x, (str, buffer, bytearray)):  # noqa: F821
                try:
                    self.flush()
                except Exception:
                    pass
                # This is modified from the initial implementation to rely on
                # our own decoding functionality to preserve unicode strings where
                # possible
                return self.buffer.write(str(x))
            return io.TextIOWrapper.write(self, x)

    else:

        def write(self, x):
            # try to use backslash and surrogate escape strategies before failing
            self._errors = (
                "backslashescape" if self.encoding != "mbcs" else "surrogateescape"
            )
            try:
                return io.TextIOWrapper.write(self, to_text(x, errors=self._errors))
            except UnicodeDecodeError:
                if self._errors != "surrogateescape":
                    self._errors = "surrogateescape"
                else:
                    self._errors = "replace"
                return io.TextIOWrapper.write(self, to_text(x, errors=self._errors))

        def writelines(self, lines):
            for line in lines:
                self.write(line)

    def __del__(self):
        try:
            self.detach()
        except Exception:
            pass

    def isatty(self):
        return self._stream.isatty()


# More things borrowed from click, this is because we are using `TextIOWrapper` instead of
# just a normal StringIO
class _StreamProvider(object):
    def __init__(self, stream):
        self._stream = stream
        super(_StreamProvider, self).__init__()

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def read1(self, size):
        fn = getattr(self._stream, "read1", None)
        if fn is not None:
            return fn(size)
        if six.PY2:
            return self._stream.readline(size)
        return self._stream.read(size)

    def readable(self):
        fn = getattr(self._stream, "readable", None)
        if fn is not None:
            return fn()
        try:
            self._stream.read(0)
        except Exception:
            return False
        return True

    def writable(self):
        fn = getattr(self._stream, "writable", None)
        if fn is not None:
            return fn()
        try:
            self._stream.write(b"")
        except Exception:
            return False
        return True

    def seekable(self):
        fn = getattr(self._stream, "seekable", None)
        if fn is not None:
            return fn()
        try:
            self._stream.seek(self._stream.tell())
        except Exception:
            return False
        return True


# XXX: The approach here is inspired somewhat by click with details taken from various
# XXX: other sources. Specifically we are using a stream cache and stream wrapping
# XXX: techniques from click (loosely inspired for the most part, with many details)
# XXX: heavily modified to suit our needs


def _isatty(stream):
    try:
        is_a_tty = stream.isatty()
    except Exception:  # pragma: no cover
        is_a_tty = False
    return is_a_tty


_wrap_for_color = None

try:
    import pipenv.vendor.colorama as colorama
except ImportError:
    colorama = None

_color_stream_cache = WeakKeyDictionary()

if os.name == "nt" or sys.platform.startswith("win"):

    if colorama is not None:

        def _is_wrapped_for_color(stream):
            return isinstance(
                stream, (colorama.AnsiToWin32, colorama.ansitowin32.StreamWrapper)
            )

        def _wrap_for_color(stream, color=None):
            try:
                cached = _color_stream_cache.get(stream)
            except KeyError:
                cached = None
            if cached is not None:
                return cached
            strip = not _can_use_color(stream, color)
            _color_wrapper = colorama.AnsiToWin32(stream, strip=strip)
            result = _color_wrapper.stream
            _write = result.write

            def _write_with_color(s):
                try:
                    return _write(s)
                except Exception:
                    _color_wrapper.reset_all()
                    raise

            result.write = _write_with_color
            try:
                _color_stream_cache[stream] = result
            except Exception:
                pass
            return result


def _cached_stream_lookup(stream_lookup_func, stream_resolution_func):
    stream_cache = WeakKeyDictionary()

    def lookup():
        stream = stream_lookup_func()
        result = None
        if stream in stream_cache:
            result = stream_cache.get(stream, None)
        if result is not None:
            return result
        result = stream_resolution_func()
        try:
            stream = stream_lookup_func()
            stream_cache[stream] = result
        except Exception:
            pass
        return result

    return lookup


def get_text_stream(stream="stdout", encoding=None):
    """Retrieve a utf-8 stream wrapper around **sys.stdout** or **sys.stderr**.

    :param str stream: The name of the stream to wrap from the :mod:`sys` module.
    :param str encoding: An optional encoding to use.
    :return: A new :class:`~vistir.misc.StreamWrapper` instance around the stream
    :rtype: `vistir.misc.StreamWrapper`
    """

    stream_map = {"stdin": sys.stdin, "stdout": sys.stdout, "stderr": sys.stderr}
    if os.name == "nt" or sys.platform.startswith("win"):
        from ._winconsole import _get_windows_console_stream, _wrap_std_stream

    else:
        _get_windows_console_stream = lambda *args: None  # noqa
        _wrap_std_stream = lambda *args: None  # noqa

    if six.PY2 and stream != "stdin":
        _wrap_std_stream(stream)
    sys_stream = stream_map[stream]
    windows_console = _get_windows_console_stream(sys_stream, encoding, None)
    if windows_console is not None:
        if _can_use_color(windows_console):
            return _wrap_for_color(windows_console)
        return windows_console
    return get_wrapped_stream(sys_stream, encoding)


def get_text_stdout():
    return get_text_stream("stdout")


def get_text_stderr():
    return get_text_stream("stderr")


def get_text_stdin():
    return get_text_stream("stdin")


_text_stdin = _cached_stream_lookup(lambda: sys.stdin, get_text_stdin)
_text_stdout = _cached_stream_lookup(lambda: sys.stdout, get_text_stdout)
_text_stderr = _cached_stream_lookup(lambda: sys.stderr, get_text_stderr)


TEXT_STREAMS = {
    "stdin": get_text_stdin,
    "stdout": get_text_stdout,
    "stderr": get_text_stderr,
}


def replace_with_text_stream(stream_name):
    """Given a stream name, replace the target stream with a text-converted
    equivalent.

    :param str stream_name: The name of a target stream, such as **stdout** or **stderr**
    :return: None
    """
    new_stream = TEXT_STREAMS.get(stream_name)
    if new_stream is not None:
        new_stream = new_stream()
        setattr(sys, stream_name, new_stream)
    return None


def _can_use_color(stream=None, color=None):
    from .termcolors import DISABLE_COLORS

    if DISABLE_COLORS:
        return False
    if not color:
        if not stream:
            stream = sys.stdin
        return _isatty(stream)
    return bool(color)


def echo(text, fg=None, bg=None, style=None, file=None, err=False, color=None):
    """Write the given text to the provided stream or **sys.stdout** by
    default.

    Provides optional foreground and background colors from the ansi defaults:
    **grey**, **red**, **green**, **yellow**, **blue**, **magenta**, **cyan**
    or **white**.

    Available styles include **bold**, **dark**, **underline**, **blink**, **reverse**,
    **concealed**

    :param str text: Text to write
    :param str fg: Foreground color to use (default: None)
    :param str bg: Foreground color to use (default: None)
    :param str style: Style to use (default: None)
    :param stream file: File to write to (default: None)
    :param bool color: Whether to force color (i.e. ANSI codes are in the text)
    """

    if file and not hasattr(file, "write"):
        raise TypeError("Expected a writable stream, received {!r}".format(file))
    if not file:
        if err:
            file = _text_stderr()
        else:
            file = _text_stdout()
    if text and not isinstance(text, (six.string_types, bytes, bytearray)):
        text = six.text_type(text)
    text = "" if not text else text
    if isinstance(text, six.text_type):
        text += "\n"
    else:
        text += b"\n"
    if text and six.PY3 and is_bytes(text):
        buffer = _get_binary_buffer(file)
        if buffer is not None:
            file.flush()
            buffer.write(text)
            buffer.flush()
            return
    if text and not is_bytes(text):
        can_use_color = _can_use_color(file, color=color)
        if any([fg, bg, style]):
            text = colorize(text, fg=fg, bg=bg, attrs=style)
        if not can_use_color or (os.name == "nt" and not _wrap_for_color):
            text = ANSI_REMOVAL_RE.sub("", text)
        elif os.name == "nt" and _wrap_for_color and not _is_wrapped_for_color(file):
            file = _wrap_for_color(file, color=color)
    if text:
        file.write(text)
    file.flush()
