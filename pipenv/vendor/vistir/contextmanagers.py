# -*- coding=utf-8 -*-
import io
import os

import stat
import sys
import typing

from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib import request

from .path import is_file_url, is_valid_url, path_to_url, url_to_path

if typing.TYPE_CHECKING:
    from typing import (
        Any,
        Bytes,
        Callable,
        ContextManager,
        Dict,
        IO,
        Iterator,
        Optional,
        Union,
        Text,
        Tuple,
        TypeVar,
    )
    from types import ModuleType
    from pipenv.patched.pip._vendor.requests import Session
    from http.client import HTTPResponse as Urllib_HTTPResponse
    from pipenv.patched.pip._vendor.urllib3.response import HTTPResponse as Urllib3_HTTPResponse
    from .spin import VistirSpinner, DummySpinner

    TSpinner = Union[VistirSpinner, DummySpinner]
    _T = TypeVar("_T")


__all__ = [
    "temp_environ",
    "temp_path",
    "cd",
    "atomic_open_for_write",
    "open_file",
    "spinner",
    "dummy_spinner",
    "replaced_stream",
    "replaced_streams",
]


# Borrowed from Pew.
# See https://github.com/berdario/pew/blob/master/pew/_utils.py#L82
@contextmanager
def temp_environ():
    # type: () -> Iterator[None]
    """Allow the ability to set os.environ temporarily"""
    environ = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(environ)


@contextmanager
def temp_path():
    # type: () -> Iterator[None]
    """A context manager which allows the ability to set sys.path temporarily

    >>> path_from_virtualenv = load_path("/path/to/venv/bin/python")
    >>> print(sys.path)
    [
        '/home/user/.pyenv/versions/3.7.0/bin',
        '/home/user/.pyenv/versions/3.7.0/lib/python37.zip',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7/lib-dynload',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7/site-packages'
    ]
    >>> with temp_path():
            sys.path = path_from_virtualenv
            # Running in the context of the path above
            run(["pip", "install", "stuff"])
    >>> print(sys.path)
    [
        '/home/user/.pyenv/versions/3.7.0/bin',
        '/home/user/.pyenv/versions/3.7.0/lib/python37.zip',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7/lib-dynload',
        '/home/user/.pyenv/versions/3.7.0/lib/python3.7/site-packages'
    ]

    """
    path = [p for p in sys.path]
    try:
        yield
    finally:
        sys.path = [p for p in path]


@contextmanager
def cd(path):
    # type: () -> Iterator[None]
    """Context manager to temporarily change working directories

    :param str path: The directory to move into

    >>> print(os.path.abspath(os.curdir))
    '/home/user/code/myrepo'
    >>> with cd("/home/user/code/otherdir/subdir"):
    ...     print("Changed directory: %s" % os.path.abspath(os.curdir))
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
    # type: (str, str, Any)
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
def spinner(
    spinner_name=None,  # type: Optional[str]
    start_text=None,  # type: Optional[str]
    handler_map=None,  # type: Optional[Dict[str, Callable]]
    nospin=False,  # type: bool
    write_to_stdout=True,  # type: bool
):
    # type: (...) -> ContextManager[TSpinner]
    """Get a spinner object or a dummy spinner to wrap a context.

    :param str spinner_name: A spinner type e.g. "dots" or "bouncingBar" (default: {"bouncingBar"})
    :param str start_text: Text to start off the spinner with (default: {None})
    :param dict handler_map: Handler map for signals to be handled gracefully (default: {None})
    :param bool nospin: If true, use the dummy spinner (default: {False})
    :param bool write_to_stdout: Writes to stdout if true, otherwise writes to stderr (default: True)
    :return: A spinner object which can be manipulated while alive
    :rtype: :class:`~vistir.spin.VistirSpinner`

    Raises:
        RuntimeError -- Raised if the spinner extra is not installed
    """

    from .spin import create_spinner

    has_yaspin = None
    try:
        import yaspin
    except (ImportError, ModuleNotFoundError):  # noqa
        has_yaspin = False
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
    use_yaspin = (has_yaspin is False) or (nospin is True)
    if has_yaspin is None or has_yaspin is True and not nospin:
        use_yaspin = True
    if start_text is None and use_yaspin is True:
        start_text = "Running..."
    with create_spinner(
        spinner_name=spinner_name,
        text=start_text,
        handler_map=handler_map,
        nospin=nospin,
        use_yaspin=use_yaspin,
        write_to_stdout=write_to_stdout,
    ) as _spinner:
        yield _spinner


@contextmanager
def atomic_open_for_write(target, binary=False, newline=None, encoding=None):
    # type: (str, bool, Optional[str], Optional[str]) -> None
    """Atomically open `target` for writing.

    This is based on Lektor's `atomic_open()` utility, but simplified a lot
    to handle only writing, and skip many multi-process/thread edge cases
    handled by Werkzeug.

    :param str target: Target filename to write
    :param bool binary: Whether to open in binary mode, default False
    :param Optional[str] newline: The newline character to use when writing, determined
        from system if not supplied.
    :param Optional[str] encoding: The encoding to use when writing, defaults to system
        encoding.

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
    try:
        os.chmod(f.name, stat.S_IWUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass
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
def open_file(
    link,  # type: Union[_T, str]
    session=None,  # type: Optional[Session]
    stream=True,  # type: bool
):
    # type: (...) -> ContextManager[Union[IO[bytes], Urllib3_HTTPResponse, Urllib_HTTPResponse]]
    """
    Open local or remote file for reading.

    :param pipenv.patched.pip._internal.index.Link link: A link object from resolving dependencies with
        pip, or else a URL.
    :param Optional[Session] session: A :class:`~requests.Session` instance
    :param bool stream: Whether to stream the content if remote, default True
    :raises ValueError: If link points to a local directory.
    :return: a context manager to the opened file-like object
    """
    if not isinstance(link, str):
        try:
            link = link.url_without_fragment
        except AttributeError:
            raise ValueError("Cannot parse url from unknown type: {0!r}".format(link))

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
            try:
                from pipenv.patched.pip._vendor.requests import Session  # noqa
            except ImportError:
                session = None
            else:
                session = Session()
        if session is None:
            with closing(request.urlopen(link)) as f:
                yield f
        else:
            with session.get(link, headers=headers, stream=stream) as resp:
                try:
                    raw = getattr(resp, "raw", None)
                    result = raw if raw else resp
                    yield result
                finally:
                    if raw:
                        conn = raw._connection
                        if conn is not None:
                            conn.close()
                    result.close()


@contextmanager
def replaced_stream(stream_name):
    # type: (str) -> Iterator[IO[Text]]
    """
    Context manager to temporarily swap out *stream_name* with a stream wrapper.

    :param str stream_name: The name of a sys stream to wrap
    :returns: A ``StreamWrapper`` replacement, temporarily

    >>> orig_stdout = sys.stdout
    >>> with replaced_stream("stdout") as stdout:
    ...     sys.stdout.write("hello")
    ...     assert stdout.getvalue() == "hello"

    >>> sys.stdout.write("hello")
    'hello'
    """

    orig_stream = getattr(sys, stream_name)
    new_stream = io.StringIO()
    try:
        setattr(sys, stream_name, new_stream)
        yield getattr(sys, stream_name)
    finally:
        setattr(sys, stream_name, orig_stream)


@contextmanager
def replaced_streams():
    # type: () -> Iterator[Tuple[IO[Text], IO[Text]]]
    """
    Context manager to replace both ``sys.stdout`` and ``sys.stderr`` using
    ``replaced_stream``

    returns: *(stdout, stderr)*

    >>> import sys
    >>> with vistir.contextmanagers.replaced_streams() as streams:
    >>>     stdout, stderr = streams
    >>>     sys.stderr.write("test")
    >>>     sys.stdout.write("hello")
    >>>     assert stdout.getvalue() == "hello"
    >>>     assert stderr.getvalue() == "test"

    >>> stdout.getvalue()
    'hello'

    >>> stderr.getvalue()
    'test'
    """

    with replaced_stream("stdout") as stdout:
        with replaced_stream("stderr") as stderr:
            yield (stdout, stderr)
