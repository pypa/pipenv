import os
import re
import string
import sys
from collections import defaultdict
from functools import lru_cache
from itertools import chain, groupby
from pathlib import Path

import pipenv.vendor.tomlkit as tomlkit
from pipenv.vendor.attr import validators
from pipenv.patched.pip._internal.models.link import Link
from pipenv.patched.pip._internal.req.constructors import install_req_from_line
from pipenv.patched.pip._vendor.packaging.markers import InvalidMarker, Marker, Op, Value, Variable
from pipenv.patched.pip._vendor.packaging.requirements import Requirement as PackagingRequirement
from pipenv.patched.pip._vendor.packaging.specifiers import InvalidSpecifier, Specifier, SpecifierSet
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.patched.pip._vendor.packaging.version import parse as parse_version
from pipenv.patched.pip._vendor.pkg_resources import Requirement, get_distribution, safe_name
from pipenv.vendor.plette.models import Package, PackageCollection
from pipenv.vendor.tomlkit.container import Container
from pipenv.vendor.tomlkit.items import AoT, Array, Bool, InlineTable, Item, String, Table
from pipenv.patched.pip._vendor.urllib3 import util as urllib3_util
from pipenv.patched.pip._vendor.urllib3.util import parse_url as urllib3_parse
from pipenv.vendor.vistir.misc import dedup
from pipenv.vendor.vistir.path import is_valid_url

from ..environment import MYPY_RUNNING
from ..utils import SCHEME_LIST, VCS_LIST, is_star

if MYPY_RUNNING:
    from typing import Iterable  # noqa
    from typing import (
        Any,
        AnyStr,
        Dict,
        List,
        Match,
        Optional,
        Set,
        Text,
        Tuple,
        TypeVar,
        Union,
    )

    from pipenv.vendor.attr import _ValidatorType  # noqa
    from pipenv.patched.pip._vendor.packaging.markers import Marker as PkgResourcesMarker
    from pipenv.patched.pip._vendor.packaging.markers import Op as PkgResourcesOp
    from pipenv.patched.pip._vendor.packaging.markers import Value as PkgResourcesValue
    from pipenv.patched.pip._vendor.packaging.markers import Variable as PkgResourcesVariable
    from pipenv.patched.pip._vendor.urllib3.util.url import Url

    _T = TypeVar("_T")
    TMarker = Union[Marker, PkgResourcesMarker]
    TVariable = TypeVar("TVariable", PkgResourcesVariable, Variable)
    TValue = TypeVar("TValue", PkgResourcesValue, Value)
    TOp = TypeVar("TOp", PkgResourcesOp, Op)
    MarkerTuple = Tuple[TVariable, TOp, TValue]
    TRequirement = Union[PackagingRequirement, Requirement]
    STRING_TYPE = Union[bytes, str, Text]
    TOML_DICT_TYPES = Union[Container, Package, PackageCollection, Table, InlineTable]
    S = TypeVar("S", bytes, str, Text)


TOML_DICT_OBJECTS = (Container, Package, Table, InlineTable, PackageCollection)
TOML_DICT_NAMES = [o.__class__.__name__ for o in TOML_DICT_OBJECTS]

HASH_STRING = " --hash={0}"

ALPHA_NUMERIC = r"[{0}{1}]".format(string.ascii_letters, string.digits)
PUNCTUATION = r"[\-_\.]"
ALPHANUM_PUNCTUATION = r"[{0}{1}\-_\.]".format(string.ascii_letters, string.digits)
NAME = r"{0}+{1}*{2}".format(ALPHANUM_PUNCTUATION, PUNCTUATION, ALPHA_NUMERIC)
REF = r"[{0}{1}\-\_\./]".format(string.ascii_letters, string.digits)
EXTRAS = r"(?P<extras>\[{0}(?:,{0})*\])".format(NAME)
NAME_WITH_EXTRAS = r"(?P<name>{0}){1}?".format(NAME, EXTRAS)
NAME_RE = re.compile(NAME_WITH_EXTRAS)
SUBDIR_RE = r"(?:[&#]subdirectory=(?P<subdirectory>.*))"
URL_NAME = r"(?:#egg={0})".format(NAME_WITH_EXTRAS)
REF_RE = r"(?:@(?P<ref>{0}+)?)".format(REF)
PATH_RE = r"(?P<pathsep>[:/])(?P<path>[^ @]+){0}?".format(REF_RE)
PASS_RE = r"(?:(?<=:)(?P<password>[^ ]+))"
AUTH_RE = r"(?:(?P<username>[^ ]+)[:@]{0}?@)".format(PASS_RE)
HOST_RE = r"(?:{0}?(?P<host>[^ ]+?\.?{1}+(?P<port>:\d+)?))?".format(
    AUTH_RE, ALPHA_NUMERIC
)
URL = r"(?P<scheme>[^ ]+://){0}{1}".format(HOST_RE, PATH_RE)
URL_RE = re.compile(r"{0}(?:{1}?{2}?)?".format(URL, URL_NAME, SUBDIR_RE))
DIRECT_URL_RE = re.compile(r"{0}\s?@\s?{1}".format(NAME_WITH_EXTRAS, URL))


def filter_none(k, v):
    # type: (AnyStr, Any) -> bool
    if v:
        return True
    return False


def filter_dict(dict_):
    # type: (Dict[AnyStr, Any]) -> Dict[AnyStr, Any]
    return {k: v for k, v in dict_.items() if filter_none(k, v)}


def optional_instance_of(cls):
    # type: (Any) -> _ValidatorType[Optional[_T]]
    return validators.optional(validators.instance_of(cls))


def create_link(link):
    # type: (AnyStr) -> Link

    if not isinstance(link, str):
        raise TypeError("must provide a string to instantiate a new link")

    return Link(link)


def tomlkit_value_to_python(toml_value):
    # type: (Union[Array, AoT, TOML_DICT_TYPES, Item]) -> Union[List, Dict]
    value_type = type(toml_value).__name__
    if (
        isinstance(toml_value, TOML_DICT_OBJECTS + (dict,))
        or value_type in TOML_DICT_NAMES
    ):
        return tomlkit_dict_to_python(toml_value)
    elif isinstance(toml_value, AoT) or value_type == "AoT":
        return [tomlkit_value_to_python(val) for val in toml_value._body]
    elif isinstance(toml_value, Array) or value_type == "Array":
        return [tomlkit_value_to_python(val) for val in list(toml_value)]
    elif isinstance(toml_value, String) or value_type == "String":
        return "{0!s}".format(toml_value)
    elif isinstance(toml_value, Bool) or value_type == "Bool":
        return toml_value.value
    elif isinstance(toml_value, Item):
        return toml_value.value
    return toml_value


def tomlkit_dict_to_python(toml_dict):
    # type: (TOML_DICT_TYPES) -> Dict
    value_type = type(toml_dict).__name__
    if toml_dict is None:
        raise TypeError("Invalid type NoneType when converting toml dict to python")
    converted = None  # type: Optional[Dict]
    if isinstance(toml_dict, (InlineTable, Table)) or value_type in (
        "InlineTable",
        "Table",
    ):
        converted = toml_dict.value
    elif isinstance(toml_dict, (Package, PackageCollection)) or value_type in (
        "Package, PackageCollection"
    ):
        converted = toml_dict._data
        if isinstance(converted, Container) or type(converted).__name__ == "Container":
            converted = converted.value
    elif isinstance(toml_dict, Container) or value_type == "Container":
        converted = toml_dict.value
    elif isinstance(toml_dict, dict):
        converted = toml_dict.copy()
    else:
        raise TypeError(
            "Invalid type for conversion: expected Container, Dict, or Table, "
            "got {0!r}".format(toml_dict)
        )
    if isinstance(converted, dict):
        return {k: tomlkit_value_to_python(v) for k, v in converted.items()}
    elif isinstance(converted, (TOML_DICT_OBJECTS)) or value_type in TOML_DICT_NAMES:
        return tomlkit_dict_to_python(converted)
    return converted


def get_url_name(url):
    # type: (AnyStr) -> AnyStr
    """Given a url, derive an appropriate name to use in a pipfile.

    :param str url: A url to derive a string from
    :returns: The name of the corresponding pipfile entry
    :rtype: Text
    """
    if not isinstance(url, str):
        raise TypeError("Expected a string, got {0!r}".format(url))
    return urllib3_util.parse_url(url).host


def init_requirement(name):
    # type: (AnyStr) -> TRequirement

    if not isinstance(name, str):
        raise TypeError("must supply a name to generate a requirement")

    req = Requirement.parse(name)
    req.vcs = None
    req.local_file = None
    req.revision = None
    req.path = None
    return req


def extras_to_string(extras):
    # type: (Iterable[S]) -> S
    """Turn a list of extras into a string.

    :param List[str]] extras: a list of extras to format
    :return: A string of extras
    :rtype: str
    """
    if isinstance(extras, str):
        if extras.startswith("["):
            return extras
        else:
            extras = [extras]
    if not extras:
        return ""
    return "[{0}]".format(",".join(sorted(set(extras))))  # type: ignore


def parse_extras(extras_str):
    # type: (AnyStr) -> List[AnyStr]
    """Turn a string of extras into a parsed extras list.

    :param str extras_str: An extras string
    :return: A sorted list of extras
    :rtype: List[str]
    """
    extras = Requirement.parse("fakepkg{0}".format(extras_to_string(extras_str))).extras
    return sorted(dedup([extra.lower() for extra in extras]))


def specs_to_string(specs):
    # type: (List[Union[STRING_TYPE, Specifier]]) -> AnyStr
    """Turn a list of specifier tuples into a string.

    :param List[Union[Specifier, str]] specs: a list of specifiers to format
    :return: A string of specifiers
    :rtype: str
    """

    if specs:
        if isinstance(specs, str):
            return specs
        try:
            extras = ",".join(["".join(spec) for spec in specs])
        except TypeError:
            extras = ",".join(["".join(spec._spec) for spec in specs])  # type: ignore
        return extras
    return ""


def build_vcs_uri(
    vcs,  # type: Optional[S]
    uri,  # type: S
    name=None,  # type: Optional[S]
    ref=None,  # type: Optional[S]
    subdirectory=None,  # type: Optional[S]
    extras=None,  # type: Optional[Iterable[S]]
):
    # type: (...) -> STRING_TYPE
    if extras is None:
        extras = []
    vcs_start = ""
    if vcs is not None:
        vcs_start = "{0}+".format(vcs)
        if not uri.startswith(vcs_start):
            uri = "{0}{1}".format(vcs_start, uri)
    if ref:
        uri = "{0}@{1}".format(uri, ref)
    if name:
        uri = "{0}#egg={1}".format(uri, name)
        if extras:
            extras_string = extras_to_string(extras)
            uri = "{0}{1}".format(uri, extras_string)
    if subdirectory:
        uri = "{0}&subdirectory={1}".format(uri, subdirectory)
    return uri


def _get_parsed_url(url):
    # type: (S) -> Url
    """This is a stand-in function for `urllib3.util.parse_url`

    The original function doesn't handle special characters very well, this simply splits
    out the authentication section, creates the parsed url, then puts the authentication
    section back in, bypassing validation.

    :return: The new, parsed URL object
    :rtype: :class:`~urllib3.util.url.Url`
    """

    try:
        parsed = urllib3_parse(url)
    except ValueError:
        scheme, _, url = url.partition("://")
        auth, _, url = url.rpartition("@")
        url = "{scheme}://{url}".format(scheme=scheme, url=url)
        parsed = urllib3_parse(url)._replace(auth=auth)
    return parsed


def convert_direct_url_to_url(direct_url):
    # type: (AnyStr) -> AnyStr
    """Converts direct URLs to standard, link-style URLs.

    Given a direct url as defined by *PEP 508*, convert to a :class:`Link`
    compatible URL by moving the name and extras into an **egg_fragment**.

    :param str direct_url: A pep-508 compliant direct url.
    :return: A reformatted URL for use with Link objects and :class:`InstallRequirement` objects.
    :rtype: AnyStr
    """
    direct_match = DIRECT_URL_RE.match(direct_url)  # type: Optional[Match]
    if direct_match is None:
        url_match = URL_RE.match(direct_url)
        if url_match or is_valid_url(direct_url):
            return direct_url
    match_dict = (
        {}
    )  # type: Dict[STRING_TYPE, Union[Tuple[STRING_TYPE, ...], STRING_TYPE]]
    if direct_match is not None:
        match_dict = direct_match.groupdict()  # type: ignore
    if not match_dict:
        raise ValueError(
            "Failed converting value to normal URL, is it a direct URL? {0!r}".format(
                direct_url
            )
        )
    url_segments = [match_dict.get(s) for s in ("scheme", "host", "path", "pathsep")]
    url = ""  # type: STRING_TYPE
    url = "".join([s for s in url_segments if s is not None])  # type: ignore
    new_url = build_vcs_uri(
        None,
        url,
        ref=match_dict.get("ref"),
        name=match_dict.get("name"),
        extras=match_dict.get("extras"),
        subdirectory=match_dict.get("subdirectory"),
    )
    return new_url


def convert_url_to_direct_url(url, name=None):
    # type: (AnyStr, Optional[AnyStr]) -> AnyStr
    """Converts normal link-style URLs to direct urls.

    Given a :class:`Link` compatible URL, convert to a direct url as
    defined by *PEP 508* by extracting the name and extras from the **egg_fragment**.

    :param AnyStr url: A :class:`InstallRequirement` compliant URL.
    :param Optiona[AnyStr] name: A name to use in case the supplied URL doesn't provide one.
    :return: A pep-508 compliant direct url.
    :rtype: AnyStr

    :raises ValueError: Raised when the URL can't be parsed or a name can't be found.
    :raises TypeError: When a non-string input is provided.
    """
    if not isinstance(url, str):
        raise TypeError(
            "Expected a string to convert to a direct url, got {0!r}".format(url)
        )
    direct_match = DIRECT_URL_RE.match(url)
    if direct_match:
        return url
    url_match = URL_RE.match(url)
    if url_match is None or not url_match.groupdict():
        raise ValueError("Failed parse a valid URL from {0!r}".format(url))
    match_dict = url_match.groupdict()
    url_segments = [match_dict.get(s) for s in ("scheme", "host", "path", "pathsep")]
    name = match_dict.get("name", name)
    extras = match_dict.get("extras")
    new_url = ""
    if extras and not name:
        url_segments.append(extras)
    elif extras and name:
        new_url = "{0}{1}@ ".format(name, extras)
    else:
        if name is not None:
            new_url = "{0}@ ".format(name)
        else:
            raise ValueError(
                "Failed to construct direct url: "
                "No name could be parsed from {0!r}".format(url)
            )
    if match_dict.get("ref"):
        url_segments.append("@{0}".format(match_dict.get("ref")))
    url = "".join([s for s in url if s is not None])
    url = "{0}{1}".format(new_url, url)
    return url


def get_version(pipfile_entry):
    # type: (Union[STRING_TYPE, Dict[STRING_TYPE, Union[STRING_TYPE, bool, Iterable[STRING_TYPE]]]]) -> STRING_TYPE
    if str(pipfile_entry) == "{}" or is_star(pipfile_entry):
        return ""

    if hasattr(pipfile_entry, "keys") and "version" in pipfile_entry:
        if is_star(pipfile_entry.get("version")):
            return ""
        return pipfile_entry.get("version", "").strip().lstrip("(").rstrip(")")

    if isinstance(pipfile_entry, str):
        return pipfile_entry.strip().lstrip("(").rstrip(")")
    return ""


def strip_extras_markers_from_requirement(req):
    # type: (TRequirement) -> TRequirement
    """Strips extras markers from requirement instances.

    Given a :class:`~packaging.requirements.Requirement` instance with markers defining
    *extra == 'name'*, strip out the extras from the markers and return the cleaned
    requirement

    :param PackagingRequirement req: A packaging requirement to clean
    :return: A cleaned requirement
    :rtype: PackagingRequirement
    """
    if req is None:
        raise TypeError("Must pass in a valid requirement, received {0!r}".format(req))
    if getattr(req, "marker", None) is not None:
        marker = req.marker  # type: TMarker
        marker._markers = _strip_extras_markers(marker._markers)
        if not marker._markers:
            req.marker = None
        else:
            req.marker = marker
    return req


def _strip_extras_markers(marker):
    # type: (Union[MarkerTuple, List[Union[MarkerTuple, str]]]) -> List[Union[MarkerTuple, str]]
    if marker is None or not isinstance(marker, (list, tuple)):
        raise TypeError("Expecting a marker type, received {0!r}".format(marker))
    markers_to_remove = []
    # iterate forwards and generate a list of indexes to remove first, then reverse the
    # list so we can remove the text that normally occurs after (but we will already
    # be past it in the loop)
    for i, marker_list in enumerate(marker):
        if isinstance(marker_list, list):
            cleaned = _strip_extras_markers(marker_list)
            if not cleaned:
                markers_to_remove.append(i)
        elif isinstance(marker_list, tuple) and marker_list[0].value == "extra":
            markers_to_remove.append(i)
    for i in reversed(markers_to_remove):
        del marker[i]
        if i > 0 and marker[i - 1] == "and":
            del marker[i - 1]
    return marker


@lru_cache()
def get_setuptools_version():
    # type: () -> Optional[STRING_TYPE]

    setuptools_dist = get_distribution(Requirement("setuptools"))
    return getattr(setuptools_dist, "version", None)


def get_default_pyproject_backend():
    # type: () -> STRING_TYPE
    st_version = get_setuptools_version()
    if st_version is not None:
        parsed_st_version = parse_version(st_version)
        if parsed_st_version >= parse_version("40.8.0"):
            return "setuptools.build_meta:__legacy__"
    return "setuptools.build_meta"


def get_pyproject(path):
    # type: (Union[STRING_TYPE, Path]) -> Optional[Tuple[List[STRING_TYPE], STRING_TYPE]]
    """Given a base path, look for the corresponding ``pyproject.toml`` file
    and return its build_requires and build_backend.

    :param AnyStr path: The root path of the project, should be a directory (will be truncated)
    :return: A 2 tuple of build requirements and the build backend
    :rtype: Optional[Tuple[List[AnyStr], AnyStr]]
    """
    if not path:
        return

    if not isinstance(path, Path):
        path = Path(path)
    if not path.is_dir():
        path = path.parent
    pp_toml = path.joinpath("pyproject.toml")
    setup_py = path.joinpath("setup.py")
    if not pp_toml.exists():
        if not setup_py.exists():
            return None
        requires = ["setuptools>=40.8", "wheel"]
        backend = get_default_pyproject_backend()
    else:
        pyproject_data = {}
        with open(pp_toml.as_posix(), encoding="utf-8") as fh:
            pyproject_data = tomlkit.loads(fh.read())
        build_system = pyproject_data.get("build-system", None)
        if build_system is None:
            if setup_py.exists():
                requires = ["setuptools>=40.8", "wheel"]
                backend = get_default_pyproject_backend()
            else:
                requires = ["setuptools>=40.8", "wheel"]
                backend = get_default_pyproject_backend()
            build_system = {"requires": requires, "build-backend": backend}
            pyproject_data["build_system"] = build_system
        else:
            requires = build_system.get("requires", ["setuptools>=40.8", "wheel"])
            backend = build_system.get("build-backend", get_default_pyproject_backend())
    return requires, backend


def split_markers_from_line(line):
    # type: (AnyStr) -> Tuple[AnyStr, Optional[AnyStr]]
    """Split markers from a dependency."""
    quote_chars = ["'", '"']
    line_quote = next(
        iter(quote for quote in quote_chars if line.startswith(quote)), None
    )
    if line_quote and line.endswith(line_quote):
        line = line.strip(line_quote)
    marker_sep = " ; "
    markers = None
    if marker_sep in line:
        line, markers = line.split(marker_sep, 1)
        markers = markers.strip() if markers else None
    return line, markers


def split_vcs_method_from_uri(uri):
    # type: (AnyStr) -> Tuple[Optional[STRING_TYPE], STRING_TYPE]
    """Split a vcs+uri formatted uri into (vcs, uri)"""
    vcs_start = "{0}+"
    vcs = next(
        iter([vcs for vcs in VCS_LIST if uri.startswith(vcs_start.format(vcs))]), None
    )
    if vcs:
        vcs, uri = uri.split("+", 1)
    return vcs, uri


def split_ref_from_uri(uri):
    # type: (AnyStr) -> Tuple[AnyStr, Optional[AnyStr]]
    """Given a path or URI, check for a ref and split it from the path if it is
    present, returning a tuple of the original input and the ref or None.

    :param AnyStr uri: The path or URI to split
    :returns: A 2-tuple of the path or URI and the ref
    :rtype: Tuple[AnyStr, Optional[AnyStr]]
    """
    if not isinstance(uri, str):
        raise TypeError("Expected a string, received {0!r}".format(uri))
    parsed = _get_parsed_url(uri)
    path = parsed.path if parsed.path else ""
    scheme = parsed.scheme if parsed.scheme else ""
    ref = None
    schema_is_filelike = scheme in ("", "file")
    if (not schema_is_filelike and "@" in path) or (
        schema_is_filelike and (re.match("^.*@[^/@]*$", path) or path.count("@") >= 2)
    ):
        path, _, ref = path.rpartition("@")
    parsed = parsed._replace(path=path)
    return (parsed.url, ref)


def validate_vcs(instance, attr_, value):
    if value not in VCS_LIST:
        raise ValueError("Invalid vcs {0!r}".format(value))


def validate_path(instance, attr_, value):
    if not os.path.exists(value):
        raise ValueError("Invalid path {0!r}".format(value))


def validate_markers(instance, attr_, value):
    try:
        Marker("{0}{1}".format(attr_.name, value))
    except InvalidMarker:
        raise ValueError("Invalid Marker {0}{1}".format(attr_, value))


def validate_specifiers(instance, attr_, value):
    if value == "":
        return True
    try:
        SpecifierSet(value)
    except (InvalidMarker, InvalidSpecifier):
        raise ValueError("Invalid Specifiers {0}".format(value))


def key_from_ireq(ireq):
    """Get a standardized key for an InstallRequirement."""
    if ireq.req is None and ireq.link is not None:
        return str(ireq.link)
    else:
        return key_from_req(ireq.req)


def key_from_req(req):
    """Get an all-lowercase version of the requirement's name."""
    if hasattr(req, "key"):
        # from pkg_resources, such as installed dists for pip-sync
        key = req.key
    else:
        # from packaging, such as install requirements from requirements.txt
        key = req.name

    key = key.replace("_", "-").lower()
    return key


def _requirement_to_str_lowercase_name(requirement):
    """Formats a packaging.requirements.Requirement with a lowercase name.

    This is simply a copy of
    https://github.com/pypa/packaging/blob/16.8/packaging/requirements.py#L109-L124
    modified to lowercase the dependency name.

    Previously, we were invoking the original Requirement.__str__ method and
    lower-casing the entire result, which would lowercase the name, *and* other,
    important stuff that should not be lower-cased (such as the marker). See
    this issue for more information: https://github.com/pypa/pipenv/issues/2113.
    """
    parts = [requirement.name.lower()]

    if requirement.extras:
        parts.append("[{0}]".format(",".join(sorted(requirement.extras))))

    if requirement.specifier:
        parts.append(str(requirement.specifier))

    if requirement.url:
        parts.append("@ {0}".format(requirement.url))

    if requirement.marker:
        parts.append(" ; {0}".format(requirement.marker))

    return "".join(parts)


def format_requirement(ireq):
    """Formats an `InstallRequirement` instance as a string.

    Generic formatter for pretty printing InstallRequirements to the terminal
    in a less verbose way than using its `__str__` method.

    :param :class:`InstallRequirement` ireq: A pip **InstallRequirement** instance.
    :return: A formatted string for prettyprinting
    :rtype: str
    """
    if ireq.editable:
        line = "-e {}".format(ireq.link)
    else:
        line = _requirement_to_str_lowercase_name(ireq.req)

    if str(ireq.req.marker) != str(ireq.markers):
        if not ireq.req.marker:
            line = "{} ; {}".format(line, ireq.markers)
        else:
            name, markers = line.split(";", 1)
            markers = markers.strip()
            line = "{} ; ({}) and ({})".format(name, markers, ireq.markers)

    return line


def format_specifier(ireq):
    """Generic formatter for pretty printing specifiers.

    Pretty-prints specifiers from InstallRequirements for output to terminal.

    :param :class:`InstallRequirement` ireq: A pip **InstallRequirement** instance.
    :return: A string of specifiers in the given install requirement or <any>
    :rtype: str
    """
    # TODO: Ideally, this is carried over to the pip library itself
    specs = ireq.specifier._specs if ireq.req is not None else []
    specs = sorted(specs, key=lambda x: x._spec[1])
    return ",".join(str(s) for s in specs) or "<any>"


def get_pinned_version(ireq):
    """Get the pinned version of an InstallRequirement.

    An InstallRequirement is considered pinned if:

    - Is not editable
    - It has exactly one specifier
    - That specifier is "=="
    - The version does not contain a wildcard

    Examples:
        django==1.8   # pinned
        django>1.8    # NOT pinned
        django~=1.8   # NOT pinned
        django==1.*   # NOT pinned

    Raises `TypeError` if the input is not a valid InstallRequirement, or
    `ValueError` if the InstallRequirement is not pinned.
    """
    try:
        specifier = ireq.specifier
    except AttributeError:
        raise TypeError("Expected InstallRequirement, not {}".format(type(ireq).__name__))

    if getattr(ireq, "editable", False):
        raise ValueError("InstallRequirement is editable")
    if not specifier:
        raise ValueError("InstallRequirement has no version specification")
    if len(specifier._specs) != 1:
        raise ValueError("InstallRequirement has multiple specifications")

    op, version = next(iter(specifier._specs))._spec
    if op not in ("==", "===") or version.endswith(".*"):
        raise ValueError("InstallRequirement not pinned (is {0!r})".format(op + version))

    return version


def is_pinned_requirement(ireq):
    """Returns whether an InstallRequirement is a "pinned" requirement.

    An InstallRequirement is considered pinned if:

    - Is not editable
    - It has exactly one specifier
    - That specifier is "=="
    - The version does not contain a wildcard

    Examples:
        django==1.8   # pinned
        django>1.8    # NOT pinned
        django~=1.8   # NOT pinned
        django==1.*   # NOT pinned
    """

    try:
        get_pinned_version(ireq)
    except (TypeError, ValueError):
        return False
    return True


def as_tuple(ireq):
    """Pulls out the (name: str, version:str, extras:(str)) tuple from the
    pinned InstallRequirement."""

    if not is_pinned_requirement(ireq):
        raise TypeError("Expected a pinned InstallRequirement, got {}".format(ireq))

    name = key_from_req(ireq.req)
    version = next(iter(ireq.specifier._specs))._spec[1]
    extras = tuple(sorted(ireq.extras))
    return name, version, extras


def full_groupby(iterable, key=None):
    """Like groupby(), but sorts the input on the group key first."""

    return groupby(sorted(iterable, key=key), key=key)


def flat_map(fn, collection):
    """Map a function over a collection and flatten the result by one-level."""

    return chain.from_iterable(map(fn, collection))


def lookup_table(values, key=None, keyval=None, unique=False, use_lists=False):
    """Builds a dict-based lookup table (index) elegantly.

    Supports building normal and unique lookup tables.  For example:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'], lambda s: s[0]) == {
    ...     'b': {'bar', 'baz'},
    ...     'f': {'foo'},
    ...     'q': {'quux', 'qux'}
    ... }

    For key functions that uniquely identify values, set unique=True:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'], lambda s: s[0], unique=True) == {
    ...     'b': 'baz',
    ...     'f': 'foo',
    ...     'q': 'quux'
    ... }

    The values of the resulting lookup table will be values, not sets.

    For extra power, you can even change the values while building up the LUT.
    To do so, use the `keyval` function instead of the `key` arg:

    >>> assert lookup_table(
    ...     ['foo', 'bar', 'baz', 'qux', 'quux'],
    ...     keyval=lambda s: (s[0], s[1:])) == {
    ...     'b': {'ar', 'az'},
    ...     'f': {'oo'},
    ...     'q': {'uux', 'ux'}
    ... }
    """

    if keyval is None:
        if key is None:
            keyval = lambda v: v
        else:
            keyval = lambda v: (key(v), v)

    if unique:
        return dict(keyval(v) for v in values)

    lut = {}
    for value in values:
        k, v = keyval(value)
        try:
            s = lut[k]
        except KeyError:
            if use_lists:
                s = lut[k] = list()
            else:
                s = lut[k] = set()
        if use_lists:
            s.append(v)
        else:
            s.add(v)
    return dict(lut)


def name_from_req(req):
    """Get the name of the requirement."""
    if hasattr(req, "project_name"):
        # from pkg_resources, such as installed dists for pip-sync
        return req.project_name
    else:
        # from packaging, such as install requirements from requirements.txt
        return req.name


def make_install_requirement(
    name, version=None, extras=None, markers=None, constraint=False
):
    """Generates an :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`.

    Create an InstallRequirement from the supplied metadata.

    :param name: The requirement's name.
    :type name: str
    :param version: The requirement version (must be pinned).
    :type version: str.
    :param extras: The desired extras.
    :type extras: list[str]
    :param markers: The desired markers, without a preceding semicolon.
    :type markers: str
    :param constraint: Whether to flag the requirement as a constraint, defaults to False.
    :param constraint: bool, optional
    :return: A generated InstallRequirement
    :rtype: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
    """
    requirement_string = "{0}".format(name)
    if extras:
        # Sort extras for stability
        extras_string = "[{}]".format(",".join(sorted(extras)))
        requirement_string = "{0}{1}".format(requirement_string, extras_string)
    if version:
        requirement_string = "{0}=={1}".format(requirement_string, str(version))
    if markers:
        requirement_string = "{0} ; {1}".format(requirement_string, str(markers))
    return install_req_from_line(requirement_string, constraint=constraint)


def version_from_ireq(ireq):
    """version_from_ireq Extract the version from a supplied
    :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`

    :param ireq: An InstallRequirement
    :type ireq: :class:`~pipenv.patched.pip._internal.req.req_install.InstallRequirement`
    :return: The version of the InstallRequirement.
    :rtype: str
    """

    return next(iter(ireq.specifier._specs)).version


def _get_requires_python(candidate):
    # type: (Any) -> str
    requires_python = getattr(candidate, "requires_python", None)
    if requires_python is not None:
        link = getattr(candidate, "location", getattr(candidate, "link", None))
        requires_python = getattr(link, "requires_python", None)
    return requires_python


def clean_requires_python(candidates):
    """Get a cleaned list of all the candidates with valid specifiers in the
    `requires_python` attributes."""
    all_candidates = []
    sys_version = ".".join(map(str, sys.version_info[:3]))
    from pipenv.patched.pip._vendor.packaging.version import parse as parse_version

    py_version = parse_version(os.environ.get("PIP_PYTHON_VERSION", sys_version))
    for c in candidates:
        requires_python = _get_requires_python(c)
        if requires_python:
            # Old specifications had people setting this to single digits
            # which is effectively the same as '>=digit,<digit+1'
            if requires_python.isdigit():
                requires_python = ">={0},<{1}".format(
                    requires_python, int(requires_python) + 1
                )
            try:
                specifierset = SpecifierSet(requires_python)
            except InvalidSpecifier:
                continue
            else:
                if not specifierset.contains(py_version):
                    continue
        all_candidates.append(c)
    return all_candidates


def fix_requires_python_marker(requires_python):
    marker_str = ""
    if any(requires_python.startswith(op) for op in Specifier._operators.keys()):
        spec_dict = defaultdict(set)
        # We are checking first if we have  leading specifier operator
        # if not, we can assume we should be doing a == comparison
        specifierset = list(SpecifierSet(requires_python))
        # for multiple specifiers, the correct way to represent that in
        # a specifierset is `Requirement('fakepkg; python_version<"3.0,>=2.6"')`
        marker_key = Variable("python_version")
        for spec in specifierset:
            operator, val = spec._spec
            cleaned_val = Value(val).serialize().replace('"', "")
            spec_dict[Op(operator).serialize()].add(cleaned_val)
        marker_str = " and ".join(
            [
                "{0}{1}'{2}'".format(marker_key.serialize(), op, ",".join(vals))
                for op, vals in spec_dict.items()
            ]
        )
    marker_to_add = PackagingRequirement("fakepkg ; {0}".format(marker_str)).marker
    return marker_to_add


def normalize_name(pkg):
    # type: (AnyStr) -> AnyStr
    """Given a package name, return its normalized, non-canonicalized form.

    :param AnyStr pkg: The name of a package
    :return: A normalized package name
    :rtype: AnyStr
    """

    assert isinstance(pkg, str)
    return pkg.replace("_", "-").lower()


def get_name_variants(pkg):
    # type: (STRING_TYPE) -> Set[STRING_TYPE]
    """Given a packager name, get the variants of its name for both the
    canonicalized and "safe" forms.

    :param AnyStr pkg: The package to lookup
    :returns: A list of names.
    :rtype: Set
    """

    if not isinstance(pkg, str):
        raise TypeError("must provide a string to derive package names")

    pkg = pkg.lower()
    names = {safe_name(pkg), canonicalize_name(pkg), pkg.replace("-", "_")}
    return names


def read_source(path, encoding="utf-8"):
    # type: (S, S) -> S
    """Read a source file and get the contents with proper encoding for Python
    2/3.

    :param AnyStr path: the file path
    :param AnyStr encoding: the encoding that defaults to UTF-8
    :returns: The contents of the source file
    :rtype: AnyStr
    """
    with open(path, "r", encoding=encoding) as fp:
        return fp.read()


def expand_env_variables(line):
    # type: (AnyStr) -> AnyStr
    """Expand the env vars in a line following pip's standard.
    https://pip.pypa.io/en/stable/reference/pip_install/#id10.

    Matches environment variable-style values in '${MY_VARIABLE_1}' with
    the variable name consisting of only uppercase letters, digits or
    the '_'
    """

    def replace_with_env(match):
        value = os.getenv(match.group(1))
        return value if value else match.group()

    return re.sub(r"\$\{([A-Z0-9_]+)\}", replace_with_env, line)
