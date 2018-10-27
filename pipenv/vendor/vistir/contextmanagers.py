# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import io
import os
import stat
import sys

from contextlib import contextmanager

import six

from .compat import NamedTemporaryFile, Path
from .path import is_file_url, is_valid_url, path_to_url, url_to_path


__all__ = [
    "temp_environ", "temp_path", "cd", "atomic_open_for_write", "open_file", "spinner"
]


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


@contextmanager
def temp_path():
    """A context manager which allows the ability to set sys.path temporarily

    >>> path_from_virtualenv = load_path("/path/to/venv/bin/python")
    >>> print(sys.path)
    ['/home/user/.pyenv/versions/3.7.0/bin', '/home/user/.pyenv/versions/3.7.0/lib/python37.zip', '/home/user/.pyenv/versions/3.7.0/lib/python3.7', '/home/user/.pyenv/versions/3.7.0/lib/python3.7/lib-dynload', '/home/user/.pyenv/versions/3.7.0/lib/python3.7/site-packages']
    >>> with temp_path():
            sys.path = path_from_virtualenv
            # Running in the context of the path above
            run(["pip", "install", "stuff"])
    >>> print(sys.path)
    ['/home/user/.pyenv/versions/3.7.0/bin', '/home/user/.pyenv/versions/3.7.0/lib/python37.zip', '/home/user/.pyenv/versions/3.7.0/lib/python3.7', '/home/user/.pyenv/versions/3.7.0/lib/python3.7/lib-dynload', '/home/user/.pyenv/versions/3.7.0/lib/python3.7/site-packages']

    """
    path = [p for p in sys.path]
    try:
        yield
    finally:
        sys.path = [p for p in path]


@contextmanager
def cd(path):
    """Context manager to temporarily change working directories

    :param str path: The directory to move into

    >>> print(os.path.abspath(os.curdir))
    '/home/user/code/myrepo'
    >>> with cd("/home/user/code/otherdir/subdir"):
            print("Changed directory: %s" % os.path.abspath(os.curdir))
    Changed directory: /home/user/code/otherdir/subdir
    >>> print(os.path.abspath(os.curdir))
    '/home/user/code/myrepo'
    """
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


@contextmanager
def dummy_spinner(spin_type, text, **kwargs):
    class FakeClass(object):
        def __init__(self, text=""):
            self.text = text

        def fail(self, exitcode=1, text=None):
            if text:
                print(text)
            raise SystemExit(exitcode, text)

        def ok(self, text):
            print(text)
            return 0

        def write(self, text):
            print(text)

    myobj = FakeClass(text)
    yield myobj


@contextmanager
def spinner(spinner_name=None, start_text=None, handler_map=None, nospin=False):
    """Get a spinner object or a dummy spinner to wrap a context.

    :param str spinner_name: A spinner type e.g. "dots" or "bouncingBar" (default: {"bouncingBar"})
    :param str start_text: Text to start off the spinner with (default: {None})
    :param dict handler_map: Handler map for signals to be handled gracefully (default: {None})
    :param bool nospin: If true, use the dummy spinner (default: {False})
    :return: A spinner object which can be manipulated while alive
    :rtype: :class:`~vistir.spin.VistirSpinner`

    Raises:
        RuntimeError -- Raised if the spinner extra is not installed
    """

    from .spin import create_spinner
    has_yaspin = False
    try:
        import yaspin
    except ImportError:
        if not nospin:
            raise RuntimeError(
                "Failed to import spinner! Reinstall vistir with command:"
                " pip install --upgrade vistir[spinner]"
            )
        else:
            spinner_name = ""
    else:
        has_yaspin = True
        spinner_name = ""
    if not start_text and nospin is False:
        start_text = "Running..."
    with create_spinner(
        spinner_name=spinner_name,
        text=start_text,
        handler_map=handler_map,
        nospin=nospin,
        use_yaspin=has_yaspin
    ) as _spinner:
        yield _spinner


@contextmanager
def atomic_open_for_write(target, binary=False, newline=None, encoding=None):
    """Atomically open `target` for writing.

    This is based on Lektor's `atomic_open()` utility, but simplified a lot
    to handle only writing, and skip many multi-process/thread edge cases
    handled by Werkzeug.

    :param str target: Target filename to write
    :param bool binary: Whether to open in binary mode, default False
    :param str newline: The newline character to use when writing, determined from system if not supplied
    :param str encoding: The encoding to use when writing, defaults to system encoding

    How this works:

    * Create a temp file (in the same directory of the actual target), and
      yield for surrounding code to write to it.
    * If some thing goes wrong, try to remove the temp file. The actual target
      is not touched whatsoever.
    * If everything goes well, close the temp file, and replace the actual
      target with this new file.

    .. code:: python

        >>> fn = "test_file.txt"
        >>> def read_test_file(filename=fn):
                with open(filename, 'r') as fh:
                    print(fh.read().strip())

        >>> with open(fn, "w") as fh:
                fh.write("this is some test text")
        >>> read_test_file()
        this is some test text

        >>> def raise_exception_while_writing(filename):
                with open(filename, "w") as fh:
                    fh.write("writing some new text")
                    raise RuntimeError("Uh oh, hope your file didn't get overwritten")

        >>> raise_exception_while_writing(fn)
        Traceback (most recent call last):
            ...
        RuntimeError: Uh oh, hope your file didn't get overwritten
        >>> read_test_file()
        writing some new text

        # Now try with vistir
        >>> def raise_exception_while_writing(filename):
                with vistir.contextmanagers.atomic_open_for_write(filename) as fh:
                    fh.write("Overwriting all the text from before with even newer text")
                    raise RuntimeError("But did it get overwritten now?")

        >>> raise_exception_while_writing(fn)
            Traceback (most recent call last):
                ...
            RuntimeError: But did it get overwritten now?

        >>> read_test_file()
            writing some new text
    """

    mode = "w+b" if binary else "w"
    f = NamedTemporaryFile(
        dir=os.path.dirname(target),
        prefix=".__atomic-write",
        mode=mode,
        encoding=encoding,
        newline=newline,
        delete=False,
    )
    # set permissions to 0644
    os.chmod(f.name, stat.S_IWUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        yield f
    except BaseException:
        f.close()
        try:
            os.remove(f.name)
        except OSError:
            pass
        raise
    else:
        f.close()
        try:
            os.remove(target)  # This is needed on Windows.
        except OSError:
            pass
        os.rename(f.name, target)  # No os.replace() on Python 2.


@contextmanager
def open_file(link, session=None, stream=True):
    """
    Open local or remote file for reading.

    :type link: pip._internal.index.Link or str
    :type session: requests.Session
    :param bool stream: Try to stream if remote, default True
    :raises ValueError: If link points to a local directory.
    :return: a context manager to the opened file-like object
    """
    if not isinstance(link, six.string_types):
        try:
            link = link.url_without_fragment
        except AttributeError:
            raise ValueError("Cannot parse url from unkown type: {0!r}".format(link))

    if not is_valid_url(link) and os.path.exists(link):
        link = path_to_url(link)

    if is_file_url(link):
        # Local URL
        local_path = url_to_path(link)
        if os.path.isdir(local_path):
            raise ValueError("Cannot open directory for read: {}".format(link))
        else:
                with io.open(local_path, "rb") as local_file:
                    yield local_file
    else:
        # Remote URL
        headers = {"Accept-Encoding": "identity"}
        if not session:
            from requests import Session

            session = Session()
        with session.get(link, headers=headers, stream=stream) as resp:
            try:
                raw = getattr(resp, "raw", None)
                result = raw if raw else resp
                yield result
            finally:
                if raw:
                    conn = getattr(raw, "_connection")
                    if conn is not None:
                        conn.close()
                result.close()
