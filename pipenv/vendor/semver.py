"""Python helper for Semantic Versioning (http://semver.org/)"""
from __future__ import print_function

import argparse
import collections
from functools import wraps, partial
import inspect
import re
import sys
import warnings


PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3


__version__ = "2.13.0"
__author__ = "Kostiantyn Rybnikov"
__author_email__ = "k-bx@k-bx.com"
__maintainer__ = ["Sebastien Celles", "Tom Schraitle"]
__maintainer_email__ = "s.celles@gmail.com"

#: Our public interface
__all__ = (
    #
    # Module level function:
    "bump_build",
    "bump_major",
    "bump_minor",
    "bump_patch",
    "bump_prerelease",
    "compare",
    "deprecated",
    "finalize_version",
    "format_version",
    "match",
    "max_ver",
    "min_ver",
    "parse",
    "parse_version_info",
    "replace",
    #
    # CLI interface
    "cmd_bump",
    "cmd_check",
    "cmd_compare",
    "createparser",
    "main",
    "process",
    #
    # Constants and classes
    "SEMVER_SPEC_VERSION",
    "VersionInfo",
)

#: Contains the implemented semver.org version of the spec
SEMVER_SPEC_VERSION = "2.0.0"


if not hasattr(__builtins__, "cmp"):

    def cmp(a, b):
        """Return negative if a<b, zero if a==b, positive if a>b."""
        return (a > b) - (a < b)


if PY3:  # pragma: no cover
    string_types = str, bytes
    text_type = str
    binary_type = bytes

    def b(s):
        return s.encode("latin-1")

    def u(s):
        return s


else:  # pragma: no cover
    string_types = unicode, str
    text_type = unicode
    binary_type = str

    def b(s):
        return s

    # Workaround for standalone backslash
    def u(s):
        return unicode(s.replace(r"\\", r"\\\\"), "unicode_escape")


def ensure_str(s, encoding="utf-8", errors="strict"):
    # Taken from six project
    """
    Coerce *s* to `str`.

    For Python 2:
      - `unicode` -> encoded to `str`
      - `str` -> `str`

    For Python 3:
      - `str` -> `str`
      - `bytes` -> decoded to `str`
    """
    if not isinstance(s, (text_type, binary_type)):
        raise TypeError("not expecting type '%s'" % type(s))
    if PY2 and isinstance(s, text_type):
        s = s.encode(encoding, errors)
    elif PY3 and isinstance(s, binary_type):
        s = s.decode(encoding, errors)
    return s


def deprecated(func=None, replace=None, version=None, category=DeprecationWarning):
    """
    Decorates a function to output a deprecation warning.

    :param func: the function to decorate (or None)
    :param str replace: the function to replace (use the full qualified
        name like ``semver.VersionInfo.bump_major``.
    :param str version: the first version when this function was deprecated.
    :param category: allow you to specify the deprecation warning class
        of your choice. By default, it's  :class:`DeprecationWarning`, but
        you can choose :class:`PendingDeprecationWarning` or a custom class.
    """

    if func is None:
        return partial(deprecated, replace=replace, version=version, category=category)

    @wraps(func)
    def wrapper(*args, **kwargs):
        msg = ["Function '{m}.{f}' is deprecated."]

        if version:
            msg.append("Deprecated since version {v}. ")
        msg.append("This function will be removed in semver 3.")
        if replace:
            msg.append("Use {r!r} instead.")
        else:
            msg.append("Use the respective 'semver.VersionInfo.{r}' instead.")

        # hasattr is needed for Python2 compatibility:
        f = func.__qualname__ if hasattr(func, "__qualname__") else func.__name__
        r = replace or f

        frame = inspect.currentframe().f_back

        msg = " ".join(msg)
        warnings.warn_explicit(
            msg.format(m=func.__module__, f=f, r=r, v=version),
            category=category,
            filename=inspect.getfile(frame.f_code),
            lineno=frame.f_lineno,
        )
        # As recommended in the Python documentation
        # https://docs.python.org/3/library/inspect.html#the-interpreter-stack
        # better remove the interpreter stack:
        del frame
        return func(*args, **kwargs)

    return wrapper


@deprecated(version="2.10.0")
def parse(version):
    """
    Parse version to major, minor, patch, pre-release, build parts.

    .. deprecated:: 2.10.0
       Use :func:`semver.VersionInfo.parse` instead.

    :param version: version string
    :return: dictionary with the keys 'build', 'major', 'minor', 'patch',
             and 'prerelease'. The prerelease or build keys can be None
             if not provided
    :rtype: dict

    >>> ver = semver.parse('3.4.5-pre.2+build.4')
    >>> ver['major']
    3
    >>> ver['minor']
    4
    >>> ver['patch']
    5
    >>> ver['prerelease']
    'pre.2'
    >>> ver['build']
    'build.4'
    """
    return VersionInfo.parse(version).to_dict()


def comparator(operator):
    """Wrap a VersionInfo binary op method in a type-check."""

    @wraps(operator)
    def wrapper(self, other):
        comparable_types = (VersionInfo, dict, tuple, list, text_type, binary_type)
        if not isinstance(other, comparable_types):
            raise TypeError(
                "other type %r must be in %r" % (type(other), comparable_types)
            )
        return operator(self, other)

    return wrapper


class VersionInfo(object):
    """
    A semver compatible version class.

    :param int major: version when you make incompatible API changes.
    :param int minor: version when you add functionality in
                      a backwards-compatible manner.
    :param int patch: version when you make backwards-compatible bug fixes.
    :param str prerelease: an optional prerelease string
    :param str build: an optional build string
    """

    __slots__ = ("_major", "_minor", "_patch", "_prerelease", "_build")
    #: Regex for number in a prerelease
    _LAST_NUMBER = re.compile(r"(?:[^\d]*(\d+)[^\d]*)+")
    #: Regex for a semver version
    _REGEX = re.compile(
        r"""
            ^
            (?P<major>0|[1-9]\d*)
            \.
            (?P<minor>0|[1-9]\d*)
            \.
            (?P<patch>0|[1-9]\d*)
            (?:-(?P<prerelease>
                (?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)
                (?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*
            ))?
            (?:\+(?P<build>
                [0-9a-zA-Z-]+
                (?:\.[0-9a-zA-Z-]+)*
            ))?
            $
        """,
        re.VERBOSE,
    )

    def __init__(self, major, minor=0, patch=0, prerelease=None, build=None):
        # Build a dictionary of the arguments except prerelease and build
        version_parts = {
            "major": major,
            "minor": minor,
            "patch": patch,
        }

        for name, value in version_parts.items():
            value = int(value)
            version_parts[name] = value
            if value < 0:
                raise ValueError(
                    "{!r} is negative. A version can only be positive.".format(name)
                )

        self._major = version_parts["major"]
        self._minor = version_parts["minor"]
        self._patch = version_parts["patch"]
        self._prerelease = None if prerelease is None else str(prerelease)
        self._build = None if build is None else str(build)

    @property
    def major(self):
        """The major part of a version (read-only)."""
        return self._major

    @major.setter
    def major(self, value):
        raise AttributeError("attribute 'major' is readonly")

    @property
    def minor(self):
        """The minor part of a version (read-only)."""
        return self._minor

    @minor.setter
    def minor(self, value):
        raise AttributeError("attribute 'minor' is readonly")

    @property
    def patch(self):
        """The patch part of a version (read-only)."""
        return self._patch

    @patch.setter
    def patch(self, value):
        raise AttributeError("attribute 'patch' is readonly")

    @property
    def prerelease(self):
        """The prerelease part of a version (read-only)."""
        return self._prerelease

    @prerelease.setter
    def prerelease(self, value):
        raise AttributeError("attribute 'prerelease' is readonly")

    @property
    def build(self):
        """The build part of a version (read-only)."""
        return self._build

    @build.setter
    def build(self, value):
        raise AttributeError("attribute 'build' is readonly")

    def to_tuple(self):
        """
        Convert the VersionInfo object to a tuple.

        .. versionadded:: 2.10.0
           Renamed ``VersionInfo._astuple`` to ``VersionInfo.to_tuple`` to
           make this function available in the public API.

        :return: a tuple with all the parts
        :rtype: tuple

        >>> semver.VersionInfo(5, 3, 1).to_tuple()
        (5, 3, 1, None, None)
        """
        return (self.major, self.minor, self.patch, self.prerelease, self.build)

    def to_dict(self):
        """
        Convert the VersionInfo object to an OrderedDict.

        .. versionadded:: 2.10.0
           Renamed ``VersionInfo._asdict`` to ``VersionInfo.to_dict`` to
           make this function available in the public API.

        :return: an OrderedDict with the keys in the order ``major``, ``minor``,
          ``patch``, ``prerelease``, and ``build``.
        :rtype: :class:`collections.OrderedDict`

        >>> semver.VersionInfo(3, 2, 1).to_dict()
        OrderedDict([('major', 3), ('minor', 2), ('patch', 1), \
('prerelease', None), ('build', None)])
        """
        return collections.OrderedDict(
            (
                ("major", self.major),
                ("minor", self.minor),
                ("patch", self.patch),
                ("prerelease", self.prerelease),
                ("build", self.build),
            )
        )

    # For compatibility reasons:
    @deprecated(replace="semver.VersionInfo.to_tuple", version="2.10.0")
    def _astuple(self):
        return self.to_tuple()  # pragma: no cover

    _astuple.__doc__ = to_tuple.__doc__

    @deprecated(replace="semver.VersionInfo.to_dict", version="2.10.0")
    def _asdict(self):
        return self.to_dict()  # pragma: no cover

    _asdict.__doc__ = to_dict.__doc__

    def __iter__(self):
        """Implement iter(self)."""
        # As long as we support Py2.7, we can't use the "yield from" syntax
        for v in self.to_tuple():
            yield v

    @staticmethod
    def _increment_string(string):
        """
        Look for the last sequence of number(s) in a string and increment.

        :param str string: the string to search for.
        :return: the incremented string

        Source:
        http://code.activestate.com/recipes/442460-increment-numbers-in-a-string/#c1
        """
        match = VersionInfo._LAST_NUMBER.search(string)
        if match:
            next_ = str(int(match.group(1)) + 1)
            start, end = match.span(1)
            string = string[: max(end - len(next_), start)] + next_ + string[end:]
        return string

    def bump_major(self):
        """
        Raise the major part of the version, return a new object but leave self
        untouched.

        :return: new object with the raised major part
        :rtype: :class:`VersionInfo`

        >>> ver = semver.VersionInfo.parse("3.4.5")
        >>> ver.bump_major()
        VersionInfo(major=4, minor=0, patch=0, prerelease=None, build=None)
        """
        cls = type(self)
        return cls(self._major + 1)

    def bump_minor(self):
        """
        Raise the minor part of the version, return a new object but leave self
        untouched.

        :return: new object with the raised minor part
        :rtype: :class:`VersionInfo`

        >>> ver = semver.VersionInfo.parse("3.4.5")
        >>> ver.bump_minor()
        VersionInfo(major=3, minor=5, patch=0, prerelease=None, build=None)
        """
        cls = type(self)
        return cls(self._major, self._minor + 1)

    def bump_patch(self):
        """
        Raise the patch part of the version, return a new object but leave self
        untouched.

        :return: new object with the raised patch part
        :rtype: :class:`VersionInfo`

        >>> ver = semver.VersionInfo.parse("3.4.5")
        >>> ver.bump_patch()
        VersionInfo(major=3, minor=4, patch=6, prerelease=None, build=None)
        """
        cls = type(self)
        return cls(self._major, self._minor, self._patch + 1)

    def bump_prerelease(self, token="rc"):
        """
        Raise the prerelease part of the version, return a new object but leave
        self untouched.

        :param token: defaults to 'rc'
        :return: new object with the raised prerelease part
        :rtype: :class:`VersionInfo`

        >>> ver = semver.VersionInfo.parse("3.4.5-rc.1")
        >>> ver.bump_prerelease()
        VersionInfo(major=3, minor=4, patch=5, prerelease='rc.2', \
build=None)
        """
        cls = type(self)
        prerelease = cls._increment_string(self._prerelease or (token or "rc") + ".0")
        return cls(self._major, self._minor, self._patch, prerelease)

    def bump_build(self, token="build"):
        """
        Raise the build part of the version, return a new object but leave self
        untouched.

        :param token: defaults to 'build'
        :return: new object with the raised build part
        :rtype: :class:`VersionInfo`

        >>> ver = semver.VersionInfo.parse("3.4.5-rc.1+build.9")
        >>> ver.bump_build()
        VersionInfo(major=3, minor=4, patch=5, prerelease='rc.1', \
build='build.10')
        """
        cls = type(self)
        build = cls._increment_string(self._build or (token or "build") + ".0")
        return cls(self._major, self._minor, self._patch, self._prerelease, build)

    def compare(self, other):
        """
        Compare self with other.

        :param other: the second version (can be string, a dict, tuple/list, or
             a VersionInfo instance)
        :return: The return value is negative if ver1 < ver2,
             zero if ver1 == ver2 and strictly positive if ver1 > ver2
        :rtype: int

        >>> semver.VersionInfo.parse("1.0.0").compare("2.0.0")
        -1
        >>> semver.VersionInfo.parse("2.0.0").compare("1.0.0")
        1
        >>> semver.VersionInfo.parse("2.0.0").compare("2.0.0")
        0
        >>> semver.VersionInfo.parse("2.0.0").compare(dict(major=2, minor=0, patch=0))
        0
        """
        cls = type(self)
        if isinstance(other, string_types):
            other = cls.parse(other)
        elif isinstance(other, dict):
            other = cls(**other)
        elif isinstance(other, (tuple, list)):
            other = cls(*other)
        elif not isinstance(other, cls):
            raise TypeError(
                "Expected str or {} instance, but got {}".format(
                    cls.__name__, type(other)
                )
            )

        v1 = self.to_tuple()[:3]
        v2 = other.to_tuple()[:3]
        x = cmp(v1, v2)
        if x:
            return x

        rc1, rc2 = self.prerelease, other.prerelease
        rccmp = _nat_cmp(rc1, rc2)

        if not rccmp:
            return 0
        if not rc1:
            return 1
        elif not rc2:
            return -1

        return rccmp

    def next_version(self, part, prerelease_token="rc"):
        """
        Determines next version, preserving natural order.

        .. versionadded:: 2.10.0

        This function is taking prereleases into account.
        The "major", "minor", and "patch" raises the respective parts like
        the ``bump_*`` functions. The real difference is using the
        "preprelease" part. It gives you the next patch version of the prerelease,
        for example:

        >>> str(semver.VersionInfo.parse("0.1.4").next_version("prerelease"))
        '0.1.5-rc.1'

        :param part: One of "major", "minor", "patch", or "prerelease"
        :param prerelease_token: prefix string of prerelease, defaults to 'rc'
        :return: new object with the appropriate part raised
        :rtype: :class:`VersionInfo`
        """
        validparts = {
            "major",
            "minor",
            "patch",
            "prerelease",
            # "build", # currently not used
        }
        if part not in validparts:
            raise ValueError(
                "Invalid part. Expected one of {validparts}, but got {part!r}".format(
                    validparts=validparts, part=part
                )
            )
        version = self
        if (version.prerelease or version.build) and (
            part == "patch"
            or (part == "minor" and version.patch == 0)
            or (part == "major" and version.minor == version.patch == 0)
        ):
            return version.replace(prerelease=None, build=None)

        if part in ("major", "minor", "patch"):
            return getattr(version, "bump_" + part)()

        if not version.prerelease:
            version = version.bump_patch()
        return version.bump_prerelease(prerelease_token)

    @comparator
    def __eq__(self, other):
        return self.compare(other) == 0

    @comparator
    def __ne__(self, other):
        return self.compare(other) != 0

    @comparator
    def __lt__(self, other):
        return self.compare(other) < 0

    @comparator
    def __le__(self, other):
        return self.compare(other) <= 0

    @comparator
    def __gt__(self, other):
        return self.compare(other) > 0

    @comparator
    def __ge__(self, other):
        return self.compare(other) >= 0

    def __getitem__(self, index):
        """
        self.__getitem__(index) <==> self[index]

        Implement getitem. If the part requested is undefined, or a part of the
        range requested is undefined, it will throw an index error.
        Negative indices are not supported

        :param Union[int, slice] index: a positive integer indicating the
               offset or a :func:`slice` object
        :raises: IndexError, if index is beyond the range or a part is None
        :return: the requested part of the version at position index

        >>> ver = semver.VersionInfo.parse("3.4.5")
        >>> ver[0], ver[1], ver[2]
        (3, 4, 5)
        """
        if isinstance(index, int):
            index = slice(index, index + 1)

        if (
            isinstance(index, slice)
            and (index.start is not None and index.start < 0)
            or (index.stop is not None and index.stop < 0)
        ):
            raise IndexError("Version index cannot be negative")

        part = tuple(filter(lambda p: p is not None, self.to_tuple()[index]))

        if len(part) == 1:
            part = part[0]
        elif not part:
            raise IndexError("Version part undefined")
        return part

    def __repr__(self):
        s = ", ".join("%s=%r" % (key, val) for key, val in self.to_dict().items())
        return "%s(%s)" % (type(self).__name__, s)

    def __str__(self):
        """str(self)"""
        version = "%d.%d.%d" % (self.major, self.minor, self.patch)
        if self.prerelease:
            version += "-%s" % self.prerelease
        if self.build:
            version += "+%s" % self.build
        return version

    def __hash__(self):
        return hash(self.to_tuple()[:4])

    def finalize_version(self):
        """
        Remove any prerelease and build metadata from the version.

        :return: a new instance with the finalized version string
        :rtype: :class:`VersionInfo`

        >>> str(semver.VersionInfo.parse('1.2.3-rc.5').finalize_version())
        '1.2.3'
        """
        cls = type(self)
        return cls(self.major, self.minor, self.patch)

    def match(self, match_expr):
        """
        Compare self to match a match expression.

        :param str match_expr: operator and version; valid operators are
              <   smaller than
              >   greater than
              >=  greator or equal than
              <=  smaller or equal than
              ==  equal
              !=  not equal
        :return: True if the expression matches the version, otherwise False
        :rtype: bool

        >>> semver.VersionInfo.parse("2.0.0").match(">=1.0.0")
        True
        >>> semver.VersionInfo.parse("1.0.0").match(">1.0.0")
        False
        """
        prefix = match_expr[:2]
        if prefix in (">=", "<=", "==", "!="):
            match_version = match_expr[2:]
        elif prefix and prefix[0] in (">", "<"):
            prefix = prefix[0]
            match_version = match_expr[1:]
        else:
            raise ValueError(
                "match_expr parameter should be in format <op><ver>, "
                "where <op> is one of "
                "['<', '>', '==', '<=', '>=', '!=']. "
                "You provided: %r" % match_expr
            )

        possibilities_dict = {
            ">": (1,),
            "<": (-1,),
            "==": (0,),
            "!=": (-1, 1),
            ">=": (0, 1),
            "<=": (-1, 0),
        }

        possibilities = possibilities_dict[prefix]
        cmp_res = self.compare(match_version)

        return cmp_res in possibilities

    @classmethod
    def parse(cls, version):
        """
        Parse version string to a VersionInfo instance.

        :param version: version string
        :return: a :class:`VersionInfo` instance
        :raises: :class:`ValueError`
        :rtype: :class:`VersionInfo`

        .. versionchanged:: 2.11.0
           Changed method from static to classmethod to
           allow subclasses.

        >>> semver.VersionInfo.parse('3.4.5-pre.2+build.4')
        VersionInfo(major=3, minor=4, patch=5, \
prerelease='pre.2', build='build.4')
        """
        match = cls._REGEX.match(ensure_str(version))
        if match is None:
            raise ValueError("%s is not valid SemVer string" % version)

        version_parts = match.groupdict()

        version_parts["major"] = int(version_parts["major"])
        version_parts["minor"] = int(version_parts["minor"])
        version_parts["patch"] = int(version_parts["patch"])

        return cls(**version_parts)

    def replace(self, **parts):
        """
        Replace one or more parts of a version and return a new
        :class:`VersionInfo` object, but leave self untouched

        .. versionadded:: 2.9.0
           Added :func:`VersionInfo.replace`

        :param dict parts: the parts to be updated. Valid keys are:
          ``major``, ``minor``, ``patch``, ``prerelease``, or ``build``
        :return: the new :class:`VersionInfo` object with the changed
          parts
        :raises: :class:`TypeError`, if ``parts`` contains invalid keys
        """
        version = self.to_dict()
        version.update(parts)
        try:
            return VersionInfo(**version)
        except TypeError:
            unknownkeys = set(parts) - set(self.to_dict())
            error = "replace() got %d unexpected keyword " "argument(s): %s" % (
                len(unknownkeys),
                ", ".join(unknownkeys),
            )
            raise TypeError(error)

    @classmethod
    def isvalid(cls, version):
        """
        Check if the string is a valid semver version.

        .. versionadded:: 2.9.1

        :param str version: the version string to check
        :return: True if the version string is a valid semver version, False
                 otherwise.
        :rtype: bool
        """
        try:
            cls.parse(version)
            return True
        except ValueError:
            return False


@deprecated(replace="semver.VersionInfo.parse", version="2.10.0")
def parse_version_info(version):
    """
    Parse version string to a VersionInfo instance.

    .. deprecated:: 2.10.0
       Use :func:`semver.VersionInfo.parse` instead.

    .. versionadded:: 2.7.2
       Added :func:`semver.parse_version_info`

    :param version: version string
    :return: a :class:`VersionInfo` instance
    :rtype: :class:`VersionInfo`

    >>> version_info = semver.VersionInfo.parse("3.4.5-pre.2+build.4")
    >>> version_info.major
    3
    >>> version_info.minor
    4
    >>> version_info.patch
    5
    >>> version_info.prerelease
    'pre.2'
    >>> version_info.build
    'build.4'
    """
    return VersionInfo.parse(version)


def _nat_cmp(a, b):
    def convert(text):
        return int(text) if re.match("^[0-9]+$", text) else text

    def split_key(key):
        return [convert(c) for c in key.split(".")]

    def cmp_prerelease_tag(a, b):
        if isinstance(a, int) and isinstance(b, int):
            return cmp(a, b)
        elif isinstance(a, int):
            return -1
        elif isinstance(b, int):
            return 1
        else:
            return cmp(a, b)

    a, b = a or "", b or ""
    a_parts, b_parts = split_key(a), split_key(b)
    for sub_a, sub_b in zip(a_parts, b_parts):
        cmp_result = cmp_prerelease_tag(sub_a, sub_b)
        if cmp_result != 0:
            return cmp_result
    else:
        return cmp(len(a), len(b))


@deprecated(version="2.10.0")
def compare(ver1, ver2):
    """
    Compare two versions strings.

    :param ver1: version string 1
    :param ver2: version string 2
    :return: The return value is negative if ver1 < ver2,
             zero if ver1 == ver2 and strictly positive if ver1 > ver2
    :rtype: int

    >>> semver.compare("1.0.0", "2.0.0")
    -1
    >>> semver.compare("2.0.0", "1.0.0")
    1
    >>> semver.compare("2.0.0", "2.0.0")
    0
    """
    v1 = VersionInfo.parse(ver1)
    return v1.compare(ver2)


@deprecated(version="2.10.0")
def match(version, match_expr):
    """
    Compare two versions strings through a comparison.

    :param str version: a version string
    :param str match_expr: operator and version; valid operators are
          <   smaller than
          >   greater than
          >=  greator or equal than
          <=  smaller or equal than
          ==  equal
          !=  not equal
    :return: True if the expression matches the version, otherwise False
    :rtype: bool

    >>> semver.match("2.0.0", ">=1.0.0")
    True
    >>> semver.match("1.0.0", ">1.0.0")
    False
    """
    ver = VersionInfo.parse(version)
    return ver.match(match_expr)


@deprecated(replace="max", version="2.10.2")
def max_ver(ver1, ver2):
    """
    Returns the greater version of two versions strings.

    :param ver1: version string 1
    :param ver2: version string 2
    :return: the greater version of the two
    :rtype: :class:`VersionInfo`

    >>> semver.max_ver("1.0.0", "2.0.0")
    '2.0.0'
    """
    if isinstance(ver1, string_types):
        ver1 = VersionInfo.parse(ver1)
    elif not isinstance(ver1, VersionInfo):
        raise TypeError()
    cmp_res = ver1.compare(ver2)
    if cmp_res >= 0:
        return str(ver1)
    else:
        return ver2


@deprecated(replace="min", version="2.10.2")
def min_ver(ver1, ver2):
    """
    Returns the smaller version of two versions strings.

    :param ver1: version string 1
    :param ver2: version string 2
    :return: the smaller version of the two
    :rtype: :class:`VersionInfo`

    >>> semver.min_ver("1.0.0", "2.0.0")
    '1.0.0'
    """
    ver1 = VersionInfo.parse(ver1)
    cmp_res = ver1.compare(ver2)
    if cmp_res <= 0:
        return str(ver1)
    else:
        return ver2


@deprecated(replace="str(versionobject)", version="2.10.0")
def format_version(major, minor, patch, prerelease=None, build=None):
    """
    Format a version string according to the Semantic Versioning specification.

    .. deprecated:: 2.10.0
       Use ``str(VersionInfo(VERSION)`` instead.

    :param int major: the required major part of a version
    :param int minor: the required minor part of a version
    :param int patch: the required patch part of a version
    :param str prerelease: the optional prerelease part of a version
    :param str build: the optional build part of a version
    :return: the formatted string
    :rtype: str

    >>> semver.format_version(3, 4, 5, 'pre.2', 'build.4')
    '3.4.5-pre.2+build.4'
    """
    return str(VersionInfo(major, minor, patch, prerelease, build))


@deprecated(version="2.10.0")
def bump_major(version):
    """
    Raise the major part of the version string.

    .. deprecated:: 2.10.0
       Use :func:`semver.VersionInfo.bump_major` instead.

    :param: version string
    :return: the raised version string
    :rtype: str

    >>> semver.bump_major("3.4.5")
    '4.0.0'
    """
    return str(VersionInfo.parse(version).bump_major())


@deprecated(version="2.10.0")
def bump_minor(version):
    """
    Raise the minor part of the version string.

    .. deprecated:: 2.10.0
       Use :func:`semver.VersionInfo.bump_minor` instead.

    :param: version string
    :return: the raised version string
    :rtype: str

    >>> semver.bump_minor("3.4.5")
    '3.5.0'
    """
    return str(VersionInfo.parse(version).bump_minor())


@deprecated(version="2.10.0")
def bump_patch(version):
    """
    Raise the patch part of the version string.

    .. deprecated:: 2.10.0
       Use :func:`semver.VersionInfo.bump_patch` instead.

    :param: version string
    :return: the raised version string
    :rtype: str

    >>> semver.bump_patch("3.4.5")
    '3.4.6'
    """
    return str(VersionInfo.parse(version).bump_patch())


@deprecated(version="2.10.0")
def bump_prerelease(version, token="rc"):
    """
    Raise the prerelease part of the version string.

    .. deprecated:: 2.10.0
       Use :func:`semver.VersionInfo.bump_prerelease` instead.

    :param version: version string
    :param token: defaults to 'rc'
    :return: the raised version string
    :rtype: str

    >>> semver.bump_prerelease('3.4.5', 'dev')
    '3.4.5-dev.1'
    """
    return str(VersionInfo.parse(version).bump_prerelease(token))


@deprecated(version="2.10.0")
def bump_build(version, token="build"):
    """
    Raise the build part of the version string.

    .. deprecated:: 2.10.0
       Use :func:`semver.VersionInfo.bump_build` instead.

    :param version: version string
    :param token: defaults to 'build'
    :return: the raised version string
    :rtype: str

    >>> semver.bump_build('3.4.5-rc.1+build.9')
    '3.4.5-rc.1+build.10'
    """
    return str(VersionInfo.parse(version).bump_build(token))


@deprecated(version="2.10.0")
def finalize_version(version):
    """
    Remove any prerelease and build metadata from the version string.

    .. deprecated:: 2.10.0
       Use :func:`semver.VersionInfo.finalize_version` instead.

    .. versionadded:: 2.7.9
       Added :func:`finalize_version`

    :param version: version string
    :return: the finalized version string
    :rtype: str

    >>> semver.finalize_version('1.2.3-rc.5')
    '1.2.3'
    """
    verinfo = VersionInfo.parse(version)
    return str(verinfo.finalize_version())


@deprecated(version="2.10.0")
def replace(version, **parts):
    """
    Replace one or more parts of a version and return the new string.

    .. deprecated:: 2.10.0
       Use :func:`semver.VersionInfo.replace` instead.

    .. versionadded:: 2.9.0
       Added :func:`replace`

    :param str version: the version string to replace
    :param dict parts: the parts to be updated. Valid keys are:
      ``major``, ``minor``, ``patch``, ``prerelease``, or ``build``
    :return: the replaced version string
    :raises: TypeError, if ``parts`` contains invalid keys
    :rtype: str

    >>> import semver
    >>> semver.replace("1.2.3", major=2, patch=10)
    '2.2.10'
    """
    return str(VersionInfo.parse(version).replace(**parts))


# ---- CLI
def cmd_bump(args):
    """
    Subcommand: Bumps a version.

    Synopsis: bump <PART> <VERSION>
    <PART> can be major, minor, patch, prerelease, or build

    :param args: The parsed arguments
    :type args: :class:`argparse.Namespace`
    :return: the new, bumped version
    """
    maptable = {
        "major": "bump_major",
        "minor": "bump_minor",
        "patch": "bump_patch",
        "prerelease": "bump_prerelease",
        "build": "bump_build",
    }
    if args.bump is None:
        # When bump is called without arguments,
        # print the help and exit
        args.parser.parse_args(["bump", "-h"])

    ver = VersionInfo.parse(args.version)
    # get the respective method and call it
    func = getattr(ver, maptable[args.bump])
    return str(func())


def cmd_check(args):
    """
    Subcommand: Checks if a string is a valid semver version.

    Synopsis: check <VERSION>

    :param args: The parsed arguments
    :type args: :class:`argparse.Namespace`
    """
    if VersionInfo.isvalid(args.version):
        return None
    raise ValueError("Invalid version %r" % args.version)


def cmd_compare(args):
    """
    Subcommand: Compare two versions

    Synopsis: compare <VERSION1> <VERSION2>

    :param args: The parsed arguments
    :type args: :class:`argparse.Namespace`
    """
    return str(compare(args.version1, args.version2))


def cmd_nextver(args):
    """
    Subcommand: Determines the next version, taking prereleases into account.

    Synopsis: nextver <VERSION> <PART>

    :param args: The parsed arguments
    :type args: :class:`argparse.Namespace`
    """
    version = VersionInfo.parse(args.version)
    return str(version.next_version(args.part))


def createparser():
    """
    Create an :class:`argparse.ArgumentParser` instance.

    :return: parser instance
    :rtype: :class:`argparse.ArgumentParser`
    """
    parser = argparse.ArgumentParser(prog=__package__, description=__doc__)

    parser.add_argument(
        "--version", action="version", version="%(prog)s " + __version__
    )

    s = parser.add_subparsers()
    # create compare subcommand
    parser_compare = s.add_parser("compare", help="Compare two versions")
    parser_compare.set_defaults(func=cmd_compare)
    parser_compare.add_argument("version1", help="First version")
    parser_compare.add_argument("version2", help="Second version")

    # create bump subcommand
    parser_bump = s.add_parser("bump", help="Bumps a version")
    parser_bump.set_defaults(func=cmd_bump)
    sb = parser_bump.add_subparsers(title="Bump commands", dest="bump")

    # Create subparsers for the bump subparser:
    for p in (
        sb.add_parser("major", help="Bump the major part of the version"),
        sb.add_parser("minor", help="Bump the minor part of the version"),
        sb.add_parser("patch", help="Bump the patch part of the version"),
        sb.add_parser("prerelease", help="Bump the prerelease part of the version"),
        sb.add_parser("build", help="Bump the build part of the version"),
    ):
        p.add_argument("version", help="Version to raise")

    # Create the check subcommand
    parser_check = s.add_parser(
        "check", help="Checks if a string is a valid semver version"
    )
    parser_check.set_defaults(func=cmd_check)
    parser_check.add_argument("version", help="Version to check")

    # Create the nextver subcommand
    parser_nextver = s.add_parser(
        "nextver", help="Determines the next version, taking prereleases into account."
    )
    parser_nextver.set_defaults(func=cmd_nextver)
    parser_nextver.add_argument("version", help="Version to raise")
    parser_nextver.add_argument(
        "part", help="One of 'major', 'minor', 'patch', or 'prerelease'"
    )
    return parser


def process(args):
    """
    Process the input from the CLI.

    :param args: The parsed arguments
    :type args: :class:`argparse.Namespace`
    :param parser: the parser instance
    :type parser: :class:`argparse.ArgumentParser`
    :return: result of the selected action
    :rtype: str
    """
    if not hasattr(args, "func"):
        args.parser.print_help()
        raise SystemExit()

    # Call the respective function object:
    return args.func(args)


def main(cliargs=None):
    """
    Entry point for the application script.

    :param list cliargs: Arguments to parse or None (=use :class:`sys.argv`)
    :return: error code
    :rtype: int
    """
    try:
        parser = createparser()
        args = parser.parse_args(args=cliargs)
        # Save parser instance:
        args.parser = parser
        result = process(args)
        if result is not None:
            print(result)
        return 0

    except (ValueError, TypeError) as err:
        print("ERROR", err, file=sys.stderr)
        return 2


if __name__ == "__main__":
    import doctest

    doctest.testmod()
