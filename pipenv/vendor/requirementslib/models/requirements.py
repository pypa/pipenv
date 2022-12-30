import collections
import copy
import os
import sys
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from sysconfig import get_path
from urllib import parse as urllib_parse
from urllib.parse import unquote

import pipenv.vendor.attr as attr
from pipenv.vendor.pyparsing.core import cached_property
from pipenv.patched.pip._internal.models.link import Link
from pipenv.patched.pip._internal.models.wheel import Wheel
from pipenv.patched.pip._internal.req.constructors import (
    _strip_extras,
    install_req_from_editable,
    install_req_from_line,
)
from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.patched.pip._internal.utils.temp_dir import global_tempdir_manager
from pipenv.patched.pip._internal.utils.urls import path_to_url, url_to_path
from pipenv.patched.pip._vendor.packaging.markers import Marker
from pipenv.patched.pip._vendor.packaging.requirements import Requirement as PackagingRequirement
from pipenv.patched.pip._vendor.packaging.specifiers import (
    InvalidSpecifier,
    LegacySpecifier,
    Specifier,
    SpecifierSet,
)
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.patched.pip._vendor.packaging.version import parse
from pipenv.vendor.vistir.contextmanagers import temp_path
from pipenv.vendor.vistir.misc import dedup
from pipenv.vendor.vistir.path import (
    create_tracked_tempdir,
    get_converted_relative_path,
    is_file_url,
    is_valid_url,
    normalize_path,
)

from ..environment import MYPY_RUNNING
from ..exceptions import RequirementError
from ..utils import (
    VCS_LIST,
    add_ssh_scheme_to_git_uri,
    get_setup_paths,
    is_installable_dir,
    is_installable_file,
    is_vcs,
    strip_ssh_from_git_uri,
)
from .dependencies import AbstractDependency, get_abstract_dependencies, get_dependencies
from .markers import normalize_marker_str
from .setup_info import (
    SetupInfo,
    _prepare_wheel_building_kwargs,
    ast_parse_setup_py,
    get_metadata,
)
from .url import URI
from .utils import (
    DIRECT_URL_RE,
    HASH_STRING,
    build_vcs_uri,
    convert_direct_url_to_url,
    create_link,
    expand_env_variables,
    extras_to_string,
    filter_none,
    format_requirement,
    get_default_pyproject_backend,
    get_pyproject,
    get_version,
    init_requirement,
    is_pinned_requirement,
    make_install_requirement,
    normalize_name,
    parse_extras,
    specs_to_string,
    split_markers_from_line,
    split_ref_from_uri,
    split_vcs_method_from_uri,
    validate_path,
    validate_specifiers,
    validate_vcs,
)

if MYPY_RUNNING:
    from typing import (
        Any,
        AnyStr,
        Dict,
        FrozenSet,
        Generator,
        List,
        Optional,
        Sequence,
        Set,
        Text,
        Tuple,
        TypeVar,
        Union,
    )

    from pipenv.patched.pip._internal.index.package_finder import PackageFinder
    from pipenv.patched.pip._internal.models.candidate import InstallationCandidate

    RequirementType = TypeVar(
        "RequirementType", covariant=True, bound=PackagingRequirement
    )
    F = TypeVar("F", "FileRequirement", "VCSRequirement", covariant=True)
    from urllib.parse import SplitResult

    from .vcs import VCSRepository

    NON_STRING_ITERABLE = Union[List, Set, Tuple]
    STRING_TYPE = Union[str, bytes, Text]
    S = TypeVar("S", bytes, str, Text)
    BASE_TYPES = Union[bool, STRING_TYPE, Tuple[STRING_TYPE, ...]]
    CUSTOM_TYPES = Union[VCSRepository, RequirementType, SetupInfo, "Line"]
    CREATION_ARG_TYPES = Union[BASE_TYPES, Link, CUSTOM_TYPES]
    PIPFILE_ENTRY_TYPE = Union[STRING_TYPE, bool, Tuple[STRING_TYPE], List[STRING_TYPE]]
    PIPFILE_TYPE = Union[STRING_TYPE, Dict[STRING_TYPE, PIPFILE_ENTRY_TYPE]]
    TPIPFILE = Dict[STRING_TYPE, PIPFILE_ENTRY_TYPE]


SPECIFIERS_BY_LENGTH = sorted(list(Specifier._operators.keys()), key=len, reverse=True)


class Line(object):
    def __init__(self, line, extras=None):
        # type: (AnyStr, Optional[Union[List[S], Set[S], Tuple[S, ...]]]) -> None
        self.editable = False  # type: bool
        if line.startswith("-e "):
            line = line[len("-e ") :]
            self.editable = True
        self.extras = ()  # type: Tuple[STRING_TYPE, ...]
        if extras is not None:
            self.extras = tuple(sorted(set(extras)))
        self.line = line  # type: STRING_TYPE
        self.hashes = []  # type: List[STRING_TYPE]
        self.markers = None  # type: Optional[STRING_TYPE]
        self.vcs = None  # type: Optional[STRING_TYPE]
        self.path = None  # type: Optional[STRING_TYPE]
        self.relpath = None  # type: Optional[STRING_TYPE]
        self.uri = None  # type: Optional[STRING_TYPE]
        self._link = None  # type: Optional[Link]
        self.is_local = False  # type: bool
        self._name = None  # type: Optional[STRING_TYPE]
        self._specifier = None  # type: Optional[STRING_TYPE]
        self.parsed_marker = None  # type: Optional[Marker]
        self.preferred_scheme = None  # type: Optional[STRING_TYPE]
        self._requirement = None  # type: Optional[PackagingRequirement]
        self._parsed_url = None  # type: Optional[URI]
        self._setup_cfg = None  # type: Optional[STRING_TYPE]
        self._setup_py = None  # type: Optional[STRING_TYPE]
        self._pyproject_toml = None  # type: Optional[STRING_TYPE]
        self._pyproject_requires = None  # type: Optional[Tuple[STRING_TYPE, ...]]
        self._pyproject_backend = None  # type: Optional[STRING_TYPE]
        self._wheel_kwargs = None  # type: Optional[Dict[STRING_TYPE, STRING_TYPE]]
        self._vcsrepo = None  # type: Optional[VCSRepository]
        self._setup_info = None  # type: Optional[SetupInfo]
        self._ref = None  # type: Optional[STRING_TYPE]
        self._ireq = None  # type: Optional[InstallRequirement]
        self._src_root = None  # type: Optional[STRING_TYPE]
        self.dist = None  # type: Any
        super(Line, self).__init__()
        self.parse()

    def __hash__(self):
        return hash(
            (
                self.editable,
                self.line,
                self.markers,
                tuple(self.extras),
                tuple(self.hashes),
                self.vcs,
                self.uri,
                self.path,
                self.name,
                self._requirement,
            )
        )

    def __repr__(self):
        try:
            return (
                "<Line (editable={self.editable}, name={self._name}, path={self.path}, "
                "uri={self.uri}, extras={self.extras}, markers={self.markers}, vcs={self.vcs}"
                ", specifier={self._specifier}, pyproject={self._pyproject_toml}, "
                "pyproject_requires={self._pyproject_requires}, "
                "pyproject_backend={self._pyproject_backend}, ireq={self._ireq})>".format(
                    self=self
                )
            )
        except Exception:
            return "<Line {0}>".format(self.__dict__.values())

    def __str__(self):
        # type: () -> str
        if self.markers:
            return "{0} ; {1}".format(self.get_line(), self.markers)
        return self.get_line()

    def get_line(
        self, with_prefix=False, with_markers=False, with_hashes=True, as_list=False
    ):
        # type: (bool, bool, bool, bool) -> Union[STRING_TYPE, List[STRING_TYPE]]
        line = self.line
        extras_str = extras_to_string(self.extras)
        with_hashes = False if self.editable or self.is_vcs else with_hashes
        hash_list = ["--hash={0}".format(h) for h in self.hashes]
        if self.is_named:
            line = self.name_and_specifier
        elif self.is_direct_url:
            line = self.link.url
        elif extras_str:
            if self.is_vcs:
                line = self.link.url
                if "git+file:/" in line and "git+file:///" not in line:
                    line = line.replace("git+file:/", "git+file:///")
            elif extras_str not in line:
                line = "{0}{1}".format(line, extras_str)
        # XXX: For using markers on vcs or url requirements, they can be used
        # as normal (i.e. no space between the requirement and the semicolon)
        # and no additional quoting as long as they are not editable requirements
        # HOWEVER, for editable requirements, the requirement+marker must be quoted
        # We do this here for the line-formatted versions, but leave it up to the
        # `Script.parse()` functionality in pipenv, for instance, to handle that
        # in a cross-platform manner for the `as_list` approach since that is how
        # we anticipate this will be used if passing directly to the command line
        # for pip.
        if with_markers and self.markers:
            line = "{0} ; {1}".format(line, self.markers)
            if with_prefix and self.editable and not as_list:
                line = '"{0}"'.format(line)
        if as_list:
            result_list = []
            if with_prefix and self.editable:
                result_list.append("-e")
            result_list.append(line)
            if with_hashes:
                result_list.extend(self.hashes)
            return result_list
        if with_prefix and self.editable:
            line = "-e {0}".format(line)
        if with_hashes and hash_list:
            line = "{0} {1}".format(line, " ".join(hash_list))
        return line

    @property
    def name_and_specifier(self):
        name_str, spec_str = "", ""
        if self.name:
            name_str = "{0}".format(self.name.lower())
            extras_str = extras_to_string(self.extras)
            if extras_str:
                name_str = "{0}{1}".format(name_str, extras_str)
        if self.specifier:
            spec_str = "{0}".format(self.specifier)
        return "{0}{1}".format(name_str, spec_str)

    @classmethod
    def split_hashes(cls, line):
        # type: (S) -> Tuple[S, List[S]]
        if "--hash" not in line:
            return line, []
        split_line = line.split()
        line_parts = []  # type: List[S]
        hashes = []  # type: List[S]
        for part in split_line:
            if part.startswith("--hash"):
                param, _, value = part.partition("=")
                hashes.append(value)
            else:
                line_parts.append(part)
        line = " ".join(line_parts)
        return line, hashes

    @property
    def line_with_prefix(self):
        # type: () -> STRING_TYPE
        return self.get_line(with_prefix=True, with_hashes=False)

    @property
    def line_for_ireq(self):
        # type: () -> STRING_TYPE
        line = ""  # type: STRING_TYPE
        if self.is_file or self.is_remote_url and not self.is_vcs:
            scheme = self.preferred_scheme if self.preferred_scheme is not None else "uri"
            local_line = next(
                iter(
                    [
                        os.path.dirname(os.path.abspath(f))
                        for f in [self.setup_py, self.setup_cfg, self.pyproject_toml]
                        if f is not None
                    ]
                ),
                None,
            )
            if local_line and self.extras:
                local_line = "{0}{1}".format(local_line, extras_to_string(self.extras))
            line = local_line if local_line is not None else self.line
            if scheme == "path":
                if not line and self.base_path is not None:
                    line = os.path.abspath(self.base_path)
            else:
                if DIRECT_URL_RE.match(self.line):
                    uri = URI.parse(self.line)
                    line = uri.full_url
                    self._requirement = init_requirement(self.line)
                    line = convert_direct_url_to_url(self.line)
                else:
                    if self.link:
                        line = self.link.url
                    else:
                        try:
                            uri = URI.parse(line)
                        except ValueError:
                            line = line
                        else:
                            line = uri.base_url
                            self._link = uri.as_link

        if self.editable:
            if not line:
                if self.is_path or self.is_file:
                    if not self.path and self.url is not None:
                        line = url_to_path(self.url)
                    else:
                        line = self.path
                    if self.extras:
                        line = "{0}{1}".format(line, extras_to_string(self.extras))
                else:
                    line = self.link.url
        elif self.is_vcs and not self.editable:
            line = add_ssh_scheme_to_git_uri(self.line)
        if not line:
            line = self.line
        return line

    @property
    def base_path(self):
        # type: () -> Optional[S]
        if not self.link and not self.path:
            self.parse_link()
        if not self.path:
            pass
        path = normalize_path(self.path)
        if os.path.exists(path) and os.path.isdir(path):
            path = path
        elif os.path.exists(path) and os.path.isfile(path):
            path = os.path.dirname(path)
        else:
            path = None
        return path

    @property
    def setup_py(self):
        # type: () -> Optional[STRING_TYPE]
        if self._setup_py is None:
            self.populate_setup_paths()
        return self._setup_py

    @property
    def setup_cfg(self):
        # type: () -> Optional[STRING_TYPE]
        if self._setup_cfg is None:
            self.populate_setup_paths()
        return self._setup_cfg

    @property
    def pyproject_toml(self):
        # type: () -> Optional[STRING_TYPE]
        if self._pyproject_toml is None:
            self.populate_setup_paths()
        return self._pyproject_toml

    @property
    def specifier(self):
        # type: () -> Optional[STRING_TYPE]
        options = [self._specifier]
        for req in (self.ireq, self.requirement):
            if req is not None and getattr(req, "specifier", None):
                options.append(req.specifier)
        specifier = next(
            iter(spec for spec in options if spec is not None), None
        )  # type: Optional[Union[Specifier, SpecifierSet]]
        spec_string = None  # type: Optional[STRING_TYPE]
        if specifier is not None:
            spec_string = specs_to_string(specifier)
        elif (
            specifier is None
            and not self.is_named
            and (self._setup_info is not None and self._setup_info.version)
        ):
            spec_string = "=={0}".format(self._setup_info.version)
        if spec_string:
            self._specifier = spec_string
        return self._specifier

    @specifier.setter
    def specifier(self, spec):
        # type: (str) -> None
        if not spec.startswith("=="):
            spec = "=={0}".format(spec)
        self._specifier = spec
        self.specifiers = SpecifierSet(spec)

    @property
    def specifiers(self):
        # type: () -> Optional[SpecifierSet]
        ireq_needs_specifier = False
        req_needs_specifier = False
        if self.ireq is None or self.ireq.req is None or not self.ireq.req.specifier:
            ireq_needs_specifier = True
        if self.requirement is None or not self.requirement.specifier:
            req_needs_specifier = True
        if any([ireq_needs_specifier, req_needs_specifier]):
            # TODO: Should we include versions for VCS dependencies? IS there a reason not
            # to? For now we are using hashes as the equivalent to pin
            # note: we need versions for direct dependencies at the very least
            if (
                self.is_file
                or self.is_remote_url
                or self.is_path
                or (self.is_vcs and not self.editable)
            ):
                if self.specifier is not None:
                    specifier = self.specifier
                    if not isinstance(specifier, SpecifierSet):
                        specifier = SpecifierSet(specifier)
                    self.specifiers = specifier
                    return specifier
        if self.ireq is not None and self.ireq.req is not None:
            return self.ireq.req.specifier
        elif self.requirement is not None:
            return self.requirement.specifier
        return None

    @specifiers.setter
    def specifiers(self, specifiers):
        # type: (Union[Text, str, SpecifierSet]) -> None
        if not isinstance(specifiers, SpecifierSet):
            if isinstance(specifiers, str):
                specifiers = SpecifierSet(specifiers)
            else:
                raise TypeError("Must pass a string or a SpecifierSet")
        specs = self.get_requirement_specs(specifiers)
        if self.ireq is not None and self._ireq and self._ireq.req is not None:
            self._ireq.req.specifier = specifiers
            self._ireq.req.specs = specs
        if self.requirement is not None:
            self.requirement.specifier = specifiers
            self.requirement.specs = specs

    @classmethod
    def get_requirement_specs(cls, specifierset):
        # type: (SpecifierSet) -> List[Tuple[AnyStr, AnyStr]]
        specs = []
        spec = next(iter(specifierset._specs), None)
        if spec:
            specs.append(spec._spec)
        return specs

    @property
    def requirement(self):
        # type: () -> Optional[RequirementType]
        if self._requirement is None:
            self.parse_requirement()
            if self._requirement is None and self._name is not None:
                self._requirement = init_requirement(canonicalize_name(self.name))
                if self.is_file or self.is_remote_url and self._requirement is not None:
                    self._requirement.url = self.url
        if (
            self._requirement
            and self._requirement.specifier
            and not self._requirement.specs
        ):
            specs = self.get_requirement_specs(self._requirement.specifier)
            self._requirement.specs = specs
        return self._requirement

    def populate_setup_paths(self):
        # type: () -> None
        if not self.link and not self.path:
            self.parse_link()
        if not self.path:
            return
        base_path = self.base_path
        if base_path is None:
            return
        setup_paths = get_setup_paths(
            base_path, subdirectory=self.subdirectory
        )  # type: Dict[STRING_TYPE, Optional[STRING_TYPE]]
        self._setup_py = setup_paths.get("setup_py")
        self._setup_cfg = setup_paths.get("setup_cfg")
        self._pyproject_toml = setup_paths.get("pyproject_toml")

    @property
    def pyproject_requires(self):
        # type: () -> Optional[Tuple[STRING_TYPE, ...]]
        if self._pyproject_requires is None and self.pyproject_toml is not None:
            if self.path is not None:
                pyproject_requires, pyproject_backend = None, None
                pyproject_results = get_pyproject(self.path)  # type: ignore
                if pyproject_results:
                    pyproject_requires, pyproject_backend = pyproject_results
                if pyproject_requires:
                    self._pyproject_requires = tuple(pyproject_requires)
                self._pyproject_backend = pyproject_backend
        return self._pyproject_requires

    @property
    def pyproject_backend(self):
        # type: () -> Optional[STRING_TYPE]
        if self._pyproject_requires is None and self.pyproject_toml is not None:
            pyproject_requires = None  # type: Optional[Sequence[STRING_TYPE]]
            pyproject_backend = None  # type: Optional[STRING_TYPE]
            pyproject_results = get_pyproject(self.path)  # type: ignore
            if pyproject_results:
                pyproject_requires, pyproject_backend = pyproject_results
            if not pyproject_backend and self.setup_cfg is not None:
                setup_dict = SetupInfo.get_setup_cfg(self.setup_cfg)
                pyproject_backend = get_default_pyproject_backend()
                pyproject_requires = setup_dict.get(
                    "build_requires", ["setuptools", "wheel"]
                )  # type: ignore
            if pyproject_requires:
                self._pyproject_requires = tuple(pyproject_requires)
            if pyproject_backend:
                self._pyproject_backend = pyproject_backend
        return self._pyproject_backend

    def parse_hashes(self):
        # type: () -> "Line"
        """Parse hashes from *self.line* and set them on the current object.

        :returns: Self
        :rtype: `:class:~Line`
        """
        line, hashes = self.split_hashes(self.line)
        self.hashes = hashes
        self.line = line
        return self

    def parse_extras(self):
        # type: () -> "Line"
        """
        Parse extras from *self.line* and set them on the current object
        :returns: self
        :rtype: :class:`~Line`
        """
        extras = None
        line = "{0}".format(self.line)
        if any([self.is_vcs, self.is_url, "@" in line]):
            try:
                if self.parsed_url.name:
                    self._name = self.parsed_url.name
                if (
                    self.parsed_url.host
                    and self.parsed_url.path
                    and self.parsed_url.scheme
                ):
                    self.line = self.parsed_url.to_string(
                        escape_password=False,
                        direct=False,
                        strip_ssh=self.parsed_url.is_implicit_ssh,
                    )
            except ValueError:
                self.line, extras = _strip_extras(self.line)
        else:
            self.line, extras = _strip_extras(self.line)
        extras_set = set()  # type: Set[STRING_TYPE]
        if extras is not None:
            extras_set = set(parse_extras(extras))
        if self._name:
            self._name, name_extras = _strip_extras(self._name)
            if name_extras:
                name_extras = set(parse_extras(name_extras))
                extras_set |= name_extras
        if extras_set is not None:
            self.extras = tuple(sorted(extras_set))
        return self

    def get_url(self):
        # type: () -> STRING_TYPE
        """Sets ``self.name`` if given a **PEP-508** style URL."""
        return self.parsed_url.to_string(
            escape_password=False, direct=False, strip_ref=True
        )

    @property
    def name(self):
        # type: () -> Optional[STRING_TYPE]
        if self._name is None:
            self.parse_name()
            if self._name is None and not self.is_named and not self.is_wheel:
                if self.setup_info:
                    self._name = self.setup_info.name
            elif self.is_wheel:
                self._name = self._parse_wheel()
            if not self._name:
                self._name = self.ireq.name
        return self._name

    @name.setter
    def name(self, name):
        # type: (STRING_TYPE) -> None
        self._name = name
        if self._setup_info:
            self._setup_info.name = name
        if self.requirement and self._requirement:
            self._requirement.name = name
        if self.ireq and self._ireq and self._ireq.req:
            self._ireq.req.name = name

    @property
    def url(self):
        # type: () -> Optional[STRING_TYPE]
        try:
            return self.parsed_url.to_string(
                escape_password=False,
                strip_ref=True,
                strip_name=True,
                strip_subdir=True,
                strip_ssh=False,
            )
        except ValueError:
            return None

    @property
    def link(self):
        # type: () -> Link
        if self._link is None:
            self.parse_link()
        return self._link

    @property
    def subdirectory(self):
        # type: () -> Optional[STRING_TYPE]
        if self.link is not None:
            return self.link.subdirectory_fragment
        return ""

    @property
    def is_wheel(self):
        # type: () -> bool
        if self.link is None:
            return False
        return self.link.is_wheel

    @property
    def is_artifact(self):
        # type: () -> bool

        if self.link is None:
            return False
        return getattr(self.link, "is_vcs", False)

    @property
    def is_vcs(self):
        # type: () -> bool
        # Installable local files and installable non-vcs urls are handled
        # as files, generally speaking
        try:
            if is_vcs(self.line) or is_vcs(self.get_url()):
                return True
        except ValueError:
            return False
        return False

    @property
    def is_url(self):
        # type: () -> bool
        try:
            url = self.get_url()
        except ValueError:
            return False
        if is_valid_url(url) or is_file_url(url):
            return True
        return False

    @property
    def is_remote_url(self):
        # type: () -> bool
        return self.is_url and self.parsed_url.host is not None

    @property
    def is_path(self):
        # type: () -> bool
        try:
            line_url = self.get_url()
        except ValueError:
            line_url = None
        if (
            self.path
            and (
                self.path.startswith(".")
                or os.path.isabs(self.path)
                or os.path.exists(self.path)
            )
            and is_installable_file(self.path)
        ):
            return True
        elif (os.path.exists(self.line) and is_installable_file(self.line)) or (
            line_url and os.path.exists(line_url) and is_installable_file(line_url)
        ):
            return True
        return False

    @property
    def is_file_url(self):
        # type: () -> bool
        try:
            url = self.get_url()
        except ValueError:
            return False
        try:
            parsed_url_scheme = self.parsed_url.scheme
        except ValueError:
            return False
        if url and is_file_url(url) or parsed_url_scheme == "file":
            return True
        return False

    @property
    def is_file(self):
        # type: () -> bool
        try:
            url = self.get_url()
        except ValueError:
            return False
        if (
            self.is_path
            or (is_file_url(url) and is_installable_file(url))
            or (
                self._parsed_url
                and self._parsed_url.is_file_url
                and is_installable_file(self._parsed_url.url_without_fragment_or_ref)
            )
        ):
            return True
        return False

    @property
    def is_named(self):
        # type: () -> bool
        return not (
            self.is_file_url
            or self.is_url
            or self.is_file
            or self.is_vcs
            or self.is_direct_url
        )

    @property
    def ref(self):
        # type: () -> Optional[STRING_TYPE]
        if self._ref is None and self.relpath is not None:
            self.relpath, self._ref = split_ref_from_uri(self.relpath)
        return self._ref

    @property
    def ireq(self):
        # type: () -> Optional[InstallRequirement]
        if self._ireq is None:
            self.parse_ireq()
        return self._ireq

    @property
    def is_installable(self):
        # type: () -> bool
        try:
            url = self.get_url()
        except ValueError:
            url = None
        possible_paths = (self.line, url, self.path, self.base_path)
        return any(is_installable_file(p) for p in possible_paths if p is not None)

    @property
    def wheel_kwargs(self):
        if not self._wheel_kwargs:
            self._wheel_kwargs = _prepare_wheel_building_kwargs(self.ireq)
        return self._wheel_kwargs

    def get_setup_info(self):
        # type: () -> SetupInfo
        setup_info = None
        with global_tempdir_manager():
            setup_info = SetupInfo.from_ireq(self.ireq, subdir=self.subdirectory)
            if not setup_info.name:
                setup_info.get_info()
        return setup_info

    @property
    def setup_info(self):
        # type: () -> Optional[SetupInfo]
        if not self._setup_info and not self.is_named and not self.is_wheel:
            # make two attempts at this before failing to allow for stale data
            try:
                self.setup_info = self.get_setup_info()
            except FileNotFoundError:
                try:
                    self.setup_info = self.get_setup_info()
                except FileNotFoundError:
                    raise
        return self._setup_info

    @setup_info.setter
    def setup_info(self, setup_info):
        # type: (SetupInfo) -> None
        self._setup_info = setup_info
        if setup_info.version:
            self.specifier = setup_info.version
        if setup_info.name and not self.name:
            self.name = setup_info.name

    def _get_vcsrepo(self):
        # type: () -> Optional[VCSRepository]
        from .vcs import VCSRepository

        checkout_directory = self.wheel_kwargs["src_dir"]  # type: ignore
        if self.name is not None:
            checkout_directory = os.path.join(
                checkout_directory, self.name
            )  # type: ignore
        vcsrepo = VCSRepository(
            url=self.link.url,
            name=self.name,
            ref=self.ref if self.ref else None,
            checkout_directory=checkout_directory,
            vcs_type=self.vcs,
            subdirectory=self.subdirectory,
        )
        if not (self.link.scheme.startswith("file") and self.editable):
            vcsrepo.obtain()
        return vcsrepo

    @property
    def vcsrepo(self):
        # type: () -> Optional[VCSRepository]
        if self._vcsrepo is None and self.is_vcs:
            self._vcsrepo = self._get_vcsrepo()
        return self._vcsrepo

    @property
    def parsed_url(self):
        # type: () -> URI
        if self._parsed_url is None:
            self._parsed_url = URI.parse(self.line)
        return self._parsed_url

    @property
    def is_direct_url(self):
        # type: () -> bool
        try:
            return self.is_url and self.parsed_url.is_direct_url
        except ValueError:
            return self.is_url and bool(DIRECT_URL_RE.match(self.line))

    @cached_property
    def metadata(self):
        # type: () -> Dict[Any, Any]
        if self.is_local and self.path and is_installable_dir(self.path):
            return get_metadata(self.path)
        return {}

    @cached_property
    def parsed_setup_cfg(self):
        # type: () -> Dict[Any, Any]
        if not (
            self.is_local
            and self.path
            and is_installable_dir(self.path)
            and self.setup_cfg
        ):
            return {}
        return self.setup_info.parse_setup_cfg()

    @cached_property
    def parsed_setup_py(self):
        # type: () -> Dict[Any, Any]
        if self.is_local and self.path and is_installable_dir(self.path):
            if self.setup_py:
                return ast_parse_setup_py(self.setup_py, raising=False)
        return {}

    @vcsrepo.setter
    def vcsrepo(self, repo):
        # type (VCSRepository) -> None
        self._vcsrepo = repo
        ireq = self.ireq
        wheel_kwargs = self.wheel_kwargs.copy()
        wheel_kwargs["src_dir"] = repo.checkout_directory
        with global_tempdir_manager(), temp_path():
            ireq.ensure_has_source_dir(wheel_kwargs["src_dir"])
            sys.path = [repo.checkout_directory, "", ".", get_path("purelib")]
            setupinfo = SetupInfo.create(
                repo.checkout_directory,
                ireq=ireq,
                subdirectory=self.subdirectory,
                kwargs=wheel_kwargs,
            )
            self._setup_info = setupinfo
            self._setup_info.reload()

    def get_ireq(self):
        # type: () -> InstallRequirement
        line = self.line_for_ireq
        if self.editable:
            ireq = install_req_from_editable(line)
        else:
            ireq = install_req_from_line(line)
        if self.is_named:
            ireq = install_req_from_line(self.line)
        if self.is_file or self.is_remote_url:
            ireq.link = Link(expand_env_variables(self.link.url))
        if self.extras and not ireq.extras:
            ireq.extras = set(self.extras)
        if self.parsed_marker is not None and not ireq.markers:
            ireq.markers = self.parsed_marker
        if not ireq.req and self._requirement is not None:
            ireq.req = copy.deepcopy(self._requirement)
        return ireq

    def parse_ireq(self):
        # type: () -> None
        if self._ireq is None:
            self._ireq = self.get_ireq()
        if self._ireq is not None:
            if self.requirement is not None and self._ireq.req is None:
                self._ireq.req = self.requirement

    def _parse_wheel(self):
        # type: () -> Optional[STRING_TYPE]
        if not self.is_wheel:
            return
        _wheel = Wheel(self.link.filename)
        name = _wheel.name
        version = _wheel.version
        self._specifier = "=={0}".format(version)
        return name

    def _parse_name_from_link(self):
        # type: () -> Optional[STRING_TYPE]
        if self.link is None:
            return None
        if getattr(self.link, "egg_fragment", None):
            return self.link.egg_fragment
        elif self.is_wheel:
            return self._parse_wheel()
        return None

    def _parse_name_from_line(self):
        # type: () -> Optional[STRING_TYPE]
        if not self.is_named:
            pass
        try:
            self._requirement = init_requirement(self.line)
        except Exception:
            raise RequirementError(
                "Failed parsing requirement from {0!r}".format(self.line)
            )
        name = self._requirement.name
        if not self._specifier and self._requirement and self._requirement.specifier:
            self._specifier = specs_to_string(self._requirement.specifier)
        if self._requirement.extras and not self.extras:
            self.extras = self._requirement.extras
        if not name:
            name = self.line
            specifier_match = next(
                iter(spec for spec in SPECIFIERS_BY_LENGTH if spec in self.line), None
            )
            specifier = None  # type: Optional[STRING_TYPE]
            if specifier_match:
                specifier = "{0!s}".format(specifier_match)
            if specifier is not None and specifier in name:
                version = None  # type: Optional[STRING_TYPE]
                name, specifier, version = name.partition(specifier)
                self._specifier = "{0}{1}".format(specifier, version)
        return name

    def _parse_name_from_path(self):
        # type: () -> Optional[S]
        if self.path and self.is_local and is_installable_dir(self.path):
            metadata = get_metadata(self.path)
            if metadata:
                name = metadata.get("name", "")
                if name and name != "wheel":
                    return name
            parsed_setup_cfg = self.parsed_setup_cfg
            if parsed_setup_cfg:
                name = parsed_setup_cfg.get("name", "")
                if name:
                    return name

            parsed_setup_py = self.parsed_setup_py
            if parsed_setup_py:
                name = parsed_setup_py.get("name", "")
                if name and isinstance(name, str):
                    return name
        return None

    def parse_name(self):
        # type: () -> "Line"
        if self._name is None:
            name = None
            if self.link is not None and self.line_is_installable:
                name = self._parse_name_from_link()
            if name is None and (
                (self.is_remote_url or self.is_artifact or self.is_vcs)
                and self._parsed_url
            ):
                if self._parsed_url.fragment:
                    _, _, name = self._parsed_url.fragment.partition("egg=")
                    if "&" in name:
                        # subdirectory fragments might also be in here
                        name, _, _ = name.partition("&")
            if name is None and self.is_named:
                name = self._parse_name_from_line()
            elif name is None and (self.is_file or self.is_remote_url or self.is_path):
                if self.is_local:
                    name = self._parse_name_from_path()
            if name is not None:
                name, extras = _strip_extras(name)
                if extras is not None and not self.extras:
                    self.extras = tuple(sorted(set(parse_extras(extras))))
                self._name = name
        return self

    def _parse_requirement_from_vcs(self):
        # type: () -> Optional[PackagingRequirement]
        url = self.url if self.url else self.link.url
        if url:
            url = unquote(url)
        if (
            url
            and self.uri != url
            and "git+ssh://" in url
            and (self.uri is not None and "git+git@" in self.uri)
            and self._requirement is not None
        ):
            self._requirement.line = self.uri
            self._requirement.url = self.url
            vcs_uri = build_vcs_uri(  # type: ignore
                vcs=self.vcs,
                uri=self.url,
                ref=self.ref,
                subdirectory=self.subdirectory,
                extras=self.extras,
                name=self.name,
            )
            if vcs_uri:
                self._requirement.link = create_link(vcs_uri)
            elif self.link:
                self._requirement.link = self.link
        # else:
        #     req.link = self.link
        if self.ref and self._requirement is not None:
            self._requirement.revision = self.ref
            if self._vcsrepo is not None:
                with global_tempdir_manager():
                    self._requirement.revision = self._vcsrepo.get_commit_hash()
        return self._requirement

    def parse_requirement(self):
        # type: () -> "Line"
        if self._name is None:
            self.parse_name()
            if not any([self._name, self.is_vcs, self.is_named]):
                if self.setup_info and self.setup_info.name:
                    self._name = self.setup_info.name
        name, extras, url = self.requirement_info
        if name:
            self._requirement = init_requirement(name)  # type: PackagingRequirement
            if extras:
                self._requirement.extras = set(extras)
            if url:
                self._requirement.url = url
            if self.is_direct_url:
                url = self.link.url
            if self.link:
                self._requirement.link = self.link
            self._requirement.editable = self.editable
            if self.path and self.link and self.link.scheme.startswith("file"):
                self._requirement.local_file = True
                self._requirement.path = self.path
            if self.is_vcs:
                self._requirement.vcs = self.vcs
                self._requirement.line = self.link.url
                self._parse_requirement_from_vcs()
            else:
                self._requirement.line = self.line
            if self.parsed_marker is not None:
                self._requirement.marker = self.parsed_marker
            if self.specifiers:
                self._requirement.specifier = self.specifiers
                specs = []
                spec = next(iter(s for s in self.specifiers._specs), None)
                if spec:
                    specs.append(spec._spec)
                self._requirement.spec = spec
        else:
            if self.is_vcs:
                raise ValueError(
                    "pipenv requires an #egg fragment for version controlled "
                    "dependencies. Please install remote dependency "
                    "in the form {0}#egg=<package-name>.".format(url)
                )
        return self

    def parse_link(self):
        # type: () -> "Line"
        parsed_url = None  # type: Optional[URI]
        if (
            not is_valid_url(self.line)
            and is_installable_file(os.path.abspath(self.line))
            and (
                self.line.startswith("./")
                or (os.path.exists(self.line) or os.path.isabs(self.line))
            )
        ):
            url = path_to_url(os.path.abspath(self.line))
            self._parsed_url = parsed_url = URI.parse(url)
        elif any(
            [
                is_valid_url(self.line),
                is_vcs(self.line),
                is_file_url(self.line),
                self.is_direct_url,
            ]
        ):
            parsed_url = self.parsed_url
        if parsed_url is None or (
            parsed_url.is_file_url and not parsed_url.is_installable
        ):
            return None
        if parsed_url.is_vcs:
            self.vcs, _ = parsed_url.scheme.split("+")
        if parsed_url.is_file_url:
            self.is_local = True
        parsed_link = parsed_url.as_link
        self._ref = parsed_url.ref
        self.uri = parsed_url.bare_url
        if parsed_url.name:
            self._name = parsed_url.name
        if parsed_url.extras:
            self.extras = tuple(sorted(set(parsed_url.extras)))
        self._link = parsed_link
        vcs, prefer, relpath, path, uri, link = FileRequirement.get_link_from_line(
            self.line
        )
        ref = None
        if link is not None and "@" in unquote(link.path) and uri is not None:
            uri, _, ref = unquote(uri).rpartition("@")
        if relpath is not None and "@" in relpath:
            relpath, _, ref = relpath.rpartition("@")
        if path is not None and "@" in path:
            path, _ = split_ref_from_uri(path)
        link_url = link.url_without_fragment
        if "@" in link_url:
            link_url, _ = split_ref_from_uri(link_url)
        self.preferred_scheme = prefer
        self.relpath = relpath
        self.path = path
        # self.uri = uri
        if prefer in ("path", "relpath") or uri.startswith("file"):
            self.is_local = True
        if parsed_url.is_vcs or parsed_url.is_direct_url and parsed_link:
            self._link = parsed_link
        else:
            self._link = link
        return self

    def parse_markers(self):
        # type: () -> None
        if self.markers:
            pkg_name, markers = split_markers_from_line(self.line)
            self.parsed_marker = markers

    @property
    def requirement_info(self):
        # type: () -> Tuple[Optional[S], Tuple[Optional[S], ...], Optional[S]]
        """
        Generates a 3-tuple of the requisite *name*, *extras* and *url* to generate a
        :class:`~packaging.requirements.Requirement` out of.

        :return: A Tuple of an optional name, a Tuple of extras, and an optional URL.
        :rtype: Tuple[Optional[S], Tuple[Optional[S], ...], Optional[S]]
        """

        # Direct URLs can be converted to packaging requirements directly, but
        # only if they are `file://` (with only two slashes)
        name = None  # type: Optional[S]
        extras = ()  # type: Tuple[Optional[S], ...]
        url = None  # type: Optional[STRING_TYPE]
        # if self.is_direct_url:
        if self._name:
            name = canonicalize_name(self._name)
        if self.is_file or self.is_url or self.is_path or self.is_file_url or self.is_vcs:
            url = ""
            if self.is_vcs:
                url = self.url if self.url else self.uri
                if self.is_direct_url:
                    url = self.link.url_without_fragment
            else:
                if self.link:
                    url = self.link.url_without_fragment
                elif self.url:
                    url = self.url
                    if self.ref:
                        url = "{0}@{1}".format(url, self.ref)
                else:
                    url = self.uri
            if self.link and name is None:
                self._name = self.link.egg_fragment
                if self._name:
                    name = canonicalize_name(self._name)
        return name, extras, url  # type: ignore

    @property
    def line_is_installable(self):
        # type: () -> bool
        """This is a safeguard against decoy requirements when a user installs
        a package whose name coincides with the name of a folder in the cwd,
        e.g. install *alembic* when there is a folder called *alembic* in the
        working directory.

        In this case we first need to check that the given requirement
        is a valid URL, VCS requirement, or installable filesystem path
        before deciding to treat it as a file requirement over a named
        requirement.
        """
        line = self.line
        direct_url_match = DIRECT_URL_RE.match(line)
        if direct_url_match:
            match_dict = direct_url_match.groupdict()
            auth = ""
            username = match_dict.get("username", None)
            password = match_dict.get("password", None)
            port = match_dict.get("port", None)
            path = match_dict.get("path", None)
            ref = match_dict.get("ref", None)
            if username is not None:
                auth = "{0}".format(username)
            if password:
                auth = "{0}:{1}".format(auth, password) if auth else password
            line = match_dict.get("host", "")
            if auth:
                line = "{auth}@{line}".format(auth=auth, line=line)
            if port:
                line = "{line}:{port}".format(line=line, port=port)
            if path:
                line = "{line}{pathsep}{path}".format(
                    line=line, pathsep=match_dict["pathsep"], path=path
                )
            if ref:
                line = "{line}@{ref}".format(line=line, ref=ref)
            line = "{scheme}{line}".format(scheme=match_dict["scheme"], line=line)
        if is_file_url(line):
            link = create_link(line)
            line = link.url_without_fragment
            line, _ = split_ref_from_uri(line)
        if (
            is_vcs(line)
            or (not is_file_url(line) and is_valid_url(line))
            or (is_file_url(line) and is_installable_file(line))
            or is_installable_file(line)
        ):
            return True
        return False

    def parse(self):
        # type: () -> None
        self.line = self.line.strip()
        if self.line.startswith('"'):
            self.line = self.line.strip('"')
        self.line, self.markers = split_markers_from_line(self.parse_hashes().line)
        if self.markers:
            self.markers = self.markers.replace('"', "'")
        self.parse_extras()
        if self.line.startswith("git+file:/") and not self.line.startswith(
            "git+file:///"
        ):
            self.line = self.line.replace("git+file:/", "git+file:///")
        self.parse_markers()
        if self.is_file_url:
            if self.line_is_installable:
                self.populate_setup_paths()
            else:
                raise RequirementError(
                    "Supplied requirement is not installable: {0!r}".format(self.line)
                )
        elif self.is_named and self._name is None:
            self.parse_name()
        self.parse_link()
        # self.parse_requirement()
        # self.parse_ireq()


@attr.s(slots=True, hash=True)
class NamedRequirement(object):
    name = attr.ib()  # type: STRING_TYPE
    version = attr.ib()  # type: Optional[STRING_TYPE]
    req = attr.ib()  # type: PackagingRequirement
    extras = attr.ib(default=attr.Factory(list))  # type: Tuple[STRING_TYPE, ...]
    editable = attr.ib(default=False)  # type: bool
    _parsed_line = attr.ib(default=None)  # type: Optional[Line]

    @req.default
    def get_requirement(self):
        # type: () -> RequirementType
        req = init_requirement(
            "{0}{1}".format(canonicalize_name(self.name), self.version)
        )
        return req

    @property
    def parsed_line(self):
        # type: () -> Optional[Line]
        if self._parsed_line is None:
            self._parsed_line = Line(self.line_part)
        return self._parsed_line

    @classmethod
    def from_line(cls, line, parsed_line=None):
        # type: (AnyStr, Optional[Line]) -> NamedRequirement
        req = init_requirement(line)
        specifiers = None  # type: Optional[STRING_TYPE]
        if req.specifier:
            specifiers = specs_to_string(req.specifier)
        req.line = line
        name = getattr(req, "name", None)
        if not name:
            name = getattr(req, "project_name", None)
            req.name = name
        if not name:
            name = getattr(req, "key", line)
            req.name = name
        creation_kwargs = {
            "name": name,
            "version": specifiers,
            "req": req,
            "parsed_line": parsed_line,
            "extras": None,
        }
        extras = None  # type: Optional[Tuple[STRING_TYPE, ...]]
        if req.extras:
            extras = tuple(req.extras)
        creation_kwargs["extras"] = extras
        return cls(**creation_kwargs)

    @classmethod
    def from_pipfile(cls, name, pipfile):
        # type: (S, TPIPFILE) -> NamedRequirement
        creation_args = {}  # type: TPIPFILE
        if hasattr(pipfile, "keys"):
            attr_fields = [field.name for field in attr.fields(cls)]
            creation_args = {
                k: v for k, v in pipfile.items() if k in attr_fields
            }  # type: ignore
        creation_args["name"] = name
        version = get_version(pipfile)  # type: Optional[STRING_TYPE]
        extras = creation_args.get("extras", None)
        creation_args["version"] = version  # type: ignore
        req = init_requirement("{0}{1}".format(name, version))
        if req and extras and req.extras and isinstance(req.extras, tuple):
            if isinstance(extras, str):
                req.extras = (extras) + tuple(["{0}".format(xtra) for xtra in req.extras])
            elif isinstance(extras, (tuple, list)):
                req.extras += tuple(extras)
        creation_args["req"] = req
        return cls(**creation_args)  # type: ignore

    @property
    def line_part(self):
        # type: () -> STRING_TYPE
        # FIXME: This should actually be canonicalized but for now we have to
        # simply lowercase it and replace underscores, since full canonicalization
        # also replaces dots and that doesn't actually work when querying the index
        return normalize_name(self.name)

    @property
    def pipfile_part(self):
        # type: () -> Dict[STRING_TYPE, Any]
        pipfile_dict = attr.asdict(self, filter=filter_none).copy()  # type: ignore
        if "version" not in pipfile_dict:
            pipfile_dict["version"] = "*"
        if "_parsed_line" in pipfile_dict:
            pipfile_dict.pop("_parsed_line")
        name = pipfile_dict.pop("name")
        return {name: pipfile_dict}


LinkInfo = collections.namedtuple(
    "LinkInfo", ["vcs_type", "prefer", "relpath", "path", "uri", "link"]
)


@attr.s(slots=True, eq=True, order=True, hash=True)
class FileRequirement(object):
    """File requirements for tar.gz installable files or wheels or setup.py
    containing directories."""

    #: Path to the relevant `setup.py` location
    setup_path = attr.ib(default=None, eq=True, order=True)  # type: Optional[STRING_TYPE]
    #: path to hit - without any of the VCS prefixes (like git+ / http+ / etc)
    path = attr.ib(default=None, eq=True, order=True)  # type: Optional[STRING_TYPE]
    #: Whether the package is editable
    editable = attr.ib(default=False, eq=True, order=True)  # type: bool
    #: Extras if applicable
    extras = attr.ib(
        default=attr.Factory(tuple), eq=True, order=True
    )  # type: Tuple[STRING_TYPE, ...]
    _uri_scheme = attr.ib(
        default=None, eq=True, order=True
    )  # type: Optional[STRING_TYPE]
    #: URI of the package
    uri = attr.ib(eq=True, order=True)  # type: Optional[STRING_TYPE]
    #: Link object representing the package to clone
    link = attr.ib(eq=True, order=True)  # type: Optional[Link]
    #: PyProject Requirements
    pyproject_requires = attr.ib(
        factory=tuple, eq=True, order=True
    )  # type: Optional[Tuple[STRING_TYPE, ...]]
    #: PyProject Build System
    pyproject_backend = attr.ib(
        default=None, eq=True, order=True
    )  # type: Optional[STRING_TYPE]
    #: PyProject Path
    pyproject_path = attr.ib(
        default=None, eq=True, order=True
    )  # type: Optional[STRING_TYPE]
    subdirectory = attr.ib(default=None)  # type: Optional[STRING_TYPE]
    #: Setup metadata e.g. dependencies
    _setup_info = attr.ib(default=None, eq=True, order=True)  # type: Optional[SetupInfo]
    _has_hashed_name = attr.ib(default=False, eq=True, order=True)  # type: bool
    _parsed_line = attr.ib(
        default=None, eq=False, order=False, hash=True
    )  # type: Optional[Line]
    #: Package name
    name = attr.ib(eq=True, order=True)  # type: Optional[STRING_TYPE]
    #: A :class:`~pkg_resources.Requirement` instance
    req = attr.ib(eq=True, order=True)  # type: Optional[PackagingRequirement]

    @classmethod
    def get_link_from_line(cls, line):
        # type: (STRING_TYPE) -> LinkInfo
        """Parse link information from given requirement line.

        Return a 6-tuple:

        - `vcs_type` indicates the VCS to use (e.g. "git"), or None.
        - `prefer` is either "file", "path" or "uri", indicating how the
            information should be used in later stages.
        - `relpath` is the relative path to use when recording the dependency,
            instead of the absolute path/URI used to perform installation.
            This can be None (to prefer the absolute path or URI).
        - `path` is the absolute file path to the package. This will always use
            forward slashes. Can be None if the line is a remote URI.
        - `uri` is the absolute URI to the package. Can be None if the line is
            not a URI.
        - `link` is an instance of :class:`pipenv.patched.pip._internal.index.Link`,
            representing a URI parse result based on the value of `uri`.

        This function is provided to deal with edge cases concerning URIs
        without a valid netloc. Those URIs are problematic to a straight
        ``urlsplit` call because they cannot be reliably reconstructed with
        ``urlunsplit`` due to a bug in the standard library:

        >>> from urllib.parse import urlsplit, urlunsplit
        >>> urlunsplit(urlsplit('git+file:///this/breaks'))
        'git+file:/this/breaks'
        >>> urlunsplit(urlsplit('file:///this/works'))
        'file:///this/works'

        See `https://bugs.python.org/issue23505#msg277350`.
        """

        # Git allows `git@github.com...` lines that are not really URIs.
        # Add "ssh://" so we can parse correctly, and restore afterwards.
        fixed_line = add_ssh_scheme_to_git_uri(line)  # type: STRING_TYPE
        added_ssh_scheme = fixed_line != line  # type: bool

        # We can assume a lot of things if this is a local filesystem path.
        if "://" not in fixed_line:
            p = Path(fixed_line).absolute()  # type: Path
            path = p.as_posix()  # type: Optional[STRING_TYPE]
            uri = p.as_uri()  # type: STRING_TYPE
            link = create_link(uri)  # type: Link
            relpath = None  # type: Optional[STRING_TYPE]
            try:
                relpath = get_converted_relative_path(path)
            except ValueError:
                relpath = None
            return LinkInfo(None, "path", relpath, path, uri, link)

        # This is an URI. We'll need to perform some elaborated parsing.

        parsed_url = urllib_parse.urlsplit(fixed_line)  # type: SplitResult
        original_url = parsed_url._replace()  # type: SplitResult

        # Split the VCS part out if needed.
        original_scheme = parsed_url.scheme  # type: STRING_TYPE
        vcs_type = None  # type: Optional[STRING_TYPE]
        if "+" in original_scheme:
            scheme = None  # type: Optional[STRING_TYPE]
            vcs_type, _, scheme = original_scheme.partition("+")
            parsed_url = parsed_url._replace(scheme=scheme)  # type: ignore
            prefer = "uri"  # type: STRING_TYPE
        else:
            vcs_type = None
            prefer = "file"

        if parsed_url.scheme == "file" and parsed_url.path:
            # This is a "file://" URI. Use url_to_path and path_to_url to
            # ensure the path is absolute. Also we need to build relpath.
            path = Path(url_to_path(urllib_parse.urlunsplit(parsed_url))).as_posix()
            try:
                relpath = get_converted_relative_path(path)
            except ValueError:
                relpath = None
            uri = path_to_url(path)
        else:
            # This is a remote URI. Simply use it.
            path = None
            relpath = None
            # Cut the fragment, but otherwise this is fixed_line.
            uri = urllib_parse.urlunsplit(
                parsed_url._replace(scheme=original_scheme, fragment="")  # type: ignore
            )

        if added_ssh_scheme:
            original_uri = urllib_parse.urlunsplit(
                original_url._replace(scheme=original_scheme, fragment="")  # type: ignore
            )
            uri = strip_ssh_from_git_uri(original_uri)

        # Re-attach VCS prefix to build a Link.
        link = create_link(
            urllib_parse.urlunsplit(
                parsed_url._replace(scheme=original_scheme)
            )  # type: ignore
        )

        return LinkInfo(vcs_type, prefer, relpath, path, uri, link)

    @property
    def setup_py_dir(self):
        # type: () -> Optional[STRING_TYPE]
        if self.setup_path:
            return os.path.dirname(os.path.abspath(self.setup_path))
        return None

    @property
    def dependencies(self):
        # type: () -> Tuple[Dict[S, PackagingRequirement], List[Union[S, PackagingRequirement]], List[S]]
        build_deps = []  # type: List[Union[S, PackagingRequirement]]
        setup_deps = []  # type: List[S]
        deps = {}  # type: Dict[S, PackagingRequirement]
        if self.setup_info:
            setup_info = self.setup_info.as_dict()
            deps.update(setup_info.get("requires", {}))
            setup_deps.extend(setup_info.get("setup_requires", []))
            build_deps.extend(setup_info.get("build_requires", []))
            if self.extras and self.setup_info.extras:
                for dep in self.extras:
                    if dep not in self.setup_info.extras:
                        continue
                    extras_list = self.setup_info.extras.get(dep, [])  # type: ignore
                    for req_instance in extras_list:  # type: ignore
                        deps[req_instance.key] = req_instance
        if self.pyproject_requires:
            build_deps.extend(list(self.pyproject_requires))
        setup_deps = list(set(setup_deps))
        build_deps = list(set(build_deps))
        return deps, setup_deps, build_deps

    def __attrs_post_init__(self):
        # type: () -> None
        if self.name is None and self.parsed_line:
            if self.parsed_line.setup_info:
                self._setup_info = self.parsed_line.setup_info
                if self.parsed_line.setup_info.name:
                    self.name = self.parsed_line.setup_info.name
        if self.req is None and (
            self._parsed_line is not None and self._parsed_line.requirement is not None
        ):
            self.req = self._parsed_line.requirement
        if (
            self._parsed_line
            and self._parsed_line.ireq
            and not self._parsed_line.ireq.req
        ):
            if self.req is not None and self._parsed_line._ireq is not None:
                self._parsed_line._ireq.req = self.req

    @property
    def setup_info(self):
        # type: () -> Optional[SetupInfo]
        if self._setup_info is None and self.parsed_line:
            if self.parsed_line and self._parsed_line and self.parsed_line.setup_info:
                if (
                    self._parsed_line._setup_info
                    and not self._parsed_line._setup_info.name
                ):
                    with global_tempdir_manager():
                        self._parsed_line._setup_info.get_info()
                self._setup_info = self.parsed_line._setup_info
            elif self.parsed_line and (
                self.parsed_line.ireq and not self.parsed_line.is_wheel
            ):
                with global_tempdir_manager():
                    self._setup_info = SetupInfo.from_ireq(
                        self.parsed_line.ireq, subdir=self.subdirectory
                    )
            else:
                if self.link and not self.link.is_wheel:
                    self._setup_info = Line(self.line_part).setup_info
                    with global_tempdir_manager():
                        self._setup_info.get_info()
        return self._setup_info

    @setup_info.setter
    def setup_info(self, setup_info):
        # type: (SetupInfo) -> None
        self._setup_info = setup_info
        if self._parsed_line:
            self._parsed_line._setup_info = setup_info

    @uri.default
    def get_uri(self):
        # type: () -> STRING_TYPE
        if self.path and not self.uri:
            self._uri_scheme = "path"
            return path_to_url(os.path.abspath(self.path))
        elif (
            getattr(self, "req", None)
            and self.req is not None
            and getattr(self.req, "url", None)
        ):
            return self.req.url
        elif self.link is not None:
            return self.link.url_without_fragment
        return ""

    @name.default
    def get_name(self):
        # type: () -> STRING_TYPE
        if self.parsed_line and self.parsed_line.name:
            return self.parsed_line.name
        elif self.link and self.link.egg_fragment:
            return self.link.egg_fragment
        elif self.setup_info and self.setup_info.name:
            return self.setup_info.name

    @link.default
    def get_link(self) -> Link:
        target = "{0}".format(self.uri)
        if hasattr(self, "name") and not self._has_hashed_name:
            target = "{0}#egg={1}".format(target, self.name)
        link = create_link(target)
        return link

    @req.default
    def get_requirement(self):
        # type () -> RequirementType
        if self.name is None:
            if self._parsed_line is not None and self._parsed_line.name is not None:
                self.name = self._parsed_line.name
            else:
                raise ValueError(
                    "Failed to generate a requirement: missing name for {0!r}".format(
                        self
                    )
                )
        if self._parsed_line:
            try:
                # initialize specifiers to make sure we capture them
                self._parsed_line.specifiers
            except Exception:
                pass
            req = copy.deepcopy(self._parsed_line.requirement)
            if req:
                return req

    @property
    def parsed_line(self):
        # type: () -> Optional[Line]
        if self._parsed_line is None:
            self._parsed_line = Line(self.line_part)
        return self._parsed_line

    @property
    def is_local(self):
        # type: () -> bool
        uri = getattr(self, "uri", None)
        if uri is None:
            if getattr(self, "path", None) and self.path is not None:
                uri = path_to_url(os.path.abspath(self.path))
            elif (
                getattr(self, "req", None)
                and self.req is not None
                and (getattr(self.req, "url", None) and self.req.url is not None)
            ):
                uri = self.req.url
            if uri and is_file_url(uri):
                return True
        return False

    @property
    def is_remote_artifact(self):
        # type: () -> bool
        if self.link is None:
            return False
        return (
            self._parsed_line
            and not self._parsed_line.is_local
            and (self._parsed_line.is_artifact or self._parsed_line.is_wheel)
            and not self.editable
        )

    @property
    def is_direct_url(self):
        # type: () -> bool
        if self._parsed_line is not None and self._parsed_line.is_direct_url:
            return True
        return self.is_remote_artifact

    @property
    def formatted_path(self):
        # type: () -> Optional[STRING_TYPE]
        if self.path:
            path = self.path
            if not isinstance(path, Path):
                path = Path(path)
            return path.as_posix()
        return None

    @classmethod
    def from_line(cls, line, editable=None, extras=None, parsed_line=None):
        # type: (AnyStr, Optional[bool], Optional[Tuple[AnyStr, ...]], Optional[Line]) -> F
        parsed_line = Line(line)
        file_req_from_parsed_line(parsed_line)

    @classmethod
    def from_pipfile(cls, name, pipfile):
        # type: (STRING_TYPE, Dict[STRING_TYPE, Union[Tuple[STRING_TYPE, ...], STRING_TYPE, bool]]) -> F
        # Parse the values out. After this dance we should have two variables:
        # path - Local filesystem path.
        # uri - Absolute URI that is parsable with urlsplit.
        # One of these will be a string; the other would be None.
        uri = pipfile.get("uri")
        fil = pipfile.get("file")
        path = pipfile.get("path")
        if path and isinstance(path, str):
            if isinstance(path, Path) and not path.is_absolute():
                path = get_converted_relative_path(path.as_posix())
            elif not os.path.isabs(path):
                path = get_converted_relative_path(path)
        if path and uri:
            raise ValueError("do not specify both 'path' and 'uri'")
        if path and fil:
            raise ValueError("do not specify both 'path' and 'file'")
        uri = uri or fil

        # Decide that scheme to use.
        # 'path' - local filesystem path.
        # 'file' - A file:// URI (possibly with VCS prefix).
        # 'uri' - Any other URI.
        if path:
            uri_scheme = "path"
        else:
            # URI is not currently a valid key in pipfile entries
            # see https://github.com/pypa/pipfile/issues/110
            uri_scheme = "file"

        if not uri:
            uri = path_to_url(path)
        link_info = None  # type: Optional[LinkInfo]
        if uri and isinstance(uri, str):
            link_info = cls.get_link_from_line(uri)
        else:
            raise ValueError(
                "Failed parsing requirement from pipfile: {0!r}".format(pipfile)
            )
        link = None  # type: Optional[Link]
        if link_info:
            link = link_info.link
            if link.url_without_fragment:
                uri = link.url_without_fragment
        extras = ()  # type: Optional[Tuple[STRING_TYPE, ...]]
        if "extras" in pipfile:
            extras = tuple(pipfile["extras"])  # type: ignore
        editable = pipfile["editable"] if "editable" in pipfile else False
        arg_dict = {
            "name": name,
            "path": path,
            "uri": uri,
            "editable": editable,
            "link": link,
            "uri_scheme": uri_scheme,
            "extras": extras if extras else None,
        }

        line = ""  # type: STRING_TYPE
        extras_string = "" if not extras else extras_to_string(extras)
        if editable and uri_scheme == "path":
            line = "{0}{1}".format(path, extras_string)
        else:
            if name:
                line_name = "{0}{1}".format(name, extras_string)
                line = "{0}#egg={1}".format(link.url_without_fragment, line_name)
            else:
                if link:
                    line = link.url
                elif uri and isinstance(uri, str):
                    line = uri
                else:
                    raise ValueError(
                        "Failed parsing requirement from pipfile: {0!r}".format(pipfile)
                    )
                line = "{0}{1}".format(line, extras_string)
            if "subdirectory" in pipfile:
                arg_dict["subdirectory"] = pipfile["subdirectory"]
                line = "{0}&subdirectory={1}".format(line, pipfile["subdirectory"])
        if editable:
            line = "-e {0}".format(line)
        arg_dict["parsed_line"] = Line(line, extras=extras)
        arg_dict["setup_info"] = arg_dict["parsed_line"].setup_info
        return cls(**arg_dict)  # type: ignore

    @property
    def line_part(self):
        # type: () -> STRING_TYPE
        link_url = None  # type: Optional[STRING_TYPE]
        seed = None  # type: Optional[STRING_TYPE]
        if self.link is not None:
            link_url = self.link.url_without_fragment
        is_vcs = getattr(self.link, "is_vcs", False)
        if self._uri_scheme and self._uri_scheme == "path":
            # We may need any one of these for passing to pip
            seed = self.path or link_url or self.uri
        elif (self._uri_scheme and self._uri_scheme == "file") or (
            (self.link.is_wheel or not is_vcs) and self.link.url
        ):
            seed = link_url or self.uri
        # add egg fragments to remote artifacts (valid urls only)
        if not self._has_hashed_name and self.is_remote_artifact and seed is not None:
            seed += "#egg={0}".format(self.name)
        editable = "-e " if self.editable else ""
        if seed is None:
            raise ValueError("Could not calculate url for {0!r}".format(self))
        return "{0}{1}".format(editable, seed)

    @property
    def pipfile_part(self):
        # type: () -> Dict[AnyStr, Dict[AnyStr, Any]]
        excludes = [
            "_base_line",
            "_has_hashed_name",
            "setup_path",
            "pyproject_path",
            "_uri_scheme",
            "pyproject_requires",
            "pyproject_backend",
            "_setup_info",
            "_parsed_line",
        ]
        filter_func = lambda k, v: bool(v) is True and k.name not in excludes  # noqa
        pipfile_dict = attr.asdict(self, filter=filter_func).copy()  # type: Dict
        name = pipfile_dict.pop("name", None)
        if name is None:
            if self.name:
                name = self.name
            elif self.parsed_line and self.parsed_line.name:
                name = self.name = self.parsed_line.name
            elif self.setup_info and self.setup_info.name:
                name = self.name = self.setup_info.name
        if "_uri_scheme" in pipfile_dict:
            pipfile_dict.pop("_uri_scheme")
        # For local paths and remote installable artifacts (zipfiles, etc)
        collision_keys = {"file", "uri", "path"}
        collision_order = ["file", "uri", "path"]  # type: List[STRING_TYPE]
        collisions = []  # type: List[STRING_TYPE]
        key_match = next(iter(k for k in collision_order if k in pipfile_dict.keys()))
        is_vcs = None
        if self.link is not None:
            is_vcs = getattr(self.link, "is_vcs", False)
        if self._uri_scheme:
            dict_key = self._uri_scheme
            target_key = dict_key if dict_key in pipfile_dict else key_match
            if target_key is not None:
                winning_value = pipfile_dict.pop(target_key)
                collisions = [k for k in collision_keys if k in pipfile_dict]
                for key in collisions:
                    pipfile_dict.pop(key)
                pipfile_dict[dict_key] = winning_value
        elif (
            self.is_remote_artifact
            or (is_vcs is not None and not is_vcs)
            and (self._uri_scheme and self._uri_scheme == "file")
        ):
            dict_key = "file"
            # Look for uri first because file is a uri format and this is designed
            # to make sure we add file keys to the pipfile as a replacement of uri
            if key_match is not None:
                winning_value = pipfile_dict.pop(key_match)
            key_to_remove = (k for k in collision_keys if k in pipfile_dict)
            for key in key_to_remove:
                pipfile_dict.pop(key)
            pipfile_dict[dict_key] = winning_value
        else:
            collisions = [key for key in collision_order if key in pipfile_dict.keys()]
            if len(collisions) > 1:
                for k in collisions[1:]:
                    pipfile_dict.pop(k)
        return {name: pipfile_dict}


@attr.s(slots=True, hash=True)
class VCSRequirement(FileRequirement):
    #: Whether the repository is editable
    editable = attr.ib(default=None)  # type: Optional[bool]
    #: URI for the repository
    uri = attr.ib(default=None)  # type: Optional[STRING_TYPE]
    #: path to the repository, if it's local
    path = attr.ib(
        default=None, validator=attr.validators.optional(validate_path)
    )  # type: Optional[STRING_TYPE]
    #: vcs type, i.e. git/hg/svn
    vcs = attr.ib(
        validator=attr.validators.optional(validate_vcs), default=None
    )  # type: Optional[STRING_TYPE]
    #: vcs reference name (branch / commit / tag)
    ref = attr.ib(default=None)  # type: Optional[STRING_TYPE]
    #: Subdirectory to use for installation if applicable
    _repo = attr.ib(default=None)  # type: Optional[VCSRepository]
    _base_line = attr.ib(default=None)  # type: Optional[STRING_TYPE]
    name = attr.ib()  # type: STRING_TYPE
    link = attr.ib()  # type: Optional[Link]
    req = attr.ib()  # type: Optional[RequirementType]

    def __attrs_post_init__(self):
        # type: () -> None
        if not self.uri:
            if self.path:
                self.uri = path_to_url(self.path)
        if self.uri is not None:
            split = urllib_parse.urlsplit(self.uri)
            scheme, rest = split[0], split[1:]
            vcs_type = ""
            if "+" in scheme:
                vcs_type, scheme = scheme.split("+", 1)
                vcs_type = "{0}+".format(vcs_type)
            new_uri = urllib_parse.urlunsplit((scheme,) + rest[:-1] + ("",))
            new_uri = "{0}{1}".format(vcs_type, new_uri)
            self.uri = new_uri

    @property
    def url(self):
        # type: () -> STRING_TYPE
        if self.link and self.link.url:
            return self.link.url
        elif self.uri:
            return self.uri
        raise ValueError("No valid url found for requirement {0!r}".format(self))

    @link.default
    def get_link(self) -> Link:
        uri = self.uri if self.uri else path_to_url(self.path)
        vcs_uri = build_vcs_uri(
            self.vcs,
            add_ssh_scheme_to_git_uri(uri),
            name=self.name,
            ref=self.ref,
            subdirectory=self.subdirectory,
            extras=self.extras,
        )
        return self.get_link_from_line(vcs_uri).link

    @name.default
    def get_name(self):
        # type: () -> STRING_TYPE
        if self.link and self.link.egg_fragment:
            return self.link.egg_fragment
        if self.req and self.req.name:
            return self.req.name
        return super(VCSRequirement, self).get_name()

    @property
    def vcs_uri(self):
        # type: () -> Optional[STRING_TYPE]
        uri = self.uri
        if uri and not any(uri.startswith("{0}+".format(vcs)) for vcs in VCS_LIST):
            if self.vcs:
                uri = "{0}+{1}".format(self.vcs, uri)
        return uri

    @property
    def setup_info(self):
        if self._parsed_line and self._parsed_line.setup_info:
            if not self._parsed_line.setup_info.name:
                with global_tempdir_manager():
                    self._parsed_line._setup_info.get_info()
            return self._parsed_line.setup_info
        subdir = self.subdirectory or self.parsed_line.subdirectory
        if self._repo:
            with global_tempdir_manager():
                self._setup_info = SetupInfo.from_ireq(
                    Line(self._repo.checkout_directory).ireq, subdir=subdir
                )
                self._setup_info.get_info()
            return self._setup_info
        ireq = self.parsed_line.ireq

        with global_tempdir_manager():
            self._setup_info = SetupInfo.from_ireq(ireq, subdir=subdir)
        return self._setup_info

    @setup_info.setter
    def setup_info(self, setup_info):
        self._setup_info = setup_info
        if self._parsed_line:
            self._parsed_line.setup_info = setup_info

    @req.default
    def get_requirement(self):
        # type: () -> PackagingRequirement
        name = None  # type: Optional[STRING_TYPE]
        if self.name:
            name = self.name
        elif self.link and self.link.egg_fragment:
            name = self.link.egg_fragment
        url = None
        if self.uri:
            url = self.uri
        elif self.link is not None:
            url = self.link.url_without_fragment
        if not name:
            raise ValueError(
                "pipenv requires an #egg fragment for version controlled "
                "dependencies. Please install remote dependency "
                "in the form {0}#egg=<package-name>.".format(url)
            )
        req = init_requirement(canonicalize_name(self.name))
        req.editable = self.editable
        if not getattr(req, "url", None):
            if url is not None:
                url = add_ssh_scheme_to_git_uri(url)
            elif self.uri is not None:
                link = self.get_link_from_line(self.uri).link
                if link:
                    url = link.url_without_fragment
            if (
                url
                and url.startswith("git+file:/")
                and not url.startswith("git+file:///")
            ):
                url = url.replace("git+file:/", "git+file:///")
            if url:
                req.url = url
        line = url if url else self.vcs_uri
        if self.editable:
            line = "-e {0}".format(line)
        req.line = line
        if self.ref:
            req.revision = self.ref
        if self.extras:
            req.extras = self.extras
        req.vcs = self.vcs
        if self.path and self.link and self.link.scheme.startswith("file"):
            req.local_file = True
            req.path = self.path
        req.link = self.link
        if (
            self.link
            and self.link.url_without_fragment
            and self.uri
            and self.uri != unquote(self.link.url_without_fragment)
            and "git+ssh://" in self.link.url
            and "git+git@" in self.uri
        ):
            req.line = self.uri
            url = self.link.url_without_fragment
            if (
                url
                and url.startswith("git+file:/")
                and not url.startswith("git+file:///")
            ):
                url = url.replace("git+file:/", "git+file:///")
            req.url = url
        return req

    @property
    def repo(self):
        # type: () -> VCSRepository
        if self._repo is None:
            if self._parsed_line and self._parsed_line.vcsrepo:
                self._repo = self._parsed_line.vcsrepo
            else:
                self._repo = self.get_vcs_repo()
                if self._parsed_line:
                    self._parsed_line.vcsrepo = self._repo
        return self._repo

    def get_checkout_dir(self, src_dir=None):
        # type: (Optional[S]) -> STRING_TYPE
        src_dir = os.environ.get("PIP_SRC", None) if not src_dir else src_dir
        checkout_dir = None
        if self.is_local:
            path = self.path
            if not path:
                path = url_to_path(self.uri)
            if path and os.path.exists(path):
                checkout_dir = os.path.abspath(path)
                return checkout_dir
        if src_dir is not None:
            checkout_dir = os.path.join(os.path.abspath(src_dir), self.name)
            os.makedirs(src_dir, exist_ok=True)
            return checkout_dir
        return os.path.join(create_tracked_tempdir(prefix="requirementslib"), self.name)

    def get_vcs_repo(self, src_dir=None, checkout_dir=None):
        # type: (Optional[STRING_TYPE], STRING_TYPE) -> VCSRepository
        from .vcs import VCSRepository

        if checkout_dir is None:
            checkout_dir = self.get_checkout_dir(src_dir=src_dir)
        vcsrepo = VCSRepository(
            url=expand_env_variables(self.url),
            name=self.name,
            ref=self.ref if self.ref else None,
            checkout_directory=checkout_dir,
            vcs_type=self.vcs,
            subdirectory=self.subdirectory,
        )
        if not self.is_local:
            vcsrepo.obtain()
        pyproject_info = None
        if self.subdirectory:
            self.setup_path = os.path.join(checkout_dir, self.subdirectory, "setup.py")
            self.pyproject_path = os.path.join(
                checkout_dir, self.subdirectory, "pyproject.toml"
            )
            pyproject_info = get_pyproject(os.path.join(checkout_dir, self.subdirectory))
        else:
            self.setup_path = os.path.join(checkout_dir, "setup.py")
            self.pyproject_path = os.path.join(checkout_dir, "pyproject.toml")
            pyproject_info = get_pyproject(checkout_dir)
        if pyproject_info is not None:
            pyproject_requires, pyproject_backend = pyproject_info
            self.pyproject_requires = tuple(pyproject_requires)
            self.pyproject_backend = pyproject_backend
        return vcsrepo

    def get_commit_hash(self):
        # type: () -> STRING_TYPE
        with global_tempdir_manager():
            hash_ = self.repo.get_commit_hash()
        return hash_

    def update_repo(self, src_dir=None, ref=None):
        # type: (Optional[STRING_TYPE], Optional[STRING_TYPE]) -> STRING_TYPE
        if ref:
            self.ref = ref
        repo_hash = None
        if not self.is_local and self.ref is not None:
            self.repo.checkout_ref(self.ref)
        repo_hash = self.get_commit_hash()
        if self.req:
            self.req.revision = repo_hash
        return repo_hash

    @contextmanager
    def locked_vcs_repo(self, src_dir=None):
        # type: (Optional[AnyStr]) -> Generator[VCSRepository, None, None]
        if not src_dir:
            src_dir = create_tracked_tempdir(prefix="requirementslib-", suffix="-src")
        vcsrepo = self.get_vcs_repo(src_dir=src_dir)
        if not self.req:
            if self.parsed_line is not None:
                self.req = self.parsed_line.requirement
            else:
                self.req = self.get_requirement()
        with global_tempdir_manager():
            revision = self.req.revision = vcsrepo.get_commit_hash()

        # Remove potential ref in the end of uri after ref is parsed
        if self.link and "@" in self.link.show_url and self.uri and "@" in self.uri:
            uri, ref = split_ref_from_uri(self.uri)
            checkout = revision
            if checkout and ref and ref in checkout:
                self.uri = uri
        orig_repo = self._repo
        self._repo = vcsrepo
        if self._parsed_line:
            self._parsed_line.vcsrepo = vcsrepo
        if self._setup_info:
            self._setup_info = attr.evolve(
                self._setup_info,
                requirements=(),
                _extras_requirements=(),
                build_requires=(),
                setup_requires=(),
                version=None,
                metadata=None,
            )
        if self.parsed_line and self._parsed_line:
            self._parsed_line.vcsrepo = vcsrepo
        if self.req and not self.editable:
            self.req.specifier = SpecifierSet("=={0}".format(self.setup_info.version))
        try:
            yield self._repo
        except Exception:
            self._repo = orig_repo
            raise

    @classmethod
    def from_pipfile(cls, name, pipfile):
        # type: (STRING_TYPE, Dict[S, Union[Tuple[S, ...], S, bool]]) -> F
        creation_args = {}  # type: Dict[STRING_TYPE, CREATION_ARG_TYPES]
        pipfile_keys = [
            k
            for k in (
                "ref",
                "vcs",
                "subdirectory",
                "path",
                "editable",
                "file",
                "uri",
                "extras",
            )
            + VCS_LIST
            if k in pipfile
        ]
        # extras = None  # type: Optional[Tuple[STRING_TYPE, ...]]
        for key in pipfile_keys:
            if key == "extras" and key in pipfile:
                extras = pipfile[key]
                if isinstance(extras, (list, tuple)):
                    pipfile[key] = tuple(sorted({extra.lower() for extra in extras}))
                else:
                    pipfile[key] = extras
            if key in VCS_LIST and key in pipfile_keys:
                creation_args["vcs"] = key
                target = pipfile[key]
                if isinstance(target, str):
                    drive, path = os.path.splitdrive(target)
                    if (
                        not drive
                        and not os.path.exists(target)
                        and (
                            is_valid_url(target)
                            or is_file_url(target)
                            or target.startswith("git@")
                        )
                    ):
                        creation_args["uri"] = target
                    else:
                        creation_args["path"] = target
                        if os.path.isabs(target):
                            creation_args["uri"] = path_to_url(target)
            elif key in pipfile_keys:
                creation_args[key] = pipfile[key]
        creation_args["name"] = name
        cls_inst = cls(**creation_args)  # type: ignore
        return cls_inst

    @classmethod
    def from_line(cls, line, editable=None, extras=None, parsed_line=None):
        # type: (AnyStr, Optional[bool], Optional[Tuple[AnyStr, ...]], Optional[Line]) -> F
        parsed_line = Line(line)
        return vcs_req_from_parsed_line(parsed_line)

    @property
    def line_part(self):
        # type: () -> STRING_TYPE
        """requirements.txt compatible line part sans-extras."""
        base = ""  # type: STRING_TYPE
        if self.is_local:
            base_link = self.link
            if not self.link:
                base_link = self.get_link()
            if base_link and base_link.egg_fragment:
                final_format = "{{0}}#egg={0}".format(base_link.egg_fragment)
            else:
                final_format = "{0}"
            base = final_format.format(self.vcs_uri)
        elif self._parsed_line is not None and (
            self._parsed_line.is_direct_url and self._parsed_line.line_with_prefix
        ):
            return self._parsed_line.line_with_prefix
        elif getattr(self, "_base_line", None) and (isinstance(self._base_line, str)):
            base = self._base_line
        else:
            base = getattr(self, "link", self.get_link()).url
        if base and self.extras and extras_to_string(self.extras) not in base:
            if self.subdirectory:
                base = "{0}".format(self.get_link().url)
            else:
                base = "{0}{1}".format(base, extras_to_string(sorted(self.extras)))
        if "git+file:/" in base and "git+file:///" not in base:
            base = base.replace("git+file:/", "git+file:///")
        if self.editable and not base.startswith("-e "):
            base = "-e {0}".format(base)
        return base

    @staticmethod
    def _choose_vcs_source(pipfile):
        # type: (Dict[S, Union[S, Any]]) -> Dict[S, Union[S, Any]]
        src_keys = [k for k in pipfile.keys() if k in ["path", "uri", "file"]]
        vcs_type = ""  # type: Optional[STRING_TYPE]
        alt_type = ""  # type: Optional[STRING_TYPE]
        vcs_value = ""  # type: STRING_TYPE
        if src_keys:
            chosen_key = next(iter(src_keys))
            vcs_type = pipfile.pop("vcs")
            if chosen_key in pipfile:
                vcs_value = pipfile[chosen_key]
                alt_type, pipfile_url = split_vcs_method_from_uri(vcs_value)
                if vcs_type is None:
                    vcs_type = alt_type
            if vcs_type and pipfile_url:
                pipfile[vcs_type] = pipfile_url
            for removed in src_keys:
                pipfile.pop(removed)
        return pipfile

    @property
    def pipfile_part(self):
        # type: () -> Dict[S, Dict[S, Union[List[S], S, bool, RequirementType, Link]]]
        excludes = [
            "_repo",
            "_base_line",
            "setup_path",
            "_has_hashed_name",
            "pyproject_path",
            "pyproject_requires",
            "pyproject_backend",
            "_setup_info",
            "_parsed_line",
            "_uri_scheme",
        ]
        filter_func = lambda k, v: bool(v) is True and k.name not in excludes  # noqa
        pipfile_dict = attr.asdict(self, filter=filter_func).copy()
        name = pipfile_dict.pop("name", None)
        if name is None:
            if self.name:
                name = self.name
            elif self.parsed_line and self.parsed_line.name:
                name = self.name = self.parsed_line.name
            elif self.setup_info and self.setup_info.name:
                name = self.name = self.setup_info.name
        if "vcs" in pipfile_dict:
            pipfile_dict = self._choose_vcs_source(pipfile_dict)
        name, _ = _strip_extras(name)
        return {name: pipfile_dict}  # type: ignore


@attr.s(eq=True, order=True, hash=True)
class Requirement(object):
    _name = attr.ib(eq=True, order=True)  # type: STRING_TYPE
    vcs = attr.ib(
        default=None,
        validator=attr.validators.optional(validate_vcs),
        eq=True,
        order=True,
    )  # type: Optional[STRING_TYPE]
    req = attr.ib(
        default=None, eq=True, order=True
    )  # type: Optional[Union[VCSRequirement, FileRequirement, NamedRequirement]]
    markers = attr.ib(default=None, eq=True, order=True)  # type: Optional[STRING_TYPE]
    _specifiers = attr.ib(
        validator=attr.validators.optional(validate_specifiers), eq=True, order=True
    )  # type: Optional[STRING_TYPE]
    index = attr.ib(default=None, eq=True, order=True)  # type: Optional[STRING_TYPE]
    editable = attr.ib(default=None, eq=True, order=True)  # type: Optional[bool]
    hashes = attr.ib(
        factory=frozenset, converter=frozenset, eq=True, order=True
    )  # type: FrozenSet[STRING_TYPE]
    extras = attr.ib(factory=tuple, eq=True, order=True)  # type: Tuple[STRING_TYPE, ...]
    abstract_dep = attr.ib(
        default=None, eq=False, order=False
    )  # type: Optional[AbstractDependency]
    _line_instance = attr.ib(default=None, eq=False, order=False)  # type: Optional[Line]
    _ireq = attr.ib(
        default=None, eq=False, order=False
    )  # type: Optional[InstallRequirement]

    def __hash__(self):
        return hash(self.as_line())

    @_name.default
    def get_name(self):
        # type: () -> Optional[STRING_TYPE]
        if self.req is not None:
            return self.req.name
        return None

    @property
    def name(self):
        # type: () -> Optional[STRING_TYPE]
        if self._name is not None:
            return self._name
        name = None
        if self.req and self.req.name:
            name = self.req.name
        elif self.req and self.is_file_or_url and self.req.setup_info:
            name = self.req.setup_info.name
        self._name = name
        return name

    @property
    def requirement(self):
        # type: () -> Optional[PackagingRequirement]
        if self.req:
            return self.req.req
        return None

    def add_hashes(self, hashes):
        # type: (Union[S, List[S], Set[S], Tuple[S, ...]]) -> Requirement
        new_hashes = set()  # type: Set[STRING_TYPE]
        if self.hashes is not None:
            new_hashes |= set(self.hashes)
        if isinstance(hashes, str):
            new_hashes.add(hashes)
        else:
            new_hashes |= set(hashes)
        return attr.evolve(self, hashes=tuple(new_hashes))

    def get_hashes_as_pip(self, as_list=False):
        # type: (bool) -> Union[STRING_TYPE, List[STRING_TYPE]]
        hashes = ""  # type: Union[STRING_TYPE, List[STRING_TYPE]]
        if as_list:
            hashes = []
            if self.hashes:
                hashes = [HASH_STRING.format(h) for h in self.hashes]
        else:
            hashes = ""
            if self.hashes:
                hashes = "".join([HASH_STRING.format(h) for h in self.hashes])
        return hashes

    @property
    def hashes_as_pip(self):
        # type: () -> STRING_TYPE
        hashes = self.get_hashes_as_pip()
        assert isinstance(hashes, str)
        return hashes

    @property
    def markers_as_pip(self):
        # type: () -> S
        if self.markers:
            return " ; {0}".format(self.markers).replace('"', "'")

        return ""

    @property
    def extras_as_pip(self):
        # type: () -> STRING_TYPE
        if self.extras:
            return "[{0}]".format(
                ",".join(sorted([extra.lower() for extra in self.extras]))  # type: ignore
            )

        return ""

    @cached_property
    def commit_hash(self):
        # type: () -> Optional[S]
        if self.req is None or not isinstance(self.req, VCSRequirement):
            return None
        commit_hash = None
        if self.req is not None:
            with self.req.locked_vcs_repo() as repo:
                commit_hash = repo.get_commit_hash()
        return commit_hash

    @_specifiers.default
    def get_specifiers(self):
        # type: () -> S
        if self.req and self.req.req and self.req.req.specifier:
            return specs_to_string(self.req.req.specifier)
        return ""

    def update_name_from_path(self, path):
        metadata = get_metadata(path)
        name = self.name
        if metadata is not None:
            metadata_name = metadata.get("name")
            if metadata_name and metadata_name != "wheel":
                name = metadata_name
        if name is not None:
            if self.req.name is None:
                self.req.name = name
            if self.req.req and self.req.req.name is None:
                self.req.req.name = name
            if self._line_instance._name is None:
                self._line_instance.name = name
            if self.req._parsed_line._name is None:
                self.req._parsed_line.name = name
            if self.req._setup_info and self.req._setup_info.name is None:
                self.req._setup_info.name = name

    def get_line_instance(self):
        # type: () -> Line
        line_parts = []
        local_editable = False
        if self.req:
            if self.req.line_part.startswith("-e "):
                local_editable = True
                line_parts.extend(self.req.line_part.split(" ", 1))
            else:
                line_parts.append(self.req.line_part)
        if not self.is_vcs and not self.vcs and self.extras_as_pip:
            if (
                self.is_file_or_url
                and not local_editable
                and not self.req.get_uri().startswith("file://")
                # fix for file uri with egg names and extras
                and not len(self.req.line_part.split("#")) > 1
            ):
                line_parts.append(f"#egg={self._name}{self.extras_as_pip}")
            else:
                line_parts.append(self.extras_as_pip)
        if self._specifiers and not (self.is_file_or_url or self.is_vcs):
            line_parts.append(self._specifiers)
        if self.markers:
            line_parts.append(" ; {0}".format(self.markers.replace('"', "'")))
        if self.hashes_as_pip and not (self.editable or self.vcs or self.is_vcs):
            line_parts.append(self.hashes_as_pip)
        if self.editable:
            if line_parts[0] == "-e":
                line = "".join(line_parts[1:])
            else:
                line = "".join(line_parts)
            if self.markers:
                line = '"{0}"'.format(line)
            line = "-e {0}".format(line)
        else:
            line = "".join(line_parts)
        return Line(line)

    @property
    def line_instance(self):
        # type: () -> Optional[Line]
        if self._line_instance is None:
            self.line_instance = self.get_line_instance()
        return self._line_instance

    @line_instance.setter
    def line_instance(self, line_instance):
        # type: (Line) -> None
        if self.req:
            self.req._parsed_line = line_instance
        self._line_instance = line_instance

    @property
    def specifiers(self):
        # type: () -> Optional[STRING_TYPE]
        if self._specifiers:
            return self._specifiers
        else:
            specs = self.get_specifiers()
            if specs:
                self._specifiers = specs
                return specs
        if not self._specifiers and (
            self.req is not None
            and isinstance(self.req, NamedRequirement)
            and self.req.version
        ):
            self._specifiers = self.req.version
        elif (
            not self.editable
            and self.req
            and (not isinstance(self.req, NamedRequirement) and self.req.setup_info)
        ):
            if (
                self.line_instance
                and self.line_instance.setup_info
                and self.line_instance.setup_info.version
            ):
                self._specifiers = "=={0}".format(self.req.setup_info.version)
        elif not self._specifiers:
            if self.req and self.req.parsed_line and self.req.parsed_line.specifiers:
                self._specifiers = specs_to_string(self.req.parsed_line.specifiers)
            elif self.line_instance and self.line_instance.specifiers:
                self._specifiers = specs_to_string(self.line_instance.specifiers)
            elif self.is_file_or_url or self.is_vcs:
                try:
                    setupinfo_dict = self.run_requires()
                except Exception:
                    setupinfo_dict = None
                if setupinfo_dict is not None:
                    self._specifiers = "=={0}".format(setupinfo_dict.get("version"))
        if self._specifiers:
            specset = SpecifierSet(self._specifiers)
            if self.line_instance and not self.line_instance.specifiers:
                self.line_instance.specifiers = specset
            if self.req:
                if self.req._parsed_line and not self.req._parsed_line.specifiers:
                    self.req._parsed_line.specifiers = specset
                elif not self.req._parsed_line and self.line_instance:
                    self.req._parsed_line = self.line_instance
            if self.req and self.req.req and not self.req.req.specifier:
                self.req.req.specifier = specset
        return self._specifiers

    @property
    def is_vcs(self):
        # type: () -> bool
        return isinstance(self.req, VCSRequirement)

    @property
    def build_backend(self):
        # type: () -> Optional[STRING_TYPE]
        if self.req is not None and (
            not isinstance(self.req, NamedRequirement) and self.req.is_local
        ):
            with global_tempdir_manager():
                setup_info = self.run_requires()
            build_backend = setup_info.get("build_backend")
            return build_backend
        return "setuptools.build_meta"

    @property
    def uses_pep517(self):
        # type: () -> bool
        if self.build_backend:
            return True
        return False

    @property
    def is_file_or_url(self):
        # type: () -> bool
        return isinstance(self.req, FileRequirement)

    @property
    def is_named(self):
        # type: () -> bool
        return isinstance(self.req, NamedRequirement)

    @property
    def is_wheel(self):
        # type: () -> bool
        if (
            self.req
            and not isinstance(self.req, NamedRequirement)
            and (self.req.link is not None and self.req.link.is_wheel)
        ):
            return True
        return False

    @property
    def normalized_name(self):
        # type: () -> S
        return canonicalize_name(self.name)

    def copy(self):
        return attr.evolve(self)

    @classmethod
    @lru_cache()
    def from_line(cls, line):
        # type: (AnyStr) -> Requirement
        if isinstance(line, InstallRequirement):
            line = format_requirement(line)
        parsed_line = Line(line)
        r = (
            None
        )  # type: Optional[Union[VCSRequirement, FileRequirement, NamedRequirement]]
        if (
            (parsed_line.is_file and parsed_line.is_installable)
            or parsed_line.is_remote_url
        ) and not parsed_line.is_vcs:
            r = file_req_from_parsed_line(parsed_line)
        elif parsed_line.is_vcs:
            r = vcs_req_from_parsed_line(parsed_line)
        elif line == "." and not is_installable_file(line):
            raise RequirementError(
                "Error parsing requirement %s -- are you sure it is installable?" % line
            )
        else:
            r = named_req_from_parsed_line(parsed_line)
        req_markers = None
        if parsed_line.markers:
            req_markers = PackagingRequirement(
                "fakepkg ; {0}".format(parsed_line.markers)
            )
        if r is not None and r.req is not None:
            r.req.marker = getattr(req_markers, "marker", None) if req_markers else None
        args = {}  # type: Dict[STRING_TYPE, CREATION_ARG_TYPES]
        args = {
            "name": r.name,
            "vcs": parsed_line.vcs,
            "req": r,
            "markers": parsed_line.markers,
            "editable": parsed_line.editable,
            "line_instance": parsed_line,
        }
        if parsed_line.extras:
            extras = ()  # type: Tuple[STRING_TYPE, ...]
            extras = tuple(sorted(dedup([extra.lower() for extra in parsed_line.extras])))
            args["extras"] = extras
            if r is not None:
                r.extras = extras
            elif r is not None and r.extras is not None:
                args["extras"] = tuple(
                    sorted(dedup([extra.lower() for extra in r.extras]))
                )  # type: ignore
            if r.req is not None:
                r.req.extras = args["extras"]
        if parsed_line.hashes:
            args["hashes"] = tuple(parsed_line.hashes)  # type: ignore
        cls_inst = cls(**args)  # type: ignore
        return cls_inst

    @classmethod
    def from_ireq(cls, ireq):
        return cls.from_line(format_requirement(ireq))

    @classmethod
    def from_metadata(cls, name, version, extras, markers):
        return cls.from_ireq(
            make_install_requirement(name, version, extras=extras, markers=markers)
        )

    @classmethod
    def from_pipfile(cls, name, pipfile):
        from .markers import PipenvMarkers

        _pipfile = {}
        if hasattr(pipfile, "keys"):
            _pipfile = dict(pipfile).copy()
        _pipfile["version"] = get_version(pipfile)
        vcs = next(iter([vcs for vcs in VCS_LIST if vcs in _pipfile]), None)
        if vcs:
            _pipfile["vcs"] = vcs
            r = VCSRequirement.from_pipfile(name, pipfile)
        elif any(key in _pipfile for key in ["path", "file", "uri"]):
            r = FileRequirement.from_pipfile(name, pipfile)
        else:
            r = NamedRequirement.from_pipfile(name, pipfile)
        markers = PipenvMarkers.from_pipfile(name, _pipfile)
        req_markers = None
        if markers:
            markers = str(markers)
            req_markers = PackagingRequirement("fakepkg ; {0}".format(markers))
            if r.req is not None:
                r.req.marker = req_markers.marker
        extras = _pipfile.get("extras")
        if r.req:
            if r.req.specifier:
                r.req.specifier = SpecifierSet(_pipfile["version"])
            r.req.extras = (
                tuple(sorted(dedup([extra.lower() for extra in extras])))
                if extras
                else ()
            )
        args = {
            "name": r.name,
            "vcs": vcs,
            "req": r,
            "markers": markers,
            "extras": tuple(_pipfile.get("extras", ())),
            "editable": _pipfile.get("editable", False),
            "index": _pipfile.get("index"),
        }
        if any(key in _pipfile for key in ["hash", "hashes"]):
            args["hashes"] = _pipfile.get("hashes", [pipfile.get("hash")])
        cls_inst = cls(**args)
        return cls_inst

    def as_line(
        self,
        sources=None,
        include_hashes=True,
        include_extras=True,
        include_markers=True,
        as_list=False,
    ):
        """Format this requirement as a line in requirements.txt.

        If ``sources`` provided, it should be an sequence of mappings, containing
        all possible sources to be used for this requirement.

        If ``sources`` is omitted or falsy, no index information will be included
        in the requirement line.
        """

        assert self.line_instance is not None
        parts = self.line_instance.get_line(
            with_prefix=True,
            with_hashes=include_hashes,
            with_markers=include_markers,
            as_list=as_list,
        )
        if sources and self.requirement and not (self.line_instance.is_local or self.vcs):
            from ..utils import prepare_pip_source_args

            if self.index:
                sources = [s for s in sources if s.get("name") == self.index]
            source_list = prepare_pip_source_args(sources)
            if as_list:
                parts.extend(sources)
            else:
                index_string = " ".join(source_list)
                parts = "{0} {1}".format(parts, index_string)
        return parts

    def get_markers(self):
        # type: () -> Marker
        markers = self.markers
        if markers:
            fake_pkg = PackagingRequirement("fakepkg ; {0}".format(markers))
            markers = fake_pkg.marker
        return markers

    def get_specifier(self):
        # type: () -> Union[SpecifierSet, LegacySpecifier]
        try:
            return Specifier(self.specifiers)
        except InvalidSpecifier:
            return LegacySpecifier(self.specifiers)

    def get_version(self):
        return parse(self.get_specifier().version)

    def get_requirement(self):
        req_line = self.req.req.line
        if req_line.startswith("-e "):
            _, req_line = req_line.split(" ", 1)
        req = init_requirement(self.name)
        req.line = req_line
        req.specifier = SpecifierSet(self.specifiers if self.specifiers else "")
        if self.is_vcs or self.is_file_or_url:
            req.url = getattr(self.req.req, "url", self.req.link.url_without_fragment)
        req.marker = self.get_markers()
        req.extras = set(self.extras) if self.extras else set()
        return req

    @property
    def constraint_line(self):
        return self.as_line()

    @property
    def is_direct_url(self):
        return (
            self.is_file_or_url
            and self.req.is_direct_url
            or (self.line_instance.is_direct_url or self.req.parsed_line.is_direct_url)
        )

    def as_pipfile(self):
        good_keys = (
            "hashes",
            "extras",
            "markers",
            "editable",
            "version",
            "index",
        ) + VCS_LIST
        req_dict = {
            k: v
            for k, v in attr.asdict(self, recurse=False, filter=filter_none).items()
            if k in good_keys
        }
        name = self.name
        if "markers" in req_dict and req_dict["markers"]:
            req_dict["markers"] = req_dict["markers"].replace('"', "'")
        if not self.req.name:
            name_carriers = (self.req, self, self.line_instance, self.req.parsed_line)
            name_options = [
                getattr(carrier, "name", None)
                for carrier in name_carriers
                if carrier is not None
            ]
            req_name = next(iter(n for n in name_options if n is not None), None)
            self.req.name = req_name
        req_name, dict_from_subreq = self.req.pipfile_part.popitem()
        base_dict = {
            k: v
            for k, v in dict_from_subreq.items()
            if k not in ["req", "link", "_setup_info"]
        }
        base_dict.update(req_dict)
        conflicting_keys = ("file", "path", "uri")
        if "file" in base_dict and any(k in base_dict for k in conflicting_keys[1:]):
            conflicts = [k for k in (conflicting_keys[1:],) if k in base_dict]
            for k in conflicts:
                base_dict.pop(k)
        if "hashes" in base_dict:
            _hashes = base_dict.pop("hashes")
            hashes = []
            for _hash in _hashes:
                try:
                    hashes.append(_hash.as_line())
                except AttributeError:
                    hashes.append(_hash)
            base_dict["hashes"] = sorted(hashes)
        if "extras" in base_dict:
            base_dict["extras"] = list(base_dict["extras"])
        if len(base_dict.keys()) == 1 and "version" in base_dict:
            base_dict = base_dict.get("version")
        return {name: base_dict}

    def as_ireq(self):
        if self.line_instance and self.line_instance.ireq:
            return self.line_instance.ireq
        elif getattr(self.req, "_parsed_line", None) and self.req._parsed_line.ireq:
            return self.req._parsed_line.ireq
        kwargs = {"include_hashes": False}
        if (self.is_file_or_url and self.req.is_local) or self.is_vcs:
            kwargs["include_markers"] = False
        ireq_line = self.as_line(**kwargs)
        ireq = Line(ireq_line).ireq
        if not getattr(ireq, "req", None):
            ireq.req = self.req.req
            if (self.is_file_or_url and self.req.is_local) or self.is_vcs:
                if getattr(ireq, "req", None) and getattr(ireq.req, "marker", None):
                    ireq.req.marker = None
        else:
            ireq.req.extras = self.req.req.extras
            if not ((self.is_file_or_url and self.req.is_local) or self.is_vcs):
                ireq.req.marker = self.req.req.marker
        return ireq

    @property
    def pipfile_entry(self):
        return self.as_pipfile().copy().popitem()

    @property
    def ireq(self):
        return self.as_ireq()

    def dependencies(self, sources=None):
        """Retrieve the dependencies of the current requirement.

        Retrieves dependencies of the current requirement.  This only works on pinned
        requirements.

        :param sources: Pipfile-formatted sources, defaults to None
        :param sources: list[dict], optional
        :return: A set of requirement strings of the dependencies of this requirement.
        :rtype: set(str)
        """
        if not sources:
            sources = [
                {"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}
            ]
        return get_dependencies(self.as_ireq(), sources=sources)

    def abstract_dependencies(self, sources=None):
        """Retrieve the abstract dependencies of this requirement.

        Returns the abstract dependencies of the current requirement in order to resolve.

        :param sources: A list of sources (pipfile format), defaults to None
        :param sources: list, optional
        :return: A list of abstract (unpinned) dependencies
        :rtype: list[ :class:`~requirementslib.models.dependency.AbstractDependency` ]
        """

        if not self.abstract_dep:
            parent = getattr(self, "parent", None)
            self.abstract_dep = AbstractDependency.from_requirement(self, parent=parent)
        if not sources:
            sources = [
                {"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}
            ]
        if is_pinned_requirement(self.ireq):
            deps = self.dependencies()
        else:
            ireq = sorted(self.find_all_matches(), key=lambda k: k.version)
            deps = get_dependencies(ireq.pop())
        return get_abstract_dependencies(deps, parent=self.abstract_dep)

    def find_all_matches(self, sources=None, finder=None):
        # type: (Optional[List[Dict[S, Union[S, bool]]]], Optional[PackageFinder]) -> List[InstallationCandidate]
        """Find all matching candidates for the current requirement.

        Consults a finder to find all matching candidates.

        :param sources: Pipfile-formatted sources, defaults to None
        :param sources: list[dict], optional
        :param PackageFinder finder: A **PackageFinder** instance from pip's repository implementation
        :return: A list of Installation Candidates
        :rtype: list[ :class:`~pipenv.patched.pip._internal.index.InstallationCandidate` ]
        """

        from .dependencies import find_all_matches, get_finder

        if not finder:
            _, finder = get_finder(sources=sources)
        return find_all_matches(finder, self.as_ireq())

    def run_requires(self, sources=None, finder=None):
        if self.req and self.req.setup_info is not None:
            info_dict = self.req.setup_info.as_dict()
        elif self.line_instance and self.line_instance.setup_info is not None:
            info_dict = self.line_instance.setup_info.as_dict()
        else:

            if not finder:
                from .dependencies import get_finder

                finder = get_finder(sources=sources)
            with global_tempdir_manager():
                info = SetupInfo.from_requirement(self, finder=finder)
                if info is None:
                    return {}
                info_dict = info.get_info()
            if self.req and not self.req.setup_info:
                self.req._setup_info = info
        if self.req._has_hashed_name and info_dict.get("name"):
            self.req.name = self.name = info_dict["name"]
            if self.req.req.name != info_dict["name"]:
                self.req.req.name = info_dict["name"]
        return info_dict

    def merge_markers(self, markers):
        # type: (Union[AnyStr, Marker]) -> None
        if not markers:
            return self
        if not isinstance(markers, Marker):
            markers = Marker(markers)
        _markers = []  # type: List[Marker]
        ireq = self.as_ireq()
        if ireq and ireq.markers:
            ireq_marker = ireq.markers
            _markers.append(str(ireq_marker))
        _markers.append(str(markers))
        marker_str = " and ".join([normalize_marker_str(m) for m in _markers if m])
        new_marker = Marker(marker_str)
        line = copy.deepcopy(self._line_instance)
        line.markers = marker_str
        line.parsed_marker = new_marker
        if getattr(line, "_requirement", None) is not None:
            line._requirement.marker = new_marker
        if getattr(line, "_ireq", None) is not None and line._ireq.req:
            line._ireq.req.marker = new_marker
        new_ireq = getattr(self, "ireq", None)
        if new_ireq and new_ireq.req:
            new_ireq.req.marker = new_marker
        req = self.req
        if req.req:
            req_requirement = req.req
            req_requirement.marker = new_marker
            req = attr.evolve(req, req=req_requirement, parsed_line=line)
        return attr.evolve(
            self, markers=str(new_marker), ireq=new_ireq, req=req, line_instance=line
        )


def file_req_from_parsed_line(parsed_line):
    # type: (Line) -> FileRequirement
    path = parsed_line.relpath if parsed_line.relpath else parsed_line.path
    pyproject_requires = None  # type: Optional[Tuple[STRING_TYPE, ...]]
    if parsed_line.pyproject_requires is not None:
        pyproject_requires = tuple(parsed_line.pyproject_requires)
    pyproject_path = (
        Path(parsed_line.pyproject_toml) if parsed_line.pyproject_toml else None
    )
    req_dict = {
        "setup_path": parsed_line.setup_py,
        "path": path,
        "editable": parsed_line.editable,
        "extras": parsed_line.extras,
        "uri_scheme": parsed_line.preferred_scheme,
        "link": parsed_line.link,
        "uri": parsed_line.uri,
        "pyproject_requires": pyproject_requires,
        "pyproject_backend": parsed_line.pyproject_backend,
        "pyproject_path": pyproject_path,
        "parsed_line": parsed_line,
        "req": parsed_line.requirement,
    }
    if parsed_line.name is not None:
        req_dict["name"] = parsed_line.name
    return FileRequirement(**req_dict)  # type: ignore


def vcs_req_from_parsed_line(parsed_line):
    # type: (Line) -> VCSRequirement
    line = "{0}".format(parsed_line.line)
    if parsed_line.editable:
        line = "-e {0}".format(line)
    if parsed_line.url is not None:
        link = create_link(
            build_vcs_uri(
                vcs=parsed_line.vcs,
                uri=parsed_line.url,
                name=parsed_line.name,
                ref=parsed_line.ref,
                subdirectory=parsed_line.subdirectory,
                extras=list(parsed_line.extras),
            )
        )
    else:
        link = parsed_line.link
    pyproject_requires = ()  # type: Optional[Tuple[STRING_TYPE, ...]]
    if parsed_line.pyproject_requires is not None:
        pyproject_requires = tuple(parsed_line.pyproject_requires)
    vcs_dict = {
        "setup_path": parsed_line.setup_py,
        "path": parsed_line.path,
        "editable": parsed_line.editable,
        "vcs": parsed_line.vcs,
        "ref": parsed_line.ref,
        "subdirectory": parsed_line.subdirectory,
        "extras": parsed_line.extras,
        "uri_scheme": parsed_line.preferred_scheme,
        "link": link,
        "uri": parsed_line.uri,
        "pyproject_requires": pyproject_requires,
        "pyproject_backend": parsed_line.pyproject_backend,
        "pyproject_path": Path(parsed_line.pyproject_toml)
        if parsed_line.pyproject_toml
        else None,
        "parsed_line": parsed_line,
        "req": parsed_line.requirement,
        "base_line": line,
    }
    if parsed_line.name:
        vcs_dict["name"] = parsed_line.name
    return VCSRequirement(**vcs_dict)  # type: ignore


def named_req_from_parsed_line(parsed_line):
    # type: (Line) -> NamedRequirement
    if parsed_line.name is not None:
        return NamedRequirement(
            name=parsed_line.name,
            version=parsed_line.specifier,
            req=parsed_line.requirement,
            extras=parsed_line.extras,
            editable=parsed_line.editable,
            parsed_line=parsed_line,
        )
    return NamedRequirement.from_line(parsed_line.line)


if __name__ == "__main__":
    line = Line("vistir@ git+https://github.com/sarugaku/vistir.git@master")
    print(line)
