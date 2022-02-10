# -*- coding=utf-8 -*-
import datetime
import functools
import io
import json
import logging
import operator
import os
import zipfile
from collections import defaultdict
from functools import reduce
from typing import Sequence

import pipenv.vendor.attr as attr
import dateutil.parser
import distlib.metadata
import distlib.wheel
import packaging.version
import pipenv.vendor.requests as requests
import pipenv.vendor.vistir as vistir
from pipenv.vendor.packaging.markers import Marker
from pipenv.vendor.packaging.requirements import Requirement as PackagingRequirement
from pipenv.vendor.packaging.specifiers import Specifier, SpecifierSet
from pipenv.vendor.packaging.tags import Tag

from ..environment import MYPY_RUNNING
from .markers import (
    get_contained_extras,
    get_contained_pyversions,
    get_without_extra,
    get_without_pyversion,
    marker_from_specifier,
    merge_markers,
    normalize_specifier_set,
)
from .requirements import Requirement
from .utils import filter_dict, get_pinned_version, is_pinned_requirement

ch = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
ch.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


if MYPY_RUNNING:
    from typing import (
        Any,
        Callable,
        Dict,
        Generator,
        Generic,
        Iterator,
        List,
        Optional,
        Set,
        Tuple,
        Type,
        TypeVar,
        Union,
    )

    from pipenv.vendor.attr import Attribute  # noqa

    from .setup_info import SetupInfo

    TAttrsClass = TypeVar("TAttrsClass")
    AttrsClass = Generic[TAttrsClass]
    TDigestDict = Dict[str, str]
    TProjectUrls = Dict[str, str]
    TReleaseUrlDict = Dict[str, Union[bool, int, str, TDigestDict]]
    TReleasesList = List[TReleaseUrlDict]
    TReleasesDict = Dict[str, TReleasesList]
    TDownloads = Dict[str, int]
    TPackageInfo = Dict[str, Optional[Union[str, List[str], TDownloads, TProjectUrls]]]
    TPackage = Dict[str, Union[TPackageInfo, int, TReleasesDict, TReleasesList]]


VALID_ALGORITHMS = {
    "sha1": 40,
    "sha3_224": 56,
    "sha512": 128,
    "blake2b": 128,
    "sha256": 64,
    "sha384": 96,
    "blake2s": 64,
    "sha3_256": 64,
    "sha3_512": 128,
    "md5": 32,
    "sha3_384": 96,
    "sha224": 56,
}  # type: Dict[str, int]

PACKAGE_TYPES = {
    "sdist",
    "bdist_wheel",
    "bdist_egg",
    "bdist_dumb",
    "bdist_wininst",
    "bdist_rpm",
    "bdist_msi",
    "bdist_dmg",
}


class PackageEncoder(json.JSONEncoder):
    def default(self, obj):  # noqa:E0202 # noqa:W0221
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        elif isinstance(obj, PackagingRequirement):
            return obj.__dict__
        elif isinstance(obj, set):
            return tuple(obj)
        elif isinstance(obj, (Specifier, SpecifierSet, Marker)):
            return str(obj)
        else:
            return json.JSONEncoder.default(self, obj)


def validate_extras(inst, attrib, value):
    # type: ("Dependency", Attribute, Tuple[str, ...]) -> None
    duplicates = [k for k in value if value.count(k) > 1]
    if duplicates:
        raise ValueError("Found duplicate keys: {0}".format(", ".join(duplicates)))
    return None


def validate_digest(inst, attrib, value):
    # type: ("Digest", Attribute, str) -> None
    expected_length = VALID_ALGORITHMS[inst.algorithm.lower()]
    if len(value) != expected_length:
        raise ValueError(
            "Expected a digest of length {0!s}, got one of length {1!s}".format(
                expected_length, len(value)
            )
        )
    return None


def get_local_wheel_metadata(wheel_file):
    # type: (str) -> Optional[distlib.metadata.Metadata]
    parsed_metadata = None
    with io.open(wheel_file, "rb") as fh:
        with zipfile.ZipFile(fh, mode="r", compression=zipfile.ZIP_DEFLATED) as zf:
            metadata = None
            for fn in zf.namelist():
                if os.path.basename(fn) == "METADATA":
                    metadata = fn
                    break
            if metadata is None:
                raise RuntimeError("No metadata found in wheel: {0}".format(wheel_file))
            with zf.open(metadata, "r") as metadata_fh:
                parsed_metadata = distlib.metadata.Metadata(fileobj=metadata_fh)
    return parsed_metadata


def get_remote_sdist_metadata(line):
    # type: (str) -> SetupInfo
    req = Requirement.from_line(line)
    try:
        _ = req.run_requires()
    except SystemExit:
        raise RuntimeError("Failed to compute metadata for dependency {0}".format(line))
    else:
        return req.line_instance.setup_info


def get_remote_wheel_metadata(whl_file):
    # type: (str) -> Optional[distlib.metadata.Metadata]
    parsed_metadata = None
    data = io.BytesIO()
    with vistir.contextmanagers.open_file(whl_file) as fp:
        for chunk in iter(lambda: fp.read(8096), b""):
            data.write(chunk)
    with zipfile.ZipFile(data, mode="r", compression=zipfile.ZIP_DEFLATED) as zf:
        metadata = None
        for fn in zf.namelist():
            if os.path.basename(fn) == "METADATA":
                metadata = fn
                break
        if metadata is None:
            raise RuntimeError("No metadata found in wheel: {0}".format(whl_file))
        with zf.open(metadata, "r") as metadata_fh:
            parsed_metadata = distlib.metadata.Metadata(fileobj=metadata_fh)
    return parsed_metadata


def create_specifierset(spec=None):
    # type: (Optional[str]) -> SpecifierSet
    if isinstance(spec, SpecifierSet):
        return spec
    elif isinstance(spec, (set, list, tuple)):
        spec = " and ".join(spec)
    if spec is None:
        spec = ""
    return SpecifierSet(spec)


@attr.s(frozen=True, eq=True)
class ExtrasCollection(object):
    #: The name of the extras collection (e.g. 'security')
    name = attr.ib(type=str)
    #: The dependency the collection belongs to
    parent = attr.ib(type="Dependency")
    #: The members of the collection
    dependencies = attr.ib(factory=set)  # type: Set["Dependency"]

    def add_dependency(self, dependency):
        # type: ("Dependency") -> "ExtrasCollection"
        if not isinstance(dependency, Dependency):
            raise TypeError(
                "Expected a Dependency instance, received {0!r}".format(dependency)
            )
        dependencies = self.dependencies.copy()
        dependencies.add(dependency)
        return attr.evolve(self, dependencies=dependencies)


@attr.s(frozen=True, eq=True)
class Dependency(object):
    #: The name of the dependency
    name = attr.ib(type=str)
    #: A requirement instance
    requirement = attr.ib(type=PackagingRequirement, eq=False)
    #: The specifier defined in the dependency definition
    specifier = attr.ib(type=SpecifierSet, converter=create_specifierset, eq=False)
    #: Any extras this dependency declares
    extras = attr.ib(factory=tuple, validator=validate_extras)  # type: Tuple[str, ...]
    #: The name of the extra meta-dependency this one came from (e.g. 'security')
    from_extras = attr.ib(default=None, eq=False)  # type: Optional[str]
    #: The declared specifier set of allowable python versions for this dependency
    python_version = attr.ib(
        default="", type=SpecifierSet, converter=create_specifierset, eq=False
    )
    #: The parent of this dependency (i.e. where it came from)
    parent = attr.ib(default=None)  # type: Optional[Dependency]
    #: The markers for this dependency
    markers = attr.ib(default=None, eq=False)  # type: Optional[Marker]
    _specset_str = attr.ib(default="", type=str)
    _python_version_str = attr.ib(default="", type=str)
    _marker_str = attr.ib(default="", type=str)

    def __str__(self):
        # type: () -> str
        return str(self.requirement)

    def as_line(self):
        # type: () -> str
        line_str = "{0}".format(self.name)
        if self.extras:
            line_str = "{0}[{1}]".format(line_str, ",".join(self.extras))
        if self.specifier:
            line_str = "{0}{1!s}".format(line_str, self.specifier)
        py_version_part = ""
        if self.python_version:
            specifiers = normalize_specifier_set(self.python_version)
            markers = []
            if specifiers is not None:
                markers = [marker_from_specifier(str(s)) for s in specifiers]
            py_version_part = reduce(merge_markers, markers)
        if self.markers:
            line_str = "{0}; {1}".format(line_str, str(self.markers))
            if py_version_part:
                line_str = "{0} and {1}".format(line_str, py_version_part)
        elif py_version_part and not self.markers:
            line_str = "{0}; {1}".format(line_str, py_version_part)
        return line_str

    def pin(self):
        # type: () -> "Package"
        base_package = get_package(self.name)
        sorted_releases = sorted(
            base_package.releases.non_yanked_releases,
            key=operator.attrgetter("parsed_version"),
            reverse=True,
        )
        version = next(
            iter(self.specifier.filter((r.version for r in sorted_releases))), None
        )
        if not version:
            version = next(
                iter(
                    self.specifier.filter(
                        (r.version for r in sorted_releases), prereleases=True
                    )
                ),
                None,
            )
        if not version:
            raise RuntimeError(
                "Failed to resolve {0} ({1!s})".format(self.name, self.specifier)
            )
        match = get_package_version(self.name, str(version))
        return match

    @classmethod
    def from_requirement(cls, req, parent=None):
        # type: (PackagingRequirement, Optional["Dependency"]) -> "Dependency"
        from_extras, marker, python_version = None, None, None
        specset_str, py_version_str, marker_str = "", "", ""
        if req.marker:
            marker = Marker(str(req.marker))
            from_extras = next(iter(list(get_contained_extras(marker))), None)
            python_version = get_contained_pyversions(marker)
            marker = get_without_extra(get_without_pyversion(marker))
            if not str(marker) or not marker or not marker._markers:
                marker = None
            req.marker = marker
            if marker is not None:
                marker_str = str(marker)
        if req.specifier:
            specset_str = str(req.specifier)
        if python_version:
            py_version_str = str(python_version)
        return cls(
            name=req.name,
            specifier=req.specifier,
            extras=tuple(sorted(set(req.extras)))
            if req.extras is not None
            else req.extras,
            requirement=req,
            from_extras=from_extras,
            python_version=python_version,
            markers=marker,
            parent=parent,
            specset_str=specset_str,
            python_version_str=py_version_str,
            marker_str=marker_str,
        )

    @classmethod
    def from_info(cls, info):
        # type: ("PackageInfo") -> "Dependency"
        marker_str = ""
        specset_str, py_version_str = "", ""
        if info.requires_python:
            # XXX: Some markers are improperly formatted -- we already handle most cases
            # XXX: but learned about new broken formats, such as
            # XXX: python_version in "2.6 2.7 3.2 3.3" (note the lack of commas)
            # XXX: as a marker on a dependency of a library called 'pickleshare'
            # XXX: Some packages also have invalid markers with stray characters,
            # XXX: such as 'algoliasearch'
            try:
                marker = marker_from_specifier(info.requires_python)
            except Exception:
                marker_str = ""
            else:
                if not marker or not marker._markers:
                    marker_str = ""
                else:
                    marker_str = "{0!s}".format(marker)
        req_str = "{0}=={1}".format(info.name, info.version)
        if marker_str:
            req_str = "{0}; {1}".format(req_str, marker_str)
        req = PackagingRequirement(req_str)
        requires_python_str = (
            info.requires_python if info.requires_python is not None else ""
        )
        if req.specifier:
            specset_str = str(req.specifier)
        if requires_python_str:
            py_version_str = requires_python_str
        return cls(
            name=info.name,
            specifier=req.specifier,
            extras=tuple(sorted(set(req.extras)))
            if req.extras is not None
            else req.extras,
            requirement=req,
            from_extras=None,
            python_version=SpecifierSet(requires_python_str),
            markers=None,
            parent=None,
            specset_str=specset_str,
            python_version_str=py_version_str,
            marker_str=marker_str,
        )

    @classmethod
    def from_str(cls, depstr, parent=None):
        # type: (str, Optional["Dependency"]) -> "Dependency"
        try:
            req = PackagingRequirement(depstr)
        except Exception:
            raise
        return cls.from_requirement(req, parent=parent)

    def add_parent(self, parent):
        # type: ("Dependency") -> "Dependency"
        return attr.evolve(self, parent=parent)


@attr.s(frozen=True, eq=True)
class Digest(object):
    #: The algorithm declared for the digest, e.g. 'sha256'
    algorithm = attr.ib(
        type=str, validator=attr.validators.in_(VALID_ALGORITHMS.keys()), eq=True
    )
    #: The digest value
    value = attr.ib(type=str, validator=validate_digest, eq=True)

    def __str__(self):
        # type: () -> str
        return "{0}:{1}".format(self.algorithm, self.value)

    @classmethod
    def create(cls, algorithm, value):
        # type: (str, str) -> "Digest"
        return cls(algorithm=algorithm, value=value)

    @classmethod
    def collection_from_dict(cls, digest_dict):
        # type: (TDigestDict) -> List["Digest"]
        return [cls.create(k, v) for k, v in digest_dict.items()]


# XXX: This is necessary because attrs converters can only be functions, not classmethods
def create_digest_collection(digest_dict):
    # type: (TDigestDict) -> List["Digest"]
    return Digest.collection_from_dict(digest_dict)


def instance_check_converter(expected_type=None, converter=None):
    # type: (Optional[Type], Optional[Callable]) -> Callable
    def _converter(val):
        if expected_type is not None and isinstance(val, expected_type):
            return val
        return converter(val)

    return _converter


@attr.s(frozen=True, eq=True)
class ParsedTag(object):
    #: The marker string corresponding to the tag
    marker_string = attr.ib(default=None)  # type: Optional[str]
    #: The python version represented by the tag
    python_version = attr.ib(default=None)  # type: Optional[str]
    #: The platform represented by the tag
    platform_system = attr.ib(default=None)  # type: Optional[str]
    #: the ABI represented by the tag
    abi = attr.ib(default=None)  # type: Optional[str]


def parse_tag(tag):
    # type: (Tag) -> ParsedTag
    """Parse a :class:`~packaging.tags.Tag` instance.

    :param :class:`~packaging.tags.Tag` tag: A tag to parse
    :return: A parsed tag with combined markers, supported platform and python version
    :rtype: :class:`~ParsedTag`
    """
    platform_system = None
    python_version = None
    version = None
    marker_str = ""
    if tag.platform.startswith("macos"):
        platform_system = "Darwin"
    elif tag.platform.startswith("manylinux") or tag.platform.startswith("linux"):
        platform_system = "Linux"
    elif tag.platform.startswith("win32"):
        platform_system = "Windows"
    if platform_system:
        marker_str = 'platform_system == "{}"'.format(platform_system)
    if tag.interpreter:
        version = tag.interpreter[2:]
        py_version_str = ""
        if len(version) == 1:
            py_version_str = ">={}.0,<{}".format(version, str(int(version) + 1))
        elif len(version) > 1 and len(version) <= 3:
            # reverse the existing version so we can add 1 to the first element
            # and re-reverse, generating the new version, e.g. [3, 2, 8] =>
            # [8, 2, 3] => [9, 2, 3] => [3, 2, 9]
            next_version_list = list(reversed(version[:]))
            next_version_list[0] = str(int(next_version_list[0]) + 1)
            next_version = ".".join(list(reversed(next_version_list)))
            version = ".".join(version)
            py_version_str = ">={},<{}".format(version, next_version)
        else:
            py_version_str = "{0}".format(version)
        python_version = marker_from_specifier(py_version_str)
    if python_version:
        if marker_str:
            marker_str = "{0} and {1!s}".format(marker_str, python_version)
        else:
            marker_str = str(python_version)
    return ParsedTag(
        marker_string=marker_str,
        python_version=version,
        platform_system=platform_system,
        abi=tag.abi,
    )


@attr.s(frozen=True, eq=True)
class ReleaseUrl(object):
    #: The MD5 digest of the given release
    md5_digest = attr.ib(type=Digest)
    #: The package type of the url
    packagetype = attr.ib(type=str, validator=attr.validators.in_(PACKAGE_TYPES))
    #: The upload timestamp from the package
    upload_time = attr.ib(
        type=datetime.datetime,
        converter=instance_check_converter(datetime.datetime, dateutil.parser.parse),  # type: ignore
    )
    #: The ISO8601 formatted upload timestamp of the package
    upload_time_iso_8601 = attr.ib(
        type=datetime.datetime,
        converter=instance_check_converter(datetime.datetime, dateutil.parser.parse),  # type: ignore
    )
    #: The size in bytes of the package
    size = attr.ib(type=int)
    #: The URL of the package
    url = attr.ib(type=str)
    #: The digests of the package
    digests = attr.ib(
        converter=instance_check_converter(list, create_digest_collection)  # type: ignore
    )  # type: List[Digest]
    #: The name of the package
    name = attr.ib(type=str, default=None)
    #: The available comments of the given upload
    comment_text = attr.ib(type=str, default="")
    #: Whether the url has been yanked from the server
    yanked = attr.ib(type=bool, default=False)
    #: The number of downloads (deprecated)
    downloads = attr.ib(type=int, default=-1)
    #: The filename of the current upload
    filename = attr.ib(type=str, default="")
    #: Whether the upload has a signature
    has_sig = attr.ib(type=bool, default=False)
    #: The python_version attribute of the upload (e.g. 'source', 'py27', etc)
    python_version = attr.ib(type=str, default="source")
    #: The 'requires_python' restriction on the package
    requires_python = attr.ib(type=str, default=None)
    #: A list of valid aprsed tags from the upload
    tags = attr.ib(factory=list)  # type: List[ParsedTag]

    @property
    def is_wheel(self):
        # type: () -> bool
        return os.path.splitext(self.filename)[-1].lower() == ".whl"

    @property
    def is_sdist(self):
        # type: () -> bool
        return self.python_version == "source"

    @property
    def markers(self):
        # type: () -> Optional[str]
        # TODO: Compare dependencies in parent and add markers for python version
        # TODO: Compare dependencies in parent and add markers for platform
        # XXX: We can't use wheel-based markers until we do it via derived markers by
        # XXX: comparing in the parent (i.e. 'Release' instance or so) and merging
        # XXX: down to the common / minimal set of markers otherwise we wind up
        # XXX: with an unmanageable set and combinatorial explosion
        # if self.is_wheel:
        #     return self.get_markers_from_wheel()
        if self.requires_python:
            return marker_from_specifier(self.requires_python)
        return None

    @property
    def pep508_url(self):
        # type: () -> str
        markers = self.markers
        req_str = "{0} @ {1}#egg={0}".format(self.name, self.url)
        if markers:
            req_str = "{0}; {1}".format(req_str, markers)
        return req_str

    def get_markers_from_wheel(self):
        # type: () -> str
        supported_platforms = []  # type: List[str]
        supported_pyversions = []
        supported_abis = []
        markers = []
        for parsed_tag in self.tags:
            if parsed_tag.marker_string:
                markers.append(Marker(parsed_tag.marker_string))
            if parsed_tag.python_version:
                supported_pyversions.append(parsed_tag.python_version)
            if parsed_tag.abi:
                supported_abis.append(parsed_tag.abi)
        if not (markers or supported_platforms):
            return ""
        if (
            all(pyversion in supported_pyversions for pyversion in ["2", "3"])
            and not supported_platforms
        ):
            marker_line = ""
        else:
            marker_line = " or ".join(["{}".format(str(marker)) for marker in markers])
        return marker_line

    def get_dependencies(self):
        # type: () -> Tuple["ReleaseUrl", Dict[str, Union[List[str], str]]]
        results = {"requires_python": None}
        requires_dist = []  # type: List[str]
        if self.is_wheel:
            metadata = get_remote_wheel_metadata(self.url)
            if metadata is not None:
                requires_dist = metadata.run_requires
                if not self.requires_python:
                    results["requires_python"] = metadata._legacy.get("Requires-Python")
        else:
            try:
                metadata = get_remote_sdist_metadata(self.pep508_url)
            except Exception:
                requires_dist = []
            else:
                requires_dist = [str(v) for v in metadata.requires.values()]
        results["requires_dist"] = requires_dist
        requires_python = getattr(self, "requires_python", results["requires_python"])
        return attr.evolve(self, requires_python=requires_python), results

    @property
    def sha256(self):
        # type: () -> str
        return next(
            iter(digest for digest in self.digests if digest.algorithm == "sha256")
        ).value

    @classmethod
    def create(cls, release_dict, name=None):
        # type: (TReleaseUrlDict, Optional[str]) -> "ReleaseUrl"
        valid_digest_keys = set("{0}_digest".format(k) for k in VALID_ALGORITHMS.keys())
        digest_keys = set(release_dict.keys()) & valid_digest_keys
        creation_kwargs = (
            {}
        )  # type: Dict[str, Union[bool, int, str, Digest, TDigestDict]]
        creation_kwargs = {k: v for k, v in release_dict.items() if k not in digest_keys}
        if name is not None:
            creation_kwargs["name"] = name
        for k in digest_keys:
            digest = release_dict[k]
            if not isinstance(digest, str):
                raise TypeError("Digests must be strings, got {!r}".format(digest))
            creation_kwargs[k] = Digest.create(k.replace("_digest", ""), digest)
        release_url = cls(**filter_dict(creation_kwargs))  # type: ignore
        if release_url.is_wheel:
            supported_tags = [
                parse_tag(Tag(*tag)) for tag in distlib.wheel.Wheel(release_url.url).tags
            ]
            release_url = attr.evolve(release_url, tags=supported_tags)
        return release_url


def create_release_urls_from_list(urls, name=None):
    # type: (Union[TReleasesList, List[ReleaseUrl]], Optional[str]) -> List[ReleaseUrl]
    url_list = []
    for release_dict in urls:
        if isinstance(release_dict, ReleaseUrl):
            if name and not release_dict.name:
                release_dict = attr.evolve(release_dict, name=name)
            url_list.append(release_dict)
            continue
        url_list.append(ReleaseUrl.create(release_dict, name=name))
    return url_list


@attr.s(frozen=True, eq=True)
class ReleaseUrlCollection(Sequence):
    #: A list of release URLs
    urls = attr.ib(converter=create_release_urls_from_list)
    #: the name of the package
    name = attr.ib(default=None)  # type: Optional[str]

    @classmethod
    def create(cls, urls, name=None):
        # type: (TReleasesList, Optional[str]) -> "ReleaseUrlCollection"
        return cls(urls=urls, name=name)

    @property
    def wheels(self):
        # type: () -> Iterator[ReleaseUrl]
        for url in self.urls:
            if not url.is_wheel:
                continue
            yield url

    @property
    def sdists(self):
        # type: () -> Iterator[ReleaseUrl]
        for url in self.urls:
            if not url.is_sdist:
                continue
            yield url

    def __iter__(self):
        # type: () -> Iterator[ReleaseUrl]
        return iter(self.urls)

    def __getitem__(self, key):
        # type: (int) -> ReleaseUrl
        return self.urls.__getitem__(key)

    def __len__(self):
        # type: () -> int
        return len(self.urls)

    @property
    def latest(self):
        # type: () -> Optional[ReleaseUrl]
        if not self.urls:
            return None
        return next(
            iter(sorted(self.urls, key=operator.attrgetter("upload_time"), reverse=True))
        )

    @property
    def latest_timestamp(self):
        # type: () -> Optional[datetime.datetime]
        latest = self.latest
        if latest is not None:
            return latest.upload_time
        return None

    def find_package_type(self, type_):
        # type: (str) -> Optional[ReleaseUrl]
        """Given a package type (e.g. sdist, bdist_wheel), find the matching
        release.

        :param str type_: A package type from :const:`~PACKAGE_TYPES`
        :return: The package from this collection matching that type, if available
        :rtype: Optional[ReleaseUrl]
        """
        if type_ not in PACKAGE_TYPES:
            raise ValueError(
                "Invalid package type: {0}. Expected one of {1}".format(
                    type_, " ".join(PACKAGE_TYPES)
                )
            )
        return next(iter(url for url in self.urls if url.packagetype == type_), None)


def convert_release_urls_to_collection(urls=None, name=None):
    # type: (Optional[TReleasesList], Optional[str]) -> ReleaseUrlCollection
    if urls is None:
        urls = []
    urls = create_release_urls_from_list(urls, name=name)
    return ReleaseUrlCollection.create(urls, name=name)


@attr.s(frozen=True)
class Release(Sequence):
    #: The version of the release
    version = attr.ib(type=str)
    #: The URL collection for the release
    urls = attr.ib(
        converter=instance_check_converter(  # type: ignore
            ReleaseUrlCollection, convert_release_urls_to_collection
        ),
        type=ReleaseUrlCollection,
    )
    #: the name of the package
    name = attr.ib(default=None)  # type: Optional[str]

    def __iter__(self):
        # type: () -> Iterator[ReleaseUrlCollection]
        return iter(self.urls)

    def __getitem__(self, key):
        return self.urls[key]

    def __len__(self):
        # type: () -> int
        return len(self.urls)

    @property
    def yanked(self):
        # type: () -> bool
        if not self.urls:
            return True
        return False

    @property
    def parsed_version(self):
        # type: () -> packaging.version._BaseVersion
        return packaging.version.parse(self.version)

    @property
    def wheels(self):
        # type: () -> Iterator[ReleaseUrl]
        return self.urls.wheels

    @property
    def sdists(self):
        # type: () -> Iterator[ReleaseUrl]
        return self.urls.sdists

    @property
    def latest(self):
        # type: () -> ReleaseUrl
        return self.urls.latest

    @property
    def latest_timestamp(self):
        # type: () -> datetime.datetime
        return self.urls.latest_timestamp

    def to_lockfile(self):
        # type: () -> Dict[str, Union[List[str], str]]
        return {
            "hashes": [str(url.sha256) for url in self.urls if url.sha256 is not None],
            "version": "=={0}".format(self.version),
        }


def get_release(version, urls, name=None):
    # type: (str, TReleasesList, Optional[str]) -> Release
    release_kwargs = {"version": version, "name": name}
    if not isinstance(urls, ReleaseUrlCollection):
        release_kwargs["urls"] = convert_release_urls_to_collection(urls, name=name)
    else:
        release_kwargs["urls"] = urls
    return Release(**release_kwargs)  # type: ignore


def get_releases_from_package(releases, name=None):
    # type: (TReleasesDict, Optional[str]) -> List[Release]
    release_list = []
    for version, urls in releases.items():
        release_list.append(get_release(version, urls, name=name))
    return release_list


@attr.s(frozen=True)
class ReleaseCollection(object):
    releases = attr.ib(
        factory=list,
        converter=instance_check_converter(list, get_releases_from_package),  # type: ignore
    )  # type: List[Release]

    def __iter__(self):
        # type: () -> Iterator[Release]
        return iter(self.releases)

    def __getitem__(self, key):
        # type: (str) -> Release
        result = next(iter(r for r in self.releases if r.version == key), None)
        if result is None:
            raise KeyError(key)
        return result

    def __len__(self):
        # type: () -> int
        return len(self.releases)

    def get_latest_lockfile(self):
        # type: () -> Dict[str, Union[str, List[str]]]
        return self.latest.to_lockfile()

    def wheels(self):
        # type: () -> Iterator[ReleaseUrl]
        for release in self.sort_releases():
            for wheel in release.wheels:
                yield wheel

    def sdists(self):
        # type: () -> Iterator[ReleaseUrl]
        for release in self.sort_releases():
            for sdist in release.sdists:
                yield sdist

    @property
    def non_yanked_releases(self):
        # type: () -> List[Release]
        return list(r for r in self.releases if not r.yanked)

    def sort_releases(self):
        # type: () -> List[Release]
        return sorted(
            self.non_yanked_releases,
            key=operator.attrgetter("latest_timestamp"),
            reverse=True,
        )

    @property
    def latest(self):
        # type: () -> Optional[Release]
        return next(iter(r for r in self.sort_releases() if not r.yanked))

    @classmethod
    def load(cls, releases, name=None):
        # type: (Union[TReleasesDict, List[Release]], Optional[str]) -> "ReleaseCollection"
        if not isinstance(releases, list):
            releases = get_releases_from_package(releases, name=name)
        return cls(releases)


def convert_releases_to_collection(releases, name=None):
    # type: (TReleasesDict, Optional[str]) -> ReleaseCollection
    return ReleaseCollection.load(releases, name=name)


def split_keywords(value):
    # type: (Union[str, List]) -> List[str]
    if value and isinstance(value, str):
        return value.split(",")
    elif isinstance(value, list):
        return value
    return []


def create_dependencies(
    requires_dist,  # type: Optional[List[Dependency]]
    parent=None,  # type: Optional[Dependency]
):
    # type: (...) -> Optional[Set[Dependency]]
    if requires_dist is None:
        return None
    dependencies = set()
    for req in requires_dist:
        if not isinstance(req, Dependency):
            dependencies.add(Dependency.from_str(req, parent=parent))
        else:
            dependencies.add(req)
    return dependencies


@attr.s(frozen=True)
class PackageInfo(object):
    name = attr.ib(type=str)
    version = attr.ib(type=str)
    package_url = attr.ib(type=str)
    summary = attr.ib(type=str, default=None)  # type: Optional[str]
    author = attr.ib(type=str, default=None)  # type: Optional[str]
    keywords = attr.ib(factory=list, converter=split_keywords)  # type: List[str]
    description = attr.ib(type=str, default="")
    download_url = attr.ib(type=str, default="")
    home_page = attr.ib(type=str, default="")
    license = attr.ib(type=str, default="")
    maintainer = attr.ib(type=str, default="")
    maintainer_email = attr.ib(type=str, default="")
    downloads = attr.ib(factory=dict)  # type: Dict[str, int]
    docs_url = attr.ib(default=None)  # type: Optional[str]
    platform = attr.ib(type=str, default="")
    project_url = attr.ib(type=str, default="")
    project_urls = attr.ib(factory=dict)  # type: Dict[str, str]
    requires_python = attr.ib(default=None)  # type: Optional[str]
    requires_dist = attr.ib(factory=list)  # type: List[Dependency]
    release_url = attr.ib(default=None)  # type: Optional[str]
    description_content_type = attr.ib(type=str, default="text/md")
    bugtrack_url = attr.ib(default=None)  # type: str
    classifiers = attr.ib(factory=list)  # type: List[str]
    author_email = attr.ib(default=None)  # type: Optional[str]
    markers = attr.ib(default=None)  # type: Optional[str]
    dependencies = attr.ib(default=None)  # type: Tuple[Dependency]

    @classmethod
    def from_json(cls, info_json):
        # type: (TPackageInfo) -> "PackageInfo"
        return cls(**filter_dict(info_json))  # type: ignore

    def to_dependency(self):
        # type: () -> Dependency
        return Dependency.from_info(self)

    def create_dependencies(self, force=False):
        # type: (bool) -> "PackageInfo"
        """Create values for **self.dependencies**.

        :param bool force: Sets **self.dependencies** to an empty tuple if it would be
            None, defaults to False.
        :return: An updated instance of the current object with **self.dependencies**
            updated accordingly.
        :rtype: :class:`PackageInfo`
        """
        if not self.dependencies and not self.requires_dist:
            if force:
                return attr.evolve(self, dependencies=tuple())
            return self
        self_dependency = self.to_dependency()
        deps = set()
        self_dependencies = tuple() if not self.dependencies else self.dependencies
        for dep in self_dependencies:
            if dep is None:
                continue
            new_dep = dep.add_parent(self_dependency)
            deps.add(new_dep)
        created_deps = create_dependencies(self.requires_dist, parent=self_dependency)
        if created_deps is not None:
            for dep in created_deps:
                if dep is None:
                    continue
                deps.add(dep)
        return attr.evolve(self, dependencies=tuple(sorted(deps)))


def convert_package_info(info_json):
    # type: (Union[TPackageInfo, PackageInfo]) -> PackageInfo
    if isinstance(info_json, PackageInfo):
        return info_json
    return PackageInfo.from_json(info_json)


def add_markers_to_dep(d, marker_str):
    # type: (str, Union[str, Marker]) -> str
    req = PackagingRequirement(d)
    existing_marker = getattr(req, "marker", None)
    if isinstance(marker_str, Marker):
        marker_str = str(marker_str)
    if existing_marker is not None:
        marker_str = str(merge_markers(existing_marker, marker_str))
    if marker_str:
        marker_str = marker_str.replace("'", '"')
        req.marker = Marker(marker_str)
    return str(req)


@attr.s
class Package(object):
    info = attr.ib(type=PackageInfo, converter=convert_package_info)
    last_serial = attr.ib(type=int)
    releases = attr.ib(
        type=ReleaseCollection,
        converter=instance_check_converter(  # type: ignore
            ReleaseCollection, convert_releases_to_collection
        ),
    )
    # XXX: Note: sometimes releases have no urls at the top level (e.g. pyrouge)
    urls = attr.ib(
        type=ReleaseUrlCollection,
        converter=instance_check_converter(  # type: ignore
            ReleaseUrlCollection, convert_release_urls_to_collection
        ),
    )

    @urls.default
    def _get_urls_collection(self):
        return functools.partial(
            convert_release_urls_to_collection, urls=[], name=self.name
        )

    @property
    def name(self):
        # type: () -> str
        return self.info.name

    @property
    def version(self):
        # type: () -> str
        return self.info.version

    @property
    def requirement(self):
        # type: () -> PackagingRequirement
        return self.info.to_dependency().requirement

    @property
    def latest_sdist(self):
        # type: () -> ReleaseUrl
        return next(iter(self.urls.sdists))

    @property
    def latest_wheels(self):
        # type: () -> Iterator[ReleaseUrl]
        for wheel in self.urls.wheels:
            yield wheel

    @property
    def dependencies(self):
        # type: () -> List[Dependency]
        if self.info.dependencies is None and list(self.urls):
            rval = self.get_dependencies()
            return rval.dependencies
        return list(self.info.dependencies)

    def get_dependencies(self):
        # type: () -> "Package"
        urls = []  # type: List[ReleaseUrl]
        deps = set()  # type: Set[str]
        info = self.info
        if info.dependencies is None:
            for url in self.urls:
                try:
                    url, dep_dict = url.get_dependencies()
                except (RuntimeError, TypeError):
                    # This happens if we are parsing `setup.py` and we fail
                    if url.is_sdist:
                        continue
                    else:
                        raise
                markers = url.markers
                dep_list = dep_dict.get("requires_dist", [])
                for dep in dep_list:
                    # XXX: We need to parse these as requirements and "and" the markers
                    # XXX: together because they may contain "extra" markers which we
                    # XXX: will need to parse and remove
                    deps.add(add_markers_to_dep(dep, markers))
                urls.append(url)
            if None in deps:
                deps.remove(None)
            info = attr.evolve(
                self.info, requires_dist=tuple(sorted(deps))
            ).create_dependencies(force=True)
        return attr.evolve(self, info=info, urls=urls)

    @classmethod
    def from_json(cls, package_json):
        # type: (Dict[str, Any]) -> "Package"
        info = convert_package_info(package_json["info"]).create_dependencies()
        releases = convert_releases_to_collection(
            package_json["releases"], name=info.name
        )
        urls = convert_release_urls_to_collection(package_json["urls"], name=info.name)
        return cls(
            info=info,
            releases=releases,
            urls=urls,
            last_serial=package_json["last_serial"],
        )

    def pin_dependencies(self, include_extras=None):
        # type: (Optional[List[str]]) -> Tuple[List["Package"], Dict[str, List[SpecifierSet]]]
        deps = []
        if include_extras:
            include_extras = list(sorted(set(include_extras)))
        else:
            include_extras = []
        constraints = defaultdict(list)
        for dep in self.dependencies:
            if dep.from_extras and dep.from_extras not in include_extras:
                continue
            if dep.specifier:
                constraints[dep.name].append(dep.specifier)
            try:
                pinned = dep.pin()
            except requests.exceptions.HTTPError:
                continue
            deps.append(pinned)
        return deps, constraints

    def get_latest_lockfile(self):
        # type: () -> Dict[str, Dict[str, Union[List[str], str]]]
        lockfile = {}
        constraints = {dep.name: dep.specifier for dep in self.dependencies}
        deps, _ = self.pin_dependencies()
        for dep in deps:
            dep = dep.get_dependencies()
            for sub_dep in dep.dependencies:
                if sub_dep.name not in constraints:
                    logger.info(
                        "Adding {0} (from {1}) {2!s}".format(
                            sub_dep.name, dep.name, sub_dep.specifier
                        )
                    )
                    constraints[sub_dep.name] = sub_dep.specifier
                else:
                    existing = "{0} (from {1}): {2!s} + ".format(
                        sub_dep.name, dep.name, constraints[sub_dep.name]
                    )
                    new_specifier = sub_dep.specifier
                    merged = constraints[sub_dep.name] & new_specifier
                    logger.info(
                        "Updating: {0}{1!s} = {2!s}".format(
                            existing, new_specifier, merged
                        )
                    )
                    constraints[sub_dep.name] = merged

            lockfile.update({dep.info.name: dep.releases.get_latest_lockfile()})
        for sub_dep_name, specset in constraints.items():
            try:
                sub_dep_pkg = get_package(sub_dep_name)
            except requests.exceptions.HTTPError:
                continue
            logger.info("Getting package: {0} ({1!s})".format(sub_dep, specset))
            sorted_releases = list(
                sorted(
                    sub_dep_pkg.releases,
                    key=operator.attrgetter("parsed_version"),
                    reverse=True,
                )
            )
            try:
                version = next(iter(specset.filter((r.version for r in sorted_releases))))
            except StopIteration:
                logger.info(
                    "No version of {0} matches specifier: {1}".format(sub_dep, specset)
                )
                logger.info(
                    "Available versions: {0}".format(
                        " ".join([r.version for r in sorted_releases])
                    )
                )
                raise
            sub_dep_instance = get_package_version(sub_dep_name, version=str(version))
            if sub_dep_instance is None:
                continue
            lockfile.update(
                {
                    sub_dep_instance.info.name: sub_dep_instance.releases.get_latest_lockfile()
                }
            )
            # lockfile.update(dep.get_latest_lockfile())
        lockfile.update({self.info.name: self.releases.get_latest_lockfile()})
        return lockfile

    def as_dict(self):
        # type: () -> Dict[str, Any]
        return json.loads(self.serialize())

    def serialize(self):
        # type: () -> str
        return json.dumps(attr.asdict(self), cls=PackageEncoder, indent=4)


def get_package(name):
    # type: (str) -> Package
    url = "https://pypi.org/pypi/{}/json".format(name)
    with requests.get(url) as r:
        r.raise_for_status()
        result = r.json()
        package = Package.from_json(result)
    return package


def get_package_version(name, version):
    # type: (str, str) -> Package
    url = "https://pypi.org/pypi/{0}/{1}/json".format(name, version)
    with requests.get(url) as r:
        r.raise_for_status()
        result = r.json()
        package = Package.from_json(result)
    return package


def get_package_from_requirement(req):
    # type: (PackagingRequirement) -> Tuple[Package, Set[str]]
    versions = set()
    if is_pinned_requirement(req):
        version = get_pinned_version(req)
        versions.add(version)
        pkg = get_package_version(req.name, version)
    else:
        pkg = get_package(req.name)
        sorted_releases = list(
            sorted(pkg.releases, key=operator.attrgetter("parsed_version"), reverse=True)
        )
        versions = set(req.specifier.filter((r.version for r in sorted_releases)))
        version = next(iter(req.specifier.filter((r.version for r in sorted_releases))))
        if pkg.version not in versions:
            pkg = get_package_version(pkg.name, version)
    return pkg, versions
