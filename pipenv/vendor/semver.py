"""
Python helper for Semantic Versioning (http://semver.org/)
"""

import collections
import re


__version__ = '2.8.1'
__author__ = 'Kostiantyn Rybnikov'
__author_email__ = 'k-bx@k-bx.com'
__maintainer__ = 'Sebastien Celles'
__maintainer_email__ = "s.celles@gmail.com"

_REGEX = re.compile(
        r"""
        ^
        (?P<major>(?:0|[1-9][0-9]*))
        \.
        (?P<minor>(?:0|[1-9][0-9]*))
        \.
        (?P<patch>(?:0|[1-9][0-9]*))
        (\-(?P<prerelease>
            (?:0|[1-9A-Za-z-][0-9A-Za-z-]*)
            (\.(?:0|[1-9A-Za-z-][0-9A-Za-z-]*))*
        ))?
        (\+(?P<build>
            [0-9A-Za-z-]+
            (\.[0-9A-Za-z-]+)*
        ))?
        $
        """, re.VERBOSE)

_LAST_NUMBER = re.compile(r'(?:[^\d]*(\d+)[^\d]*)+')

if not hasattr(__builtins__, 'cmp'):
    def cmp(a, b):
        return (a > b) - (a < b)


def parse(version):
    """Parse version to major, minor, patch, pre-release, build parts.

    :param version: version string
    :return: dictionary with the keys 'build', 'major', 'minor', 'patch',
             and 'prerelease'. The prerelease or build keys can be None
             if not provided
    :rtype: dict

    >>> import semver
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
    match = _REGEX.match(version)
    if match is None:
        raise ValueError('%s is not valid SemVer string' % version)

    version_parts = match.groupdict()

    version_parts['major'] = int(version_parts['major'])
    version_parts['minor'] = int(version_parts['minor'])
    version_parts['patch'] = int(version_parts['patch'])

    return version_parts


class VersionInfo(object):
    """
    :param int major: version when you make incompatible API changes.
    :param int minor: version when you add functionality in
                      a backwards-compatible manner.
    :param int patch: version when you make backwards-compatible bug fixes.
    :param str prerelease: an optional prerelease string
    :param str build: an optional build string
    """
    __slots__ = ('_major', '_minor', '_patch', '_prerelease', '_build')

    def __init__(self, major, minor, patch, prerelease=None, build=None):
        self._major = major
        self._minor = minor
        self._patch = patch
        self._prerelease = prerelease
        self._build = build

    @property
    def major(self):
        return self._major

    @property
    def minor(self):
        return self._minor

    @property
    def patch(self):
        return self._patch

    @property
    def prerelease(self):
        return self._prerelease

    @property
    def build(self):
        return self._build

    def _astuple(self):
        return (self.major, self.minor, self.patch,
                self.prerelease, self.build)

    def _asdict(self):
        return collections.OrderedDict((
            ("major", self.major),
            ("minor", self.minor),
            ("patch", self.patch),
            ("prerelease", self.prerelease),
            ("build", self.build)
        ))

    def __eq__(self, other):
        if not isinstance(other, (VersionInfo, dict)):
            return NotImplemented
        return _compare_by_keys(self._asdict(), _to_dict(other)) == 0

    def __ne__(self, other):
        if not isinstance(other, (VersionInfo, dict)):
            return NotImplemented
        return _compare_by_keys(self._asdict(), _to_dict(other)) != 0

    def __lt__(self, other):
        if not isinstance(other, (VersionInfo, dict)):
            return NotImplemented
        return _compare_by_keys(self._asdict(), _to_dict(other)) < 0

    def __le__(self, other):
        if not isinstance(other, (VersionInfo, dict)):
            return NotImplemented
        return _compare_by_keys(self._asdict(), _to_dict(other)) <= 0

    def __gt__(self, other):
        if not isinstance(other, (VersionInfo, dict)):
            return NotImplemented
        return _compare_by_keys(self._asdict(), _to_dict(other)) > 0

    def __ge__(self, other):
        if not isinstance(other, (VersionInfo, dict)):
            return NotImplemented
        return _compare_by_keys(self._asdict(), _to_dict(other)) >= 0

    def __repr__(self):
        s = ", ".join("%s=%r" % (key, val)
                      for key, val in self._asdict().items())
        return "VersionInfo(%s)" % s

    def __str__(self):
        return format_version(*(self._astuple()))

    def __hash__(self):
        return hash(self._astuple())

    @staticmethod
    def parse(version):
        """Parse version string to a VersionInfo instance.

        >>> from semver import VersionInfo
        >>> VersionInfo.parse('3.4.5-pre.2+build.4')
        VersionInfo(major=3, minor=4, patch=5, \
prerelease='pre.2', build='build.4')

        :param version: version string
        :return: a :class:`VersionInfo` instance
        :rtype: :class:`VersionInfo`
        """
        return parse_version_info(version)


def _to_dict(obj):
    if isinstance(obj, VersionInfo):
        return obj._asdict()
    return obj


def parse_version_info(version):
    """Parse version string to a VersionInfo instance.

    :param version: version string
    :return: a :class:`VersionInfo` instance
    :rtype: :class:`VersionInfo`

    >>> import semver
    >>> version_info = semver.parse_version_info("3.4.5-pre.2+build.4")
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
    parts = parse(version)
    version_info = VersionInfo(
            parts['major'], parts['minor'], parts['patch'],
            parts['prerelease'], parts['build'])

    return version_info


def _nat_cmp(a, b):
    def convert(text):
        return int(text) if re.match('^[0-9]+$', text) else text

    def split_key(key):
        return [convert(c) for c in key.split('.')]

    def cmp_prerelease_tag(a, b):
        if isinstance(a, int) and isinstance(b, int):
            return cmp(a, b)
        elif isinstance(a, int):
            return -1
        elif isinstance(b, int):
            return 1
        else:
            return cmp(a, b)

    a, b = a or '', b or ''
    a_parts, b_parts = split_key(a), split_key(b)
    for sub_a, sub_b in zip(a_parts, b_parts):
        cmp_result = cmp_prerelease_tag(sub_a, sub_b)
        if cmp_result != 0:
            return cmp_result
    else:
        return cmp(len(a), len(b))


def _compare_by_keys(d1, d2):
    for key in ['major', 'minor', 'patch']:
        v = cmp(d1.get(key), d2.get(key))
        if v:
            return v

    rc1, rc2 = d1.get('prerelease'), d2.get('prerelease')
    rccmp = _nat_cmp(rc1, rc2)

    if not rccmp:
        return 0
    if not rc1:
        return 1
    elif not rc2:
        return -1

    return rccmp


def compare(ver1, ver2):
    """Compare two versions

    :param ver1: version string 1
    :param ver2: version string 2
    :return: The return value is negative if ver1 < ver2,
             zero if ver1 == ver2 and strictly positive if ver1 > ver2
    :rtype: int

    >>> import semver
    >>> semver.compare("1.0.0", "2.0.0")
    -1
    >>> semver.compare("2.0.0", "1.0.0")
    1
    >>> semver.compare("2.0.0", "2.0.0")
    0
    """

    v1, v2 = parse(ver1), parse(ver2)

    return _compare_by_keys(v1, v2)


def match(version, match_expr):
    """Compare two versions through a comparison

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

    >>> import semver
    >>> semver.match("2.0.0", ">=1.0.0")
    True
    >>> semver.match("1.0.0", ">1.0.0")
    False
    """
    prefix = match_expr[:2]
    if prefix in ('>=', '<=', '==', '!='):
        match_version = match_expr[2:]
    elif prefix and prefix[0] in ('>', '<'):
        prefix = prefix[0]
        match_version = match_expr[1:]
    else:
        raise ValueError("match_expr parameter should be in format <op><ver>, "
                         "where <op> is one of "
                         "['<', '>', '==', '<=', '>=', '!=']. "
                         "You provided: %r" % match_expr)

    possibilities_dict = {
        '>': (1,),
        '<': (-1,),
        '==': (0,),
        '!=': (-1, 1),
        '>=': (0, 1),
        '<=': (-1, 0)
    }

    possibilities = possibilities_dict[prefix]
    cmp_res = compare(version, match_version)

    return cmp_res in possibilities


def max_ver(ver1, ver2):
    """Returns the greater version of two versions

    :param ver1: version string 1
    :param ver2: version string 2
    :return: the greater version of the two
    :rtype: :class:`VersionInfo`

    >>> import semver
    >>> semver.max_ver("1.0.0", "2.0.0")
    '2.0.0'
    """
    cmp_res = compare(ver1, ver2)
    if cmp_res == 0 or cmp_res == 1:
        return ver1
    else:
        return ver2


def min_ver(ver1, ver2):
    """Returns the smaller version of two versions

    :param ver1: version string 1
    :param ver2: version string 2
    :return: the smaller version of the two
    :rtype: :class:`VersionInfo`

    >>> import semver
    >>> semver.min_ver("1.0.0", "2.0.0")
    '1.0.0'
    """
    cmp_res = compare(ver1, ver2)
    if cmp_res == 0 or cmp_res == -1:
        return ver1
    else:
        return ver2


def format_version(major, minor, patch, prerelease=None, build=None):
    """Format a version according to the Semantic Versioning specification

    :param str major: the required major part of a version
    :param str minor: the required minor part of a version
    :param str patch: the required patch part of a version
    :param str prerelease: the optional prerelease part of a version
    :param str build: the optional build part of a version
    :return: the formatted string
    :rtype: str

    >>> import semver
    >>> semver.format_version(3, 4, 5, 'pre.2', 'build.4')
    '3.4.5-pre.2+build.4'
    """
    version = "%d.%d.%d" % (major, minor, patch)
    if prerelease is not None:
        version = version + "-%s" % prerelease

    if build is not None:
        version = version + "+%s" % build

    return version


def _increment_string(string):
    """
    Look for the last sequence of number(s) in a string and increment, from:
    http://code.activestate.com/recipes/442460-increment-numbers-in-a-string/#c1
    """
    match = _LAST_NUMBER.search(string)
    if match:
        next_ = str(int(match.group(1)) + 1)
        start, end = match.span(1)
        string = string[:max(end - len(next_), start)] + next_ + string[end:]
    return string


def bump_major(version):
    """Raise the major part of the version

    :param: version string
    :return: the raised version string
    :rtype: str

    >>> import semver
    >>> semver.bump_major("3.4.5")
    '4.0.0'
    """
    verinfo = parse(version)
    return format_version(verinfo['major'] + 1, 0, 0)


def bump_minor(version):
    """Raise the minor part of the version

    :param: version string
    :return: the raised version string
    :rtype: str

    >>> import semver
    >>> semver.bump_minor("3.4.5")
    '3.5.0'
    """
    verinfo = parse(version)
    return format_version(verinfo['major'], verinfo['minor'] + 1, 0)


def bump_patch(version):
    """Raise the patch part of the version

    :param: version string
    :return: the raised version string
    :rtype: str

    >>> import semver
    >>> semver.bump_patch("3.4.5")
    '3.4.6'
    """
    verinfo = parse(version)
    return format_version(verinfo['major'], verinfo['minor'],
                          verinfo['patch'] + 1)


def bump_prerelease(version, token='rc'):
    """Raise the prerelease part of the version

    :param version: version string
    :param token: defaults to 'rc'
    :return: the raised version string
    :rtype: str

    >>> bump_prerelease('3.4.5', 'dev')
    '3.4.5-dev.1'
    """
    verinfo = parse(version)
    verinfo['prerelease'] = _increment_string(
        verinfo['prerelease'] or (token or 'rc') + '.0'
    )
    return format_version(verinfo['major'], verinfo['minor'], verinfo['patch'],
                          verinfo['prerelease'])


def bump_build(version, token='build'):
    """Raise the build part of the version

    :param version: version string
    :param token: defaults to 'build'
    :return: the raised version string
    :rtype: str

    >>> bump_build('3.4.5-rc.1+build.9')
    '3.4.5-rc.1+build.10'
    """
    verinfo = parse(version)
    verinfo['build'] = _increment_string(
        verinfo['build'] or (token or 'build') + '.0'
    )
    return format_version(verinfo['major'], verinfo['minor'], verinfo['patch'],
                          verinfo['prerelease'], verinfo['build'])


def finalize_version(version):
    """Remove any prerelease and build metadata from the version

    :param version: version string
    :return: the finalized version string
    :rtype: str

    >>> finalize_version('1.2.3-rc.5')
    '1.2.3'
    """
    verinfo = parse(version)
    return format_version(verinfo['major'], verinfo['minor'], verinfo['patch'])


if __name__ == "__main__":
    import doctest
    doctest.testmod()
