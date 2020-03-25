import os
import stat
from datetime import datetime

from ._compat import _get_argv_encoding
from ._compat import filename_to_ui
from ._compat import get_filesystem_encoding
from ._compat import get_streerror
from ._compat import open_stream
from ._compat import PY2
from ._compat import text_type
from .exceptions import BadParameter
from .utils import LazyFile
from .utils import safecall


class ParamType(object):
    """Helper for converting values through types.  The following is
    necessary for a valid type:

    *   it needs a name
    *   it needs to pass through None unchanged
    *   it needs to convert from a string
    *   it needs to convert its result type through unchanged
        (eg: needs to be idempotent)
    *   it needs to be able to deal with param and context being `None`.
        This can be the case when the object is used with prompt
        inputs.
    """

    is_composite = False

    #: the descriptive name of this type
    name = None

    #: if a list of this type is expected and the value is pulled from a
    #: string environment variable, this is what splits it up.  `None`
    #: means any whitespace.  For all parameters the general rule is that
    #: whitespace splits them up.  The exception are paths and files which
    #: are split by ``os.path.pathsep`` by default (":" on Unix and ";" on
    #: Windows).
    envvar_list_splitter = None

    def __call__(self, value, param=None, ctx=None):
        if value is not None:
            return self.convert(value, param, ctx)

    def get_metavar(self, param):
        """Returns the metavar default for this param if it provides one."""

    def get_missing_message(self, param):
        """Optionally might return extra information about a missing
        parameter.

        .. versionadded:: 2.0
        """

    def convert(self, value, param, ctx):
        """Converts the value.  This is not invoked for values that are
        `None` (the missing value).
        """
        return value

    def split_envvar_value(self, rv):
        """Given a value from an environment variable this splits it up
        into small chunks depending on the defined envvar list splitter.

        If the splitter is set to `None`, which means that whitespace splits,
        then leading and trailing whitespace is ignored.  Otherwise, leading
        and trailing splitters usually lead to empty items being included.
        """
        return (rv or "").split(self.envvar_list_splitter)

    def fail(self, message, param=None, ctx=None):
        """Helper method to fail with an invalid value message."""
        raise BadParameter(message, ctx=ctx, param=param)


class CompositeParamType(ParamType):
    is_composite = True

    @property
    def arity(self):
        raise NotImplementedError()


class FuncParamType(ParamType):
    def __init__(self, func):
        self.name = func.__name__
        self.func = func

    def convert(self, value, param, ctx):
        try:
            return self.func(value)
        except ValueError:
            try:
                value = text_type(value)
            except UnicodeError:
                value = str(value).decode("utf-8", "replace")
            self.fail(value, param, ctx)


class UnprocessedParamType(ParamType):
    name = "text"

    def convert(self, value, param, ctx):
        return value

    def __repr__(self):
        return "UNPROCESSED"


class StringParamType(ParamType):
    name = "text"

    def convert(self, value, param, ctx):
        if isinstance(value, bytes):
            enc = _get_argv_encoding()
            try:
                value = value.decode(enc)
            except UnicodeError:
                fs_enc = get_filesystem_encoding()
                if fs_enc != enc:
                    try:
                        value = value.decode(fs_enc)
                    except UnicodeError:
                        value = value.decode("utf-8", "replace")
                else:
                    value = value.decode("utf-8", "replace")
            return value
        return value

    def __repr__(self):
        return "STRING"


class Choice(ParamType):
    """The choice type allows a value to be checked against a fixed set
    of supported values. All of these values have to be strings.

    You should only pass a list or tuple of choices. Other iterables
    (like generators) may lead to surprising results.

    The resulting value will always be one of the originally passed choices
    regardless of ``case_sensitive`` or any ``ctx.token_normalize_func``
    being specified.

    See :ref:`choice-opts` for an example.

    :param case_sensitive: Set to false to make choices case
        insensitive. Defaults to true.
    """

    name = "choice"

    def __init__(self, choices, case_sensitive=True):
        self.choices = choices
        self.case_sensitive = case_sensitive

    def get_metavar(self, param):
        return "[{}]".format("|".join(self.choices))

    def get_missing_message(self, param):
        return "Choose from:\n\t{}.".format(",\n\t".join(self.choices))

    def convert(self, value, param, ctx):
        # Match through normalization and case sensitivity
        # first do token_normalize_func, then lowercase
        # preserve original `value` to produce an accurate message in
        # `self.fail`
        normed_value = value
        normed_choices = {choice: choice for choice in self.choices}

        if ctx is not None and ctx.token_normalize_func is not None:
            normed_value = ctx.token_normalize_func(value)
            normed_choices = {
                ctx.token_normalize_func(normed_choice): original
                for normed_choice, original in normed_choices.items()
            }

        if not self.case_sensitive:
            if PY2:
                lower = str.lower
            else:
                lower = str.casefold

            normed_value = lower(normed_value)
            normed_choices = {
                lower(normed_choice): original
                for normed_choice, original in normed_choices.items()
            }

        if normed_value in normed_choices:
            return normed_choices[normed_value]

        self.fail(
            "invalid choice: {}. (choose from {})".format(
                value, ", ".join(self.choices)
            ),
            param,
            ctx,
        )

    def __repr__(self):
        return "Choice('{}')".format(list(self.choices))


class DateTime(ParamType):
    """The DateTime type converts date strings into `datetime` objects.

    The format strings which are checked are configurable, but default to some
    common (non-timezone aware) ISO 8601 formats.

    When specifying *DateTime* formats, you should only pass a list or a tuple.
    Other iterables, like generators, may lead to surprising results.

    The format strings are processed using ``datetime.strptime``, and this
    consequently defines the format strings which are allowed.

    Parsing is tried using each format, in order, and the first format which
    parses successfully is used.

    :param formats: A list or tuple of date format strings, in the order in
                    which they should be tried. Defaults to
                    ``'%Y-%m-%d'``, ``'%Y-%m-%dT%H:%M:%S'``,
                    ``'%Y-%m-%d %H:%M:%S'``.
    """

    name = "datetime"

    def __init__(self, formats=None):
        self.formats = formats or ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]

    def get_metavar(self, param):
        return "[{}]".format("|".join(self.formats))

    def _try_to_convert_date(self, value, format):
        try:
            return datetime.strptime(value, format)
        except ValueError:
            return None

    def convert(self, value, param, ctx):
        # Exact match
        for format in self.formats:
            dtime = self._try_to_convert_date(value, format)
            if dtime:
                return dtime

        self.fail(
            "invalid datetime format: {}. (choose from {})".format(
                value, ", ".join(self.formats)
            )
        )

    def __repr__(self):
        return "DateTime"


class IntParamType(ParamType):
    name = "integer"

    def convert(self, value, param, ctx):
        try:
            return int(value)
        except ValueError:
            self.fail("{} is not a valid integer".format(value), param, ctx)

    def __repr__(self):
        return "INT"


class IntRange(IntParamType):
    """A parameter that works similar to :data:`click.INT` but restricts
    the value to fit into a range.  The default behavior is to fail if the
    value falls outside the range, but it can also be silently clamped
    between the two edges.

    See :ref:`ranges` for an example.
    """

    name = "integer range"

    def __init__(self, min=None, max=None, clamp=False):
        self.min = min
        self.max = max
        self.clamp = clamp

    def convert(self, value, param, ctx):
        rv = IntParamType.convert(self, value, param, ctx)
        if self.clamp:
            if self.min is not None and rv < self.min:
                return self.min
            if self.max is not None and rv > self.max:
                return self.max
        if (
            self.min is not None
            and rv < self.min
            or self.max is not None
            and rv > self.max
        ):
            if self.min is None:
                self.fail(
                    "{} is bigger than the maximum valid value {}.".format(
                        rv, self.max
                    ),
                    param,
                    ctx,
                )
            elif self.max is None:
                self.fail(
                    "{} is smaller than the minimum valid value {}.".format(
                        rv, self.min
                    ),
                    param,
                    ctx,
                )
            else:
                self.fail(
                    "{} is not in the valid range of {} to {}.".format(
                        rv, self.min, self.max
                    ),
                    param,
                    ctx,
                )
        return rv

    def __repr__(self):
        return "IntRange({}, {})".format(self.min, self.max)


class FloatParamType(ParamType):
    name = "float"

    def convert(self, value, param, ctx):
        try:
            return float(value)
        except ValueError:
            self.fail(
                "{} is not a valid floating point value".format(value), param, ctx
            )

    def __repr__(self):
        return "FLOAT"


class FloatRange(FloatParamType):
    """A parameter that works similar to :data:`click.FLOAT` but restricts
    the value to fit into a range.  The default behavior is to fail if the
    value falls outside the range, but it can also be silently clamped
    between the two edges.

    See :ref:`ranges` for an example.
    """

    name = "float range"

    def __init__(self, min=None, max=None, clamp=False):
        self.min = min
        self.max = max
        self.clamp = clamp

    def convert(self, value, param, ctx):
        rv = FloatParamType.convert(self, value, param, ctx)
        if self.clamp:
            if self.min is not None and rv < self.min:
                return self.min
            if self.max is not None and rv > self.max:
                return self.max
        if (
            self.min is not None
            and rv < self.min
            or self.max is not None
            and rv > self.max
        ):
            if self.min is None:
                self.fail(
                    "{} is bigger than the maximum valid value {}.".format(
                        rv, self.max
                    ),
                    param,
                    ctx,
                )
            elif self.max is None:
                self.fail(
                    "{} is smaller than the minimum valid value {}.".format(
                        rv, self.min
                    ),
                    param,
                    ctx,
                )
            else:
                self.fail(
                    "{} is not in the valid range of {} to {}.".format(
                        rv, self.min, self.max
                    ),
                    param,
                    ctx,
                )
        return rv

    def __repr__(self):
        return "FloatRange({}, {})".format(self.min, self.max)


class BoolParamType(ParamType):
    name = "boolean"

    def convert(self, value, param, ctx):
        if isinstance(value, bool):
            return bool(value)
        value = value.lower()
        if value in ("true", "t", "1", "yes", "y"):
            return True
        elif value in ("false", "f", "0", "no", "n"):
            return False
        self.fail("{} is not a valid boolean".format(value), param, ctx)

    def __repr__(self):
        return "BOOL"


class UUIDParameterType(ParamType):
    name = "uuid"

    def convert(self, value, param, ctx):
        import uuid

        try:
            if PY2 and isinstance(value, text_type):
                value = value.encode("ascii")
            return uuid.UUID(value)
        except ValueError:
            self.fail("{} is not a valid UUID value".format(value), param, ctx)

    def __repr__(self):
        return "UUID"


class File(ParamType):
    """Declares a parameter to be a file for reading or writing.  The file
    is automatically closed once the context tears down (after the command
    finished working).

    Files can be opened for reading or writing.  The special value ``-``
    indicates stdin or stdout depending on the mode.

    By default, the file is opened for reading text data, but it can also be
    opened in binary mode or for writing.  The encoding parameter can be used
    to force a specific encoding.

    The `lazy` flag controls if the file should be opened immediately or upon
    first IO. The default is to be non-lazy for standard input and output
    streams as well as files opened for reading, `lazy` otherwise. When opening a
    file lazily for reading, it is still opened temporarily for validation, but
    will not be held open until first IO. lazy is mainly useful when opening
    for writing to avoid creating the file until it is needed.

    Starting with Click 2.0, files can also be opened atomically in which
    case all writes go into a separate file in the same folder and upon
    completion the file will be moved over to the original location.  This
    is useful if a file regularly read by other users is modified.

    See :ref:`file-args` for more information.
    """

    name = "filename"
    envvar_list_splitter = os.path.pathsep

    def __init__(
        self, mode="r", encoding=None, errors="strict", lazy=None, atomic=False
    ):
        self.mode = mode
        self.encoding = encoding
        self.errors = errors
        self.lazy = lazy
        self.atomic = atomic

    def resolve_lazy_flag(self, value):
        if self.lazy is not None:
            return self.lazy
        if value == "-":
            return False
        elif "w" in self.mode:
            return True
        return False

    def convert(self, value, param, ctx):
        try:
            if hasattr(value, "read") or hasattr(value, "write"):
                return value

            lazy = self.resolve_lazy_flag(value)

            if lazy:
                f = LazyFile(
                    value, self.mode, self.encoding, self.errors, atomic=self.atomic
                )
                if ctx is not None:
                    ctx.call_on_close(f.close_intelligently)
                return f

            f, should_close = open_stream(
                value, self.mode, self.encoding, self.errors, atomic=self.atomic
            )
            # If a context is provided, we automatically close the file
            # at the end of the context execution (or flush out).  If a
            # context does not exist, it's the caller's responsibility to
            # properly close the file.  This for instance happens when the
            # type is used with prompts.
            if ctx is not None:
                if should_close:
                    ctx.call_on_close(safecall(f.close))
                else:
                    ctx.call_on_close(safecall(f.flush))
            return f
        except (IOError, OSError) as e:  # noqa: B014
            self.fail(
                "Could not open file: {}: {}".format(
                    filename_to_ui(value), get_streerror(e)
                ),
                param,
                ctx,
            )


class Path(ParamType):
    """The path type is similar to the :class:`File` type but it performs
    different checks.  First of all, instead of returning an open file
    handle it returns just the filename.  Secondly, it can perform various
    basic checks about what the file or directory should be.

    .. versionchanged:: 6.0
       `allow_dash` was added.

    :param exists: if set to true, the file or directory needs to exist for
                   this value to be valid.  If this is not required and a
                   file does indeed not exist, then all further checks are
                   silently skipped.
    :param file_okay: controls if a file is a possible value.
    :param dir_okay: controls if a directory is a possible value.
    :param writable: if true, a writable check is performed.
    :param readable: if true, a readable check is performed.
    :param resolve_path: if this is true, then the path is fully resolved
                         before the value is passed onwards.  This means
                         that it's absolute and symlinks are resolved.  It
                         will not expand a tilde-prefix, as this is
                         supposed to be done by the shell only.
    :param allow_dash: If this is set to `True`, a single dash to indicate
                       standard streams is permitted.
    :param path_type: optionally a string type that should be used to
                      represent the path.  The default is `None` which
                      means the return value will be either bytes or
                      unicode depending on what makes most sense given the
                      input data Click deals with.
    """

    envvar_list_splitter = os.path.pathsep

    def __init__(
        self,
        exists=False,
        file_okay=True,
        dir_okay=True,
        writable=False,
        readable=True,
        resolve_path=False,
        allow_dash=False,
        path_type=None,
    ):
        self.exists = exists
        self.file_okay = file_okay
        self.dir_okay = dir_okay
        self.writable = writable
        self.readable = readable
        self.resolve_path = resolve_path
        self.allow_dash = allow_dash
        self.type = path_type

        if self.file_okay and not self.dir_okay:
            self.name = "file"
            self.path_type = "File"
        elif self.dir_okay and not self.file_okay:
            self.name = "directory"
            self.path_type = "Directory"
        else:
            self.name = "path"
            self.path_type = "Path"

    def coerce_path_result(self, rv):
        if self.type is not None and not isinstance(rv, self.type):
            if self.type is text_type:
                rv = rv.decode(get_filesystem_encoding())
            else:
                rv = rv.encode(get_filesystem_encoding())
        return rv

    def convert(self, value, param, ctx):
        rv = value

        is_dash = self.file_okay and self.allow_dash and rv in (b"-", "-")

        if not is_dash:
            if self.resolve_path:
                rv = os.path.realpath(rv)

            try:
                st = os.stat(rv)
            except OSError:
                if not self.exists:
                    return self.coerce_path_result(rv)
                self.fail(
                    "{} '{}' does not exist.".format(
                        self.path_type, filename_to_ui(value)
                    ),
                    param,
                    ctx,
                )

            if not self.file_okay and stat.S_ISREG(st.st_mode):
                self.fail(
                    "{} '{}' is a file.".format(self.path_type, filename_to_ui(value)),
                    param,
                    ctx,
                )
            if not self.dir_okay and stat.S_ISDIR(st.st_mode):
                self.fail(
                    "{} '{}' is a directory.".format(
                        self.path_type, filename_to_ui(value)
                    ),
                    param,
                    ctx,
                )
            if self.writable and not os.access(value, os.W_OK):
                self.fail(
                    "{} '{}' is not writable.".format(
                        self.path_type, filename_to_ui(value)
                    ),
                    param,
                    ctx,
                )
            if self.readable and not os.access(value, os.R_OK):
                self.fail(
                    "{} '{}' is not readable.".format(
                        self.path_type, filename_to_ui(value)
                    ),
                    param,
                    ctx,
                )

        return self.coerce_path_result(rv)


class Tuple(CompositeParamType):
    """The default behavior of Click is to apply a type on a value directly.
    This works well in most cases, except for when `nargs` is set to a fixed
    count and different types should be used for different items.  In this
    case the :class:`Tuple` type can be used.  This type can only be used
    if `nargs` is set to a fixed number.

    For more information see :ref:`tuple-type`.

    This can be selected by using a Python tuple literal as a type.

    :param types: a list of types that should be used for the tuple items.
    """

    def __init__(self, types):
        self.types = [convert_type(ty) for ty in types]

    @property
    def name(self):
        return "<{}>".format(" ".join(ty.name for ty in self.types))

    @property
    def arity(self):
        return len(self.types)

    def convert(self, value, param, ctx):
        if len(value) != len(self.types):
            raise TypeError(
                "It would appear that nargs is set to conflict with the"
                " composite type arity."
            )
        return tuple(ty(x, param, ctx) for ty, x in zip(self.types, value))


def convert_type(ty, default=None):
    """Converts a callable or python type into the most appropriate
    param type.
    """
    guessed_type = False
    if ty is None and default is not None:
        if isinstance(default, tuple):
            ty = tuple(map(type, default))
        else:
            ty = type(default)
        guessed_type = True

    if isinstance(ty, tuple):
        return Tuple(ty)
    if isinstance(ty, ParamType):
        return ty
    if ty is text_type or ty is str or ty is None:
        return STRING
    if ty is int:
        return INT
    # Booleans are only okay if not guessed.  This is done because for
    # flags the default value is actually a bit of a lie in that it
    # indicates which of the flags is the one we want.  See get_default()
    # for more information.
    if ty is bool and not guessed_type:
        return BOOL
    if ty is float:
        return FLOAT
    if guessed_type:
        return STRING

    # Catch a common mistake
    if __debug__:
        try:
            if issubclass(ty, ParamType):
                raise AssertionError(
                    "Attempted to use an uninstantiated parameter type ({}).".format(ty)
                )
        except TypeError:
            pass
    return FuncParamType(ty)


#: A dummy parameter type that just does nothing.  From a user's
#: perspective this appears to just be the same as `STRING` but internally
#: no string conversion takes place.  This is necessary to achieve the
#: same bytes/unicode behavior on Python 2/3 in situations where you want
#: to not convert argument types.  This is usually useful when working
#: with file paths as they can appear in bytes and unicode.
#:
#: For path related uses the :class:`Path` type is a better choice but
#: there are situations where an unprocessed type is useful which is why
#: it is is provided.
#:
#: .. versionadded:: 4.0
UNPROCESSED = UnprocessedParamType()

#: A unicode string parameter type which is the implicit default.  This
#: can also be selected by using ``str`` as type.
STRING = StringParamType()

#: An integer parameter.  This can also be selected by using ``int`` as
#: type.
INT = IntParamType()

#: A floating point value parameter.  This can also be selected by using
#: ``float`` as type.
FLOAT = FloatParamType()

#: A boolean parameter.  This is the default for boolean flags.  This can
#: also be selected by using ``bool`` as a type.
BOOL = BoolParamType()

#: A UUID parameter.
UUID = UUIDParameterType()
