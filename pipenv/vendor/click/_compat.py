# flake8: noqa
import codecs
import io
import os
import re
import sys
from weakref import WeakKeyDictionary

PY2 = sys.version_info[0] == 2
CYGWIN = sys.platform.startswith("cygwin")
MSYS2 = sys.platform.startswith("win") and ("GCC" in sys.version)
# Determine local App Engine environment, per Google's own suggestion
APP_ENGINE = "APPENGINE_RUNTIME" in os.environ and "Development/" in os.environ.get(
    "SERVER_SOFTWARE", ""
)
WIN = sys.platform.startswith("win") and not APP_ENGINE and not MSYS2
DEFAULT_COLUMNS = 80


_ansi_re = re.compile(r"\033\[[;?0-9]*[a-zA-Z]")


def get_filesystem_encoding():
    return sys.getfilesystemencoding() or sys.getdefaultencoding()


def _make_text_stream(
    stream, encoding, errors, force_readable=False, force_writable=False
):
    if encoding is None:
        encoding = get_best_encoding(stream)
    if errors is None:
        errors = "replace"
    return _NonClosingTextIOWrapper(
        stream,
        encoding,
        errors,
        line_buffering=True,
        force_readable=force_readable,
        force_writable=force_writable,
    )


def is_ascii_encoding(encoding):
    """Checks if a given encoding is ascii."""
    try:
        return codecs.lookup(encoding).name == "ascii"
    except LookupError:
        return False


def get_best_encoding(stream):
    """Returns the default stream encoding if not found."""
    rv = getattr(stream, "encoding", None) or sys.getdefaultencoding()
    if is_ascii_encoding(rv):
        return "utf-8"
    return rv


class _NonClosingTextIOWrapper(io.TextIOWrapper):
    def __init__(
        self,
        stream,
        encoding,
        errors,
        force_readable=False,
        force_writable=False,
        **extra
    ):
        self._stream = stream = _FixupStream(stream, force_readable, force_writable)
        io.TextIOWrapper.__init__(self, stream, encoding, errors, **extra)

    # The io module is a place where the Python 3 text behavior
    # was forced upon Python 2, so we need to unbreak
    # it to look like Python 2.
    if PY2:

        def write(self, x):
            if isinstance(x, str) or is_bytes(x):
                try:
                    self.flush()
                except Exception:
                    pass
                return self.buffer.write(str(x))
            return io.TextIOWrapper.write(self, x)

        def writelines(self, lines):
            for line in lines:
                self.write(line)

    def __del__(self):
        try:
            self.detach()
        except Exception:
            pass

    def isatty(self):
        # https://bitbucket.org/pypy/pypy/issue/1803
        return self._stream.isatty()


class _FixupStream(object):
    """The new io interface needs more from streams than streams
    traditionally implement.  As such, this fix-up code is necessary in
    some circumstances.

    The forcing of readable and writable flags are there because some tools
    put badly patched objects on sys (one such offender are certain version
    of jupyter notebook).
    """

    def __init__(self, stream, force_readable=False, force_writable=False):
        self._stream = stream
        self._force_readable = force_readable
        self._force_writable = force_writable

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def read1(self, size):
        f = getattr(self._stream, "read1", None)
        if f is not None:
            return f(size)
        # We only dispatch to readline instead of read in Python 2 as we
        # do not want cause problems with the different implementation
        # of line buffering.
        if PY2:
            return self._stream.readline(size)
        return self._stream.read(size)

    def readable(self):
        if self._force_readable:
            return True
        x = getattr(self._stream, "readable", None)
        if x is not None:
            return x()
        try:
            self._stream.read(0)
        except Exception:
            return False
        return True

    def writable(self):
        if self._force_writable:
            return True
        x = getattr(self._stream, "writable", None)
        if x is not None:
            return x()
        try:
            self._stream.write("")
        except Exception:
            try:
                self._stream.write(b"")
            except Exception:
                return False
        return True

    def seekable(self):
        x = getattr(self._stream, "seekable", None)
        if x is not None:
            return x()
        try:
            self._stream.seek(self._stream.tell())
        except Exception:
            return False
        return True


if PY2:
    text_type = unicode
    raw_input = raw_input
    string_types = (str, unicode)
    int_types = (int, long)
    iteritems = lambda x: x.iteritems()
    range_type = xrange

    from pipes import quote as shlex_quote

    def is_bytes(x):
        return isinstance(x, (buffer, bytearray))

    _identifier_re = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    # For Windows, we need to force stdout/stdin/stderr to binary if it's
    # fetched for that.  This obviously is not the most correct way to do
    # it as it changes global state.  Unfortunately, there does not seem to
    # be a clear better way to do it as just reopening the file in binary
    # mode does not change anything.
    #
    # An option would be to do what Python 3 does and to open the file as
    # binary only, patch it back to the system, and then use a wrapper
    # stream that converts newlines.  It's not quite clear what's the
    # correct option here.
    #
    # This code also lives in _winconsole for the fallback to the console
    # emulation stream.
    #
    # There are also Windows environments where the `msvcrt` module is not
    # available (which is why we use try-catch instead of the WIN variable
    # here), such as the Google App Engine development server on Windows. In
    # those cases there is just nothing we can do.
    def set_binary_mode(f):
        return f

    try:
        import msvcrt
    except ImportError:
        pass
    else:

        def set_binary_mode(f):
            try:
                fileno = f.fileno()
            except Exception:
                pass
            else:
                msvcrt.setmode(fileno, os.O_BINARY)
            return f

    try:
        import fcntl
    except ImportError:
        pass
    else:

        def set_binary_mode(f):
            try:
                fileno = f.fileno()
            except Exception:
                pass
            else:
                flags = fcntl.fcntl(fileno, fcntl.F_GETFL)
                fcntl.fcntl(fileno, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
            return f

    def isidentifier(x):
        return _identifier_re.search(x) is not None

    def get_binary_stdin():
        return set_binary_mode(sys.stdin)

    def get_binary_stdout():
        _wrap_std_stream("stdout")
        return set_binary_mode(sys.stdout)

    def get_binary_stderr():
        _wrap_std_stream("stderr")
        return set_binary_mode(sys.stderr)

    def get_text_stdin(encoding=None, errors=None):
        rv = _get_windows_console_stream(sys.stdin, encoding, errors)
        if rv is not None:
            return rv
        return _make_text_stream(sys.stdin, encoding, errors, force_readable=True)

    def get_text_stdout(encoding=None, errors=None):
        _wrap_std_stream("stdout")
        rv = _get_windows_console_stream(sys.stdout, encoding, errors)
        if rv is not None:
            return rv
        return _make_text_stream(sys.stdout, encoding, errors, force_writable=True)

    def get_text_stderr(encoding=None, errors=None):
        _wrap_std_stream("stderr")
        rv = _get_windows_console_stream(sys.stderr, encoding, errors)
        if rv is not None:
            return rv
        return _make_text_stream(sys.stderr, encoding, errors, force_writable=True)

    def filename_to_ui(value):
        if isinstance(value, bytes):
            value = value.decode(get_filesystem_encoding(), "replace")
        return value


else:
    import io

    text_type = str
    raw_input = input
    string_types = (str,)
    int_types = (int,)
    range_type = range
    isidentifier = lambda x: x.isidentifier()
    iteritems = lambda x: iter(x.items())

    from shlex import quote as shlex_quote

    def is_bytes(x):
        return isinstance(x, (bytes, memoryview, bytearray))

    def _is_binary_reader(stream, default=False):
        try:
            return isinstance(stream.read(0), bytes)
        except Exception:
            return default
            # This happens in some cases where the stream was already
            # closed.  In this case, we assume the default.

    def _is_binary_writer(stream, default=False):
        try:
            stream.write(b"")
        except Exception:
            try:
                stream.write("")
                return False
            except Exception:
                pass
            return default
        return True

    def _find_binary_reader(stream):
        # We need to figure out if the given stream is already binary.
        # This can happen because the official docs recommend detaching
        # the streams to get binary streams.  Some code might do this, so
        # we need to deal with this case explicitly.
        if _is_binary_reader(stream, False):
            return stream

        buf = getattr(stream, "buffer", None)

        # Same situation here; this time we assume that the buffer is
        # actually binary in case it's closed.
        if buf is not None and _is_binary_reader(buf, True):
            return buf

    def _find_binary_writer(stream):
        # We need to figure out if the given stream is already binary.
        # This can happen because the official docs recommend detatching
        # the streams to get binary streams.  Some code might do this, so
        # we need to deal with this case explicitly.
        if _is_binary_writer(stream, False):
            return stream

        buf = getattr(stream, "buffer", None)

        # Same situation here; this time we assume that the buffer is
        # actually binary in case it's closed.
        if buf is not None and _is_binary_writer(buf, True):
            return buf

    def _stream_is_misconfigured(stream):
        """A stream is misconfigured if its encoding is ASCII."""
        # If the stream does not have an encoding set, we assume it's set
        # to ASCII.  This appears to happen in certain unittest
        # environments.  It's not quite clear what the correct behavior is
        # but this at least will force Click to recover somehow.
        return is_ascii_encoding(getattr(stream, "encoding", None) or "ascii")

    def _is_compat_stream_attr(stream, attr, value):
        """A stream attribute is compatible if it is equal to the
        desired value or the desired value is unset and the attribute
        has a value.
        """
        stream_value = getattr(stream, attr, None)
        return stream_value == value or (value is None and stream_value is not None)

    def _is_compatible_text_stream(stream, encoding, errors):
        """Check if a stream's encoding and errors attributes are
        compatible with the desired values.
        """
        return _is_compat_stream_attr(
            stream, "encoding", encoding
        ) and _is_compat_stream_attr(stream, "errors", errors)

    def _force_correct_text_stream(
        text_stream,
        encoding,
        errors,
        is_binary,
        find_binary,
        force_readable=False,
        force_writable=False,
    ):
        if is_binary(text_stream, False):
            binary_reader = text_stream
        else:
            # If the stream looks compatible, and won't default to a
            # misconfigured ascii encoding, return it as-is.
            if _is_compatible_text_stream(text_stream, encoding, errors) and not (
                encoding is None and _stream_is_misconfigured(text_stream)
            ):
                return text_stream

            # Otherwise, get the underlying binary reader.
            binary_reader = find_binary(text_stream)

            # If that's not possible, silently use the original reader
            # and get mojibake instead of exceptions.
            if binary_reader is None:
                return text_stream

        # Default errors to replace instead of strict in order to get
        # something that works.
        if errors is None:
            errors = "replace"

        # Wrap the binary stream in a text stream with the correct
        # encoding parameters.
        return _make_text_stream(
            binary_reader,
            encoding,
            errors,
            force_readable=force_readable,
            force_writable=force_writable,
        )

    def _force_correct_text_reader(text_reader, encoding, errors, force_readable=False):
        return _force_correct_text_stream(
            text_reader,
            encoding,
            errors,
            _is_binary_reader,
            _find_binary_reader,
            force_readable=force_readable,
        )

    def _force_correct_text_writer(text_writer, encoding, errors, force_writable=False):
        return _force_correct_text_stream(
            text_writer,
            encoding,
            errors,
            _is_binary_writer,
            _find_binary_writer,
            force_writable=force_writable,
        )

    def get_binary_stdin():
        reader = _find_binary_reader(sys.stdin)
        if reader is None:
            raise RuntimeError("Was not able to determine binary stream for sys.stdin.")
        return reader

    def get_binary_stdout():
        writer = _find_binary_writer(sys.stdout)
        if writer is None:
            raise RuntimeError(
                "Was not able to determine binary stream for sys.stdout."
            )
        return writer

    def get_binary_stderr():
        writer = _find_binary_writer(sys.stderr)
        if writer is None:
            raise RuntimeError(
                "Was not able to determine binary stream for sys.stderr."
            )
        return writer

    def get_text_stdin(encoding=None, errors=None):
        rv = _get_windows_console_stream(sys.stdin, encoding, errors)
        if rv is not None:
            return rv
        return _force_correct_text_reader(
            sys.stdin, encoding, errors, force_readable=True
        )

    def get_text_stdout(encoding=None, errors=None):
        rv = _get_windows_console_stream(sys.stdout, encoding, errors)
        if rv is not None:
            return rv
        return _force_correct_text_writer(
            sys.stdout, encoding, errors, force_writable=True
        )

    def get_text_stderr(encoding=None, errors=None):
        rv = _get_windows_console_stream(sys.stderr, encoding, errors)
        if rv is not None:
            return rv
        return _force_correct_text_writer(
            sys.stderr, encoding, errors, force_writable=True
        )

    def filename_to_ui(value):
        if isinstance(value, bytes):
            value = value.decode(get_filesystem_encoding(), "replace")
        else:
            value = value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
        return value


def get_streerror(e, default=None):
    if hasattr(e, "strerror"):
        msg = e.strerror
    else:
        if default is not None:
            msg = default
        else:
            msg = str(e)
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", "replace")
    return msg


def _wrap_io_open(file, mode, encoding, errors):
    """On Python 2, :func:`io.open` returns a text file wrapper that
    requires passing ``unicode`` to ``write``. Need to open the file in
    binary mode then wrap it in a subclass that can write ``str`` and
    ``unicode``.

    Also handles not passing ``encoding`` and ``errors`` in binary mode.
    """
    binary = "b" in mode

    if binary:
        kwargs = {}
    else:
        kwargs = {"encoding": encoding, "errors": errors}

    if not PY2 or binary:
        return io.open(file, mode, **kwargs)

    f = io.open(file, "{}b".format(mode.replace("t", "")))
    return _make_text_stream(f, **kwargs)


def open_stream(filename, mode="r", encoding=None, errors="strict", atomic=False):
    binary = "b" in mode

    # Standard streams first.  These are simple because they don't need
    # special handling for the atomic flag.  It's entirely ignored.
    if filename == "-":
        if any(m in mode for m in ["w", "a", "x"]):
            if binary:
                return get_binary_stdout(), False
            return get_text_stdout(encoding=encoding, errors=errors), False
        if binary:
            return get_binary_stdin(), False
        return get_text_stdin(encoding=encoding, errors=errors), False

    # Non-atomic writes directly go out through the regular open functions.
    if not atomic:
        return _wrap_io_open(filename, mode, encoding, errors), True

    # Some usability stuff for atomic writes
    if "a" in mode:
        raise ValueError(
            "Appending to an existing file is not supported, because that"
            " would involve an expensive `copy`-operation to a temporary"
            " file. Open the file in normal `w`-mode and copy explicitly"
            " if that's what you're after."
        )
    if "x" in mode:
        raise ValueError("Use the `overwrite`-parameter instead.")
    if "w" not in mode:
        raise ValueError("Atomic writes only make sense with `w`-mode.")

    # Atomic writes are more complicated.  They work by opening a file
    # as a proxy in the same folder and then using the fdopen
    # functionality to wrap it in a Python file.  Then we wrap it in an
    # atomic file that moves the file over on close.
    import errno
    import random

    try:
        perm = os.stat(filename).st_mode
    except OSError:
        perm = None

    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL

    if binary:
        flags |= getattr(os, "O_BINARY", 0)

    while True:
        tmp_filename = os.path.join(
            os.path.dirname(filename),
            ".__atomic-write{:08x}".format(random.randrange(1 << 32)),
        )
        try:
            fd = os.open(tmp_filename, flags, 0o666 if perm is None else perm)
            break
        except OSError as e:
            if e.errno == errno.EEXIST or (
                os.name == "nt"
                and e.errno == errno.EACCES
                and os.path.isdir(e.filename)
                and os.access(e.filename, os.W_OK)
            ):
                continue
            raise

    if perm is not None:
        os.chmod(tmp_filename, perm)  # in case perm includes bits in umask

    f = _wrap_io_open(fd, mode, encoding, errors)
    return _AtomicFile(f, tmp_filename, os.path.realpath(filename)), True


# Used in a destructor call, needs extra protection from interpreter cleanup.
if hasattr(os, "replace"):
    _replace = os.replace
    _can_replace = True
else:
    _replace = os.rename
    _can_replace = not WIN


class _AtomicFile(object):
    def __init__(self, f, tmp_filename, real_filename):
        self._f = f
        self._tmp_filename = tmp_filename
        self._real_filename = real_filename
        self.closed = False

    @property
    def name(self):
        return self._real_filename

    def close(self, delete=False):
        if self.closed:
            return
        self._f.close()
        if not _can_replace:
            try:
                os.remove(self._real_filename)
            except OSError:
                pass
        _replace(self._tmp_filename, self._real_filename)
        self.closed = True

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.close(delete=exc_type is not None)

    def __repr__(self):
        return repr(self._f)


auto_wrap_for_ansi = None
colorama = None
get_winterm_size = None


def strip_ansi(value):
    return _ansi_re.sub("", value)


def _is_jupyter_kernel_output(stream):
    if WIN:
        # TODO: Couldn't test on Windows, should't try to support until
        # someone tests the details wrt colorama.
        return

    while isinstance(stream, (_FixupStream, _NonClosingTextIOWrapper)):
        stream = stream._stream

    return stream.__class__.__module__.startswith("ipykernel.")


def should_strip_ansi(stream=None, color=None):
    if color is None:
        if stream is None:
            stream = sys.stdin
        return not isatty(stream) and not _is_jupyter_kernel_output(stream)
    return not color


# If we're on Windows, we provide transparent integration through
# colorama.  This will make ANSI colors through the echo function
# work automatically.
if WIN:
    # Windows has a smaller terminal
    DEFAULT_COLUMNS = 79

    from ._winconsole import _get_windows_console_stream, _wrap_std_stream

    def _get_argv_encoding():
        import locale

        return locale.getpreferredencoding()

    if PY2:

        def raw_input(prompt=""):
            sys.stderr.flush()
            if prompt:
                stdout = _default_text_stdout()
                stdout.write(prompt)
            stdin = _default_text_stdin()
            return stdin.readline().rstrip("\r\n")

    try:
        import colorama
    except ImportError:
        pass
    else:
        _ansi_stream_wrappers = WeakKeyDictionary()

        def auto_wrap_for_ansi(stream, color=None):
            """This function wraps a stream so that calls through colorama
            are issued to the win32 console API to recolor on demand.  It
            also ensures to reset the colors if a write call is interrupted
            to not destroy the console afterwards.
            """
            try:
                cached = _ansi_stream_wrappers.get(stream)
            except Exception:
                cached = None
            if cached is not None:
                return cached
            strip = should_strip_ansi(stream, color)
            ansi_wrapper = colorama.AnsiToWin32(stream, strip=strip)
            rv = ansi_wrapper.stream
            _write = rv.write

            def _safe_write(s):
                try:
                    return _write(s)
                except:
                    ansi_wrapper.reset_all()
                    raise

            rv.write = _safe_write
            try:
                _ansi_stream_wrappers[stream] = rv
            except Exception:
                pass
            return rv

        def get_winterm_size():
            win = colorama.win32.GetConsoleScreenBufferInfo(
                colorama.win32.STDOUT
            ).srWindow
            return win.Right - win.Left, win.Bottom - win.Top


else:

    def _get_argv_encoding():
        return getattr(sys.stdin, "encoding", None) or get_filesystem_encoding()

    _get_windows_console_stream = lambda *x: None
    _wrap_std_stream = lambda *x: None


def term_len(x):
    return len(strip_ansi(x))


def isatty(stream):
    try:
        return stream.isatty()
    except Exception:
        return False


def _make_cached_stream_func(src_func, wrapper_func):
    cache = WeakKeyDictionary()

    def func():
        stream = src_func()
        try:
            rv = cache.get(stream)
        except Exception:
            rv = None
        if rv is not None:
            return rv
        rv = wrapper_func()
        try:
            stream = src_func()  # In case wrapper_func() modified the stream
            cache[stream] = rv
        except Exception:
            pass
        return rv

    return func


_default_text_stdin = _make_cached_stream_func(lambda: sys.stdin, get_text_stdin)
_default_text_stdout = _make_cached_stream_func(lambda: sys.stdout, get_text_stdout)
_default_text_stderr = _make_cached_stream_func(lambda: sys.stderr, get_text_stderr)


binary_streams = {
    "stdin": get_binary_stdin,
    "stdout": get_binary_stdout,
    "stderr": get_binary_stderr,
}

text_streams = {
    "stdin": get_text_stdin,
    "stdout": get_text_stdout,
    "stderr": get_text_stderr,
}
