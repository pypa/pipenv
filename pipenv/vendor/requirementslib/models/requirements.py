# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function

import collections
import copy
import hashlib
import os

from contextlib import contextmanager
from functools import partial

import attr
import pep517
import pep517.wrappers
import pip_shims
import vistir

from first import first
from packaging.markers import Marker
from packaging.requirements import Requirement as PackagingRequirement
from packaging.specifiers import Specifier, SpecifierSet, LegacySpecifier, InvalidSpecifier
from packaging.utils import canonicalize_name
from six.moves.urllib import parse as urllib_parse
from six.moves.urllib.parse import unquote
from vistir.compat import Path
from vistir.misc import dedup
from vistir.path import (
    create_tracked_tempdir,
    get_converted_relative_path,
    is_file_url,
    is_valid_url,
    normalize_path,
    mkdir_p
)

from ..exceptions import RequirementError
from ..utils import (
    VCS_LIST,
    is_installable_file,
    is_vcs,
    ensure_setup_py,
    add_ssh_scheme_to_git_uri,
    strip_ssh_from_git_uri,
    get_setup_paths
)
from .setup_info import SetupInfo, _prepare_wheel_building_kwargs
from .utils import (
    HASH_STRING,
    build_vcs_uri,
    extras_to_string,
    filter_none,
    format_requirement,
    get_version,
    init_requirement,
    is_pinned_requirement,
    make_install_requirement,
    parse_extras,
    specs_to_string,
    split_markers_from_line,
    split_vcs_method_from_uri,
    validate_path,
    validate_specifiers,
    validate_vcs,
    normalize_name,
    create_link,
    get_pyproject,
)

from ..environment import MYPY_RUNNING

if MYPY_RUNNING:
    from typing import Optional, TypeVar, List, Dict, Union, Any, Tuple, NoReturn
    from pip_shims.shims import Link, InstallRequirement
    RequirementType = TypeVar('RequirementType', covariant=True, bound=PackagingRequirement)
    from six.moves.urllib.parse import SplitResult
    from .vcs import VCSRepository


SPECIFIERS_BY_LENGTH = sorted(list(Specifier._operators.keys()), key=len, reverse=True)


run = partial(vistir.misc.run, combine_stderr=False, return_object=True, nospin=True)


class Line(object):
    def __init__(self, line):
        # type: (str) -> None
        self.editable = line.startswith("-e ")
        if self.editable:
            line = line[len("-e "):]
        self.line = line
        self.hashes = []  # type: List[str]
        self.extras = []  # type: List[str]
        self.markers = None  # type: Optional[str]
        self.vcs = None  # type: Optional[str]
        self.path = None  # type: Optional[str]
        self.relpath = None  # type: Optional[str]
        self.uri = None  # type: Optional[str]
        self._link = None  # type: Optional[Link]
        self.is_local = False
        self.name = None  # type: Optional[str]
        self.specifier = None  # type: Optional[str]
        self.parsed_marker = None  # type: Optional[Marker]
        self.preferred_scheme = None  # type: Optional[str]
        self.requirement = None  # type: Optional[PackagingRequirement]
        self._parsed_url = None  # type: Optional[urllib_parse.ParseResult]
        self._setup_cfg = None  # type: Optional[str]
        self._setup_py = None  # type: Optional[str]
        self._pyproject_toml = None  # type: Optional[str]
        self._pyproject_requires = None  # type: Optional[List[str]]
        self._pyproject_backend = None  # type: Optional[str]
        self._wheel_kwargs = None  # type: Dict[str, str]
        self._vcsrepo = None  # type: Optional[VCSRepository]
        self._ref = None  # type: Optional[str]
        self._ireq = None  # type: Optional[InstallRequirement]
        self._src_root = None  # type: Optional[str]
        self.dist = None  # type: Any
        super(Line, self).__init__()
        self.parse()

    @classmethod
    def split_hashes(cls, line):
        # type: (str) -> Tuple[str, List[str]]
        if "--hash" not in line:
            return line,  []
        split_line = line.split()
        line_parts = []  # type: List[str]
        hashes = []  # type: List[str]
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
        # type: () -> str
        if self.editable:
            return "-e {0}".format(self.line)
        return self.line

    @property
    def base_path(self):
        # type: () -> Optional[str]
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
        # type: () -> Optional[str]
        if self._setup_py is None:
            self.populate_setup_paths()
        return self._setup_py

    @property
    def setup_cfg(self):
        # type: () -> Optional[str]
        if self._setup_cfg is None:
            self.populate_setup_paths()
        return self._setup_cfg

    @property
    def pyproject_toml(self):
        # type: () -> Optional[str]
        if self._pyproject_toml is None:
            self.populate_setup_paths()
        return self._pyproject_toml

    def populate_setup_paths(self):
        # type: () -> None
        if not self.link and not self.path:
            self.parse_link()
        if not self.path:
            return
        base_path = self.base_path
        if base_path is None:
            return
        setup_paths = get_setup_paths(self.base_path, subdirectory=self.subdirectory)  # type: Dict[str, Optional[str]]
        self._setup_py = setup_paths.get("setup_py")
        self._setup_cfg = setup_paths.get("setup_cfg")
        self._pyproject_toml = setup_paths.get("pyproject_toml")

    @property
    def pyproject_requires(self):
        if self._pyproject_requires is None and self.pyproject_toml is not None:
            pyproject_requires, pyproject_backend = get_pyproject(self.path)
            self._pyproject_requires = pyproject_requires
            self._pyproject_backend = pyproject_backend
        return self._pyproject_requires

    @property
    def pyproject_backend(self):
        if self._pyproject_requires is None and self.pyproject_toml is not None:
            pyproject_requires, pyproject_backend = get_pyproject(self.path)
            if not pyproject_backend and self.setup_cfg is not None:
                setup_dict = SetupInfo.get_setup_cfg(self.setup_cfg)
                pyproject_backend = "setuptools.build_meta"
                pyproject_requires = setup_dict.get("build_requires", ["setuptools", "wheel"])

            self._pyproject_requires = pyproject_requires
            self._pyproject_backend = pyproject_backend
        return self._pyproject_backend

    def parse_hashes(self):
        # type: () -> None
        """
        Parse hashes from *self.line* and set them on the current object.
        :returns: Nothing
        :rtype: None
        """

        line, hashes = self.split_hashes(self.line)
        self.hashes = hashes
        self.line = line

    def parse_extras(self):
        # type: () -> None
        """
        Parse extras from *self.line* and set them on the current object
        :returns: Nothing
        :rtype: None
        """

        self.line, extras = pip_shims.shims._strip_extras(self.line)
        if extras is not None:
            self.extras = parse_extras(extras)

    def get_url(self):
        # type: () -> str
        """Sets ``self.name`` if given a **PEP-508** style URL"""

        line = self.line
        if self.vcs is not None and self.line.startswith("{0}+".format(self.vcs)):
            _, _, _parseable = self.line.partition("+")
            parsed = urllib_parse.urlparse(add_ssh_scheme_to_git_uri(_parseable))
        else:
            parsed = urllib_parse.urlparse(add_ssh_scheme_to_git_uri(line))
        if "@" in self.line and parsed.scheme == "":
            name, _, url = self.line.partition("@")
            if self.name is None:
                self.name = name
            line = url.strip()
            parsed = urllib_parse.urlparse(line)
        self._parsed_url = parsed
        return line

    @property
    def url(self):
        # type: () -> Optional[str]
        if self.uri is not None:
            url = add_ssh_scheme_to_git_uri(self.uri)
        url = getattr(self.link, "url_without_fragment", None)
        if url is not None:
            url = add_ssh_scheme_to_git_uri(unquote(url))
        if url is not None and self._parsed_url is None:
            if self.vcs is not None:
                _, _, _parseable = url.partition("+")
            self._parsed_url = urllib_parse.urlparse(_parseable)
        return url

    @property
    def link(self):
        # type: () -> Link
        if self._link is None:
            self.parse_link()
        return self._link

    @property
    def subdirectory(self):
        # type: () -> Optional[str]
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
        return self.link.is_artifact

    @property
    def is_vcs(self):
        # type: () -> bool
        # Installable local files and installable non-vcs urls are handled
        # as files, generally speaking
        if is_vcs(self.line) or is_vcs(self.get_url()):
            return True
        return False

    @property
    def is_url(self):
        # type: () -> bool
        url = self.get_url()
        if (is_valid_url(url) or is_file_url(url)):
            return True
        return False

    @property
    def is_path(self):
        # type: () -> bool
        if self.path and (
            self.path.startswith(".") or os.path.isabs(self.path) or
            os.path.exists(self.path)
        ):
            return True
        elif os.path.exists(self.line) or os.path.exists(self.get_url()):
            return True
        return False

    @property
    def is_file(self):
        # type: () -> bool
        if self.is_path or is_file_url(self.get_url()) or (self._parsed_url and self._parsed_url.scheme == "file"):
            return True
        return False

    @property
    def is_named(self):
        # type: () -> bool
        return not (self.is_file or self.is_url or self.is_vcs)

    @property
    def ref(self):
        # type: () -> Optional[str]
        if self._ref is None:
            if self.relpath and "@" in self.relpath:
                self._relpath, _, self._ref = self.relpath.rpartition("@")
        return self._ref

    @property
    def ireq(self):
        # type: () -> Optional[pip_shims.InstallRequirement]
        if self._ireq is None:
            self.parse_ireq()
        return self._ireq

    @property
    def is_installable(self):
        # type: () -> bool
        if is_installable_file(self.line) or is_installable_file(self.get_url()) or is_installable_file(self.path) or is_installable_file(self.base_path):
            return True
        return False

    def _get_vcsrepo(self):
        # type: () -> Optional[VCSRepository]
        from .vcs import VCSRepository
        checkout_directory = self.wheel_kwargs["src_dir"]  # type: ignore
        if self.name is not None:
            checkout_directory = os.path.join(checkout_directory, self.name)  # type: ignore
        vcsrepo = VCSRepository(
            url=self.link.url,
            name=self.name,
            ref=self.ref if self.ref else None,
            checkout_directory=checkout_directory,
            vcs_type=self.vcs,
            subdirectory=self.subdirectory,
        )
        if not self.link.scheme.startswith("file"):
            vcsrepo.obtain()
        return vcsrepo

    @property
    def vcsrepo(self):
        # type: () -> Optional[VCSRepository]
        if self._vcsrepo is None:
            self._vcsrepo = self._get_vcsrepo()
        return self._vcsrepo

    def get_ireq(self):
        # type: () -> InstallRequirement
        if self.is_named:
            ireq = pip_shims.shims.install_req_from_line(self.line)
        elif (self.is_file or self.is_url) and not self.is_vcs:
            line = self.line
            scheme = self.preferred_scheme if self.preferred_scheme is not None else "uri"
            if self.setup_py:
                line = os.path.dirname(os.path.abspath(self.setup_py))
            elif self.setup_cfg:
                line = os.path.dirname(os.path.abspath(self.setup_cfg))
            elif self.pyproject_toml:
                line = os.path.dirname(os.path.abspath(self.pyproject_toml))
            if scheme == "path":
                if not line and self.base_path is not None:
                    line = os.path.abspath(self.base_path)
                # if self.extras:
                    # line = pip_shims.shims.path_to_url(line)
            else:
                if self.link is not None:
                    line = self.link.url_without_fragment
                else:
                    if self.uri is not None:
                        line = self.uri
                    else:
                        line = self.path
            if self.extras:
                line = "{0}[{1}]".format(line, ",".join(sorted(set(self.extras))))
            if self.editable:
                ireq = pip_shims.shims.install_req_from_editable(self.link.url)
            else:
                ireq = pip_shims.shims.install_req_from_line(line)
        else:
            if self.editable:
                ireq = pip_shims.shims.install_req_from_editable(self.link.url)
            else:
                ireq = pip_shims.shims.install_req_from_line(self.link.url)
        if self.extras and not ireq.extras:
            ireq.extras = set(self.extras)
        if self.parsed_marker is not None and not ireq.markers:
            ireq.markers = self.parsed_marker
        return ireq

    def parse_ireq(self):
        # type: () -> None
        if self._ireq is None:
            self._ireq = self.get_ireq()
        # if self._ireq is not None:
        #     if self.requirement is not None and self._ireq.req is None:
        #         self._ireq.req = self.requirement

    def _parse_wheel(self):
        # type: () -> Optional[str]
        if not self.is_wheel:
            pass
        from pip_shims.shims import Wheel
        _wheel = Wheel(self.link.filename)
        name = _wheel.name
        version = _wheel.version
        self.specifier = "=={0}".format(version)
        return name

    def _parse_name_from_link(self):
        # type: () -> Optional[str]

        if getattr(self.link, "egg_fragment", None):
            return self.link.egg_fragment
        elif self.is_wheel:
            return self._parse_wheel()
        return None

    def _parse_name_from_line(self):
        # type: () -> Optional[str]

        if not self.is_named:
            pass
        name = self.line
        specifier_match = next(
            iter(spec for spec in SPECIFIERS_BY_LENGTH if spec in self.line), None
        )
        if specifier_match is not None:
            name, specifier_match, version = name.partition(specifier_match)
            self.specifier = "{0}{1}".format(specifier_match, version)
        return name

    def parse_name(self):
        # type: () -> None
        if self.name is None:
            name = None
            if self.link is not None:
                name = self._parse_name_from_link()
            if name is None and (
                (self.is_url or self.is_artifact or self.is_vcs) and self._parsed_url
            ):
                if self._parsed_url.fragment:
                    _, _, name = self._parsed_url.fragment.partition("egg=")
                    if "&" in name:
                        # subdirectory fragments might also be in here
                        name, _, _ = name.partition("&")
            if self.is_named and name is None:
                name = self._parse_name_from_line()
            if name is not None:
                name, extras = pip_shims.shims._strip_extras(name)
                if extras is not None and not self.extras:
                    self.extras = parse_extras(extras)
                self.name = name

    def _parse_requirement_from_vcs(self):
        # type: () -> Optional[PackagingRequirement]
        name = self.name if self.name else self.link.egg_fragment
        url = self.uri if self.uri else unquote(self.link.url)
        if not name:
            raise ValueError(
                "pipenv requires an #egg fragment for version controlled "
                "dependencies. Please install remote dependency "
                "in the form {0}#egg=<package-name>.".format(url)
            )
        req = init_requirement(canonicalize_name(name))  # type: PackagingRequirement
        req.editable = self.editable
        if not getattr(req, "url") and self.link:
            req.url = url
        req.line = self.link.url
        if (
            self.uri != unquote(self.link.url_without_fragment)
            and "git+ssh://" in self.link.url
            and (self.uri is not None and "git+git@" in self.uri)
        ):
            req.line = self.uri
            req.url = self.uri
        if self.ref:
            if self._vcsrepo is not None:
                req.revision = self._vcsrepo.get_commit_hash()
            else:
                req.revision = self.ref
        if self.extras:
            req.extras = self.extras
        req.vcs = self.vcs
        req.link = self.link
        if self.path and self.link and self.link.scheme.startswith("file"):
            req.local_file = True
            req.path = self.path
        return req

    def parse_requirement(self):
        # type: () -> None
        if self.name is None:
            self.parse_name()
        if self.is_named:
            self.requirement = init_requirement(self.line)
        elif self.is_vcs:
            self.requirement = self._parse_requirement_from_vcs()
            if self.name is None and (
                self.requirement is not None and self.requirement.name is not None
            ):
                self.name = self.requirement.name
        if self.name is not None and self.requirement is None:
            self.requirement = init_requirement(self.name)
        if self.requirement:
            if self.parsed_marker is not None:
                self.requirement.marker = self.parsed_marker
            if self.is_url or self.is_file and (self.link or self.url) and not self.is_vcs:
                if self.uri:
                    self.requirement.url = self.uri
                elif self.link:
                    self.requirement.url = unquote(self.link.url_without_fragment)
                else:
                    self.requirement.url = self.url
            if self.extras and not self.requirement.extras:
                self.requirement.extras = set(self.extras)

    def parse_link(self):
        # type: () -> None
        if self.is_file or self.is_url or self.is_vcs:
            vcs, prefer, relpath, path, uri, link = FileRequirement.get_link_from_line(self.line)
            ref = None
            if link is not None and "@" in link.path and uri is not None:
                uri, _, ref = uri.rpartition("@")
            if relpath is not None and "@" in relpath:
                relpath, _, ref = relpath.rpartition("@")
            self._ref = ref
            self.vcs = vcs
            self.preferred_scheme = prefer
            self.relpath = relpath
            self.path = path
            self.uri = uri
            self._link = link

    def parse_markers(self):
        # type: () -> None
        if self.markers:
            markers = PackagingRequirement("fakepkg; {0}".format(self.markers)).marker
            self.parsed_marker = markers

    def parse(self):
        # type: () -> None
        self.parse_hashes()
        self.line, self.markers = split_markers_from_line(self.line)
        self.parse_extras()
        self.line = self.line.strip('"').strip("'").strip()
        self.parse_markers()
        if self.is_file:
            self.populate_setup_paths()
        self.parse_link()
        self.parse_requirement()
        self.parse_ireq()

@attr.s(slots=True)
class NamedRequirement(object):
    name = attr.ib()  # type: str
    version = attr.ib(validator=attr.validators.optional(validate_specifiers))  # type: Optional[str]
    req = attr.ib()  # type: PackagingRequirement
    extras = attr.ib(default=attr.Factory(list))  # type: List[str]
    editable = attr.ib(default=False)  # type: bool

    @req.default
    def get_requirement(self):
        # type: () -> RequirementType
        req = init_requirement(
            "{0}{1}".format(canonicalize_name(self.name), self.version)
        )
        return req

    @classmethod
    def from_line(cls, line):
        # type: (str) -> NamedRequirement
        req = init_requirement(line)
        specifiers = None  # type: Optional[str]
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
        extras = None  # type: Optional[List[str]]
        if req.extras:
            extras = list(req.extras)
            return cls(name=name, version=specifiers, req=req, extras=extras)
        return cls(name=name, version=specifiers, req=req)

    @classmethod
    def from_pipfile(cls, name, pipfile):
        # type: (str, Dict[str, Union[str, Optional[str], Optional[List[str]]]]) -> NamedRequirement
        creation_args = {}  # type: Dict[str, Union[Optional[str], Optional[List[str]]]]
        if hasattr(pipfile, "keys"):
            attr_fields = [field.name for field in attr.fields(cls)]
            creation_args = {k: v for k, v in pipfile.items() if k in attr_fields}
        creation_args["name"] = name
        version = get_version(pipfile)  # type: Optional[str]
        extras = creation_args.get("extras", None)
        creation_args["version"] = version
        req = init_requirement("{0}{1}".format(name, version))
        if extras:
            req.extras += tuple(extras)
        creation_args["req"] = req
        return cls(**creation_args)  # type: ignore

    @property
    def line_part(self):
        # type: () -> str
        # FIXME: This should actually be canonicalized but for now we have to
        # simply lowercase it and replace underscores, since full canonicalization
        # also replaces dots and that doesn't actually work when querying the index
        return "{0}".format(normalize_name(self.name))

    @property
    def pipfile_part(self):
        # type: () -> Dict[str, Any]
        pipfile_dict = attr.asdict(self, filter=filter_none).copy()  # type: ignore
        if "version" not in pipfile_dict:
            pipfile_dict["version"] = "*"
        name = pipfile_dict.pop("name")
        return {name: pipfile_dict}


LinkInfo = collections.namedtuple(
    "LinkInfo", ["vcs_type", "prefer", "relpath", "path", "uri", "link"]
)


@attr.s(slots=True)
class FileRequirement(object):
    """File requirements for tar.gz installable files or wheels or setup.py
    containing directories."""

    #: Path to the relevant `setup.py` location
    setup_path = attr.ib(default=None)  # type: Optional[str]
    #: path to hit - without any of the VCS prefixes (like git+ / http+ / etc)
    path = attr.ib(default=None)  # type: Optional[str]
    #: Whether the package is editable
    editable = attr.ib(default=False)  # type: bool
    #: Extras if applicable
    extras = attr.ib(default=attr.Factory(list))  # type: List[str]
    _uri_scheme = attr.ib(default=None)  # type: Optional[str]
    #: URI of the package
    uri = attr.ib()  # type: Optional[str]
    #: Link object representing the package to clone
    link = attr.ib()  # type: Optional[Link]
    #: PyProject Requirements
    pyproject_requires = attr.ib(default=attr.Factory(list))  # type: List
    #: PyProject Build System
    pyproject_backend = attr.ib(default=None)  # type: Optional[str]
    #: PyProject Path
    pyproject_path = attr.ib(default=None)  # type: Optional[str]
    #: Setup metadata e.g. dependencies
    setup_info = attr.ib(default=None)  # type: SetupInfo
    _has_hashed_name = attr.ib(default=False)  # type: bool
    #: Package name
    name = attr.ib()  # type: Optional[str]
    #: A :class:`~pkg_resources.Requirement` isntance
    req = attr.ib()  # type: Optional[PackagingRequirement]

    @classmethod
    def get_link_from_line(cls, line):
        # type: (str) -> LinkInfo
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
        - `link` is an instance of :class:`pip._internal.index.Link`,
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
        fixed_line = add_ssh_scheme_to_git_uri(line)  # type: str
        added_ssh_scheme = fixed_line != line  # type: bool

        # We can assume a lot of things if this is a local filesystem path.
        if "://" not in fixed_line:
            p = Path(fixed_line).absolute()  # type: Path
            path = p.as_posix()  # type: Optional[str]
            uri = p.as_uri()  # type: str
            link = create_link(uri)  # type: Link
            relpath = None  # type: Optional[str]
            try:
                relpath = get_converted_relative_path(path)
            except ValueError:
                relpath = None
            return LinkInfo(None, "path", relpath, path, uri, link)

        # This is an URI. We'll need to perform some elaborated parsing.

        parsed_url = urllib_parse.urlsplit(fixed_line)  # type: SplitResult
        original_url = parsed_url._replace()  # type: SplitResult

        # Split the VCS part out if needed.
        original_scheme = parsed_url.scheme  # type: str
        vcs_type = None  # type: Optional[str]
        if "+" in original_scheme:
            scheme = None  # type: Optional[str]
            vcs_type, _, scheme = original_scheme.partition("+")
            parsed_url = parsed_url._replace(scheme=scheme)
            prefer = "uri"  # type: str
        else:
            vcs_type = None
            prefer = "file"

        if parsed_url.scheme == "file" and parsed_url.path:
            # This is a "file://" URI. Use url_to_path and path_to_url to
            # ensure the path is absolute. Also we need to build relpath.
            path = Path(
                pip_shims.shims.url_to_path(urllib_parse.urlunsplit(parsed_url))
            ).as_posix()
            try:
                relpath = get_converted_relative_path(path)
            except ValueError:
                relpath = None
            uri = pip_shims.shims.path_to_url(path)
        else:
            # This is a remote URI. Simply use it.
            path = None
            relpath = None
            # Cut the fragment, but otherwise this is fixed_line.
            uri = urllib_parse.urlunsplit(
                parsed_url._replace(scheme=original_scheme, fragment="")
            )

        if added_ssh_scheme:
            original_uri = urllib_parse.urlunsplit(
                original_url._replace(scheme=original_scheme, fragment="")
            )
            uri = strip_ssh_from_git_uri(original_uri)

        # Re-attach VCS prefix to build a Link.
        link = create_link(
            urllib_parse.urlunsplit(parsed_url._replace(scheme=original_scheme))
        )

        return LinkInfo(vcs_type, prefer, relpath, path, uri, link)

    @property
    def setup_py_dir(self):
        # type: () -> Optional[str]
        if self.setup_path:
            return os.path.dirname(os.path.abspath(self.setup_path))
        return None

    @property
    def dependencies(self):
        # type: () -> Tuple[Dict[str, PackagingRequirement], List[Union[str, PackagingRequirement]], List[str]]
        build_deps = []  # type: List[Union[str, PackagingRequirement]]
        setup_deps = []  # type: List[str]
        deps = {}  # type: Dict[str, PackagingRequirement]
        if self.setup_info:
            setup_info = self.setup_info.as_dict()
            deps.update(setup_info.get("requires", {}))
            setup_deps.extend(setup_info.get("setup_requires", []))
            build_deps.extend(setup_info.get("build_requires", []))
        if self.pyproject_requires:
            build_deps.extend(self.pyproject_requires)
        setup_deps = list(set(setup_deps))
        build_deps = list(set(build_deps))
        return deps, setup_deps, build_deps

    @uri.default
    def get_uri(self):
        # type: () -> str
        if self.path and not self.uri:
            self._uri_scheme = "path"
            return pip_shims.shims.path_to_url(os.path.abspath(self.path))
        elif getattr(self, "req", None) and self.req is not None and getattr(self.req, "url"):
            return self.req.url
        elif self.link is not None:
            return self.link.url_without_fragment
        return ""

    @name.default
    def get_name(self):
        # type: () -> str
        loc = self.path or self.uri
        if loc and not self._uri_scheme:
            self._uri_scheme = "path" if self.path else "file"
        name = None
        hashed_loc = hashlib.sha256(loc.encode("utf-8")).hexdigest()
        hashed_name = hashed_loc[-7:]
        if getattr(self, "req", None) and self.req is not None and getattr(self.req, "name") and self.req.name is not None:
            if self.is_direct_url and self.req.name != hashed_name:
                return self.req.name
        if self.link and self.link.egg_fragment and self.link.egg_fragment != hashed_name:
            return self.link.egg_fragment
        elif self.link and self.link.is_wheel:
            from pip_shims import Wheel
            self._has_hashed_name = False
            return Wheel(self.link.filename).name
        elif self.link and ((self.link.scheme == "file" or self.editable) or (
            self.path and self.setup_path and os.path.isfile(str(self.setup_path))
        )):
            _ireq = None
            if self.editable:
                line = pip_shims.shims.path_to_url(self.setup_py_dir)
                if self.extras:
                    line = "{0}[{1}]".format(line, ",".join(self.extras))
                _ireq = pip_shims.shims.install_req_from_editable(line)
            else:
                line = Path(self.setup_py_dir).as_posix()
                if self.extras:
                    line = "{0}[{1}]".format(line, ",".join(self.extras))
                _ireq = pip_shims.shims.install_req_from_line(line)
            if getattr(self, "req", None) is not None:
                _ireq.req = copy.deepcopy(self.req)
            if self.extras and _ireq and not _ireq.extras:
                _ireq.extras = set(self.extras)
            from .setup_info import SetupInfo
            subdir = getattr(self, "subdirectory", None)
            setupinfo = None
            if self.setup_info is not None:
                setupinfo = self.setup_info
            else:
                setupinfo = SetupInfo.from_ireq(_ireq, subdir=subdir)
            if setupinfo:
                self.setup_info = setupinfo
                setupinfo_dict = setupinfo.as_dict()
                setup_name = setupinfo_dict.get("name", None)
                if setup_name:
                    name = setup_name
                    self._has_hashed_name = False
                build_requires = setupinfo_dict.get("build_requires")
                build_backend = setupinfo_dict.get("build_backend")
                if build_requires and not self.pyproject_requires:
                    self.pyproject_requires = build_requires
                if build_backend and not self.pyproject_backend:
                    self.pyproject_backend = build_backend
        if not name or name.lower() == "unknown":
            self._has_hashed_name = True
            name = hashed_name
        name_in_link = getattr(self.link, "egg_fragment", "") if self.link else ""
        if not self._has_hashed_name and name_in_link != name and self.link is not None:
            self.link = create_link("{0}#egg={1}".format(self.link.url, name))
        if name is not None:
            return name
        return ""

    @link.default
    def get_link(self):
        # type: () -> Link
        target = "{0}".format(self.uri)
        if hasattr(self, "name") and not self._has_hashed_name:
            target = "{0}#egg={1}".format(target, self.name)
        link = create_link(target)
        return link

    @req.default
    def get_requirement(self):
        # type: () -> PackagingRequirement
        if self.name is None:
            raise ValueError("Failed to generate a requirement: missing name for {0!r}".format(self))
        req = init_requirement(normalize_name(self.name))
        req.editable = False
        if self.link is not None:
            req.line = self.link.url_without_fragment
        elif self.uri is not None:
            req.line = self.uri
        else:
            req.line = self.name
        if self.path and self.link and self.link.scheme.startswith("file"):
            req.local_file = True
            req.path = self.path
            if self.editable:
                req.url = None
            else:
                req.url = self.link.url_without_fragment
        else:
            req.local_file = False
            req.path = None
            req.url = self.link.url_without_fragment
        if self.editable:
            req.editable = True
        req.link = self.link
        return req

    @property
    def is_local(self):
        # type: () -> bool
        uri = getattr(self, "uri", None)
        if uri is None:
            if getattr(self, "path", None) and self.path is not None:
                uri = pip_shims.shims.path_to_url(os.path.abspath(self.path))
            elif getattr(self, "req", None) and self.req is not None and (
                getattr(self.req, "url") and self.req.url is not None
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
            any(
                self.link.scheme.startswith(scheme)
                for scheme in ("http", "https", "ftp", "ftps", "uri")
            )
            and (self.link.is_artifact or self.link.is_wheel)
            and not self.editable
        )

    @property
    def is_direct_url(self):
        # type: () -> bool
        return self.is_remote_artifact

    @property
    def formatted_path(self):
        # type: () -> Optional[str]
        if self.path:
            path = self.path
            if not isinstance(path, Path):
                path = Path(path)
            return path.as_posix()
        return None

    @classmethod
    def create(
        cls,
        path=None,  # type: Optional[str]
        uri=None,  # type: str
        editable=False,  # type: bool
        extras=None,  # type: Optional[List[str]]
        link=None,  # type: Link
        vcs_type=None,  # type: Optional[Any]
        name=None,  # type: Optional[str]
        req=None,  # type: Optional[Any]
        line=None,  # type: Optional[str]
        uri_scheme=None,  # type: str
        setup_path=None,  # type: Optional[Any]
        relpath=None,  # type: Optional[Any]
    ):
        # type: (...) -> FileRequirement
        parsed_line = None
        if line:
            parsed_line = Line(line)
        if relpath and not path:
            path = relpath
        if not path and uri and link is not None and link.scheme == "file":
            path = os.path.abspath(pip_shims.shims.url_to_path(unquote(uri)))
            try:
                path = get_converted_relative_path(path)
            except ValueError:  # Vistir raises a ValueError if it can't make a relpath
                path = path
        if line and not (uri_scheme and uri and link):
            vcs_type, uri_scheme, relpath, path, uri, link = cls.get_link_from_line(line)
        if not uri_scheme:
            uri_scheme = "path" if path else "file"
        if path and not uri:
            uri = unquote(pip_shims.shims.path_to_url(os.path.abspath(path)))
        if not link:
            link = cls.get_link_from_line(uri).link
        if not uri:
            uri = unquote(link.url_without_fragment)
        if not extras:
            extras = []
        pyproject_path = None
        if path is not None:
            pyproject_requires = get_pyproject(path)
        pyproject_backend = None
        pyproject_requires = None
        if pyproject_requires is not None:
            pyproject_requires, pyproject_backend = pyproject_requires
        if path:
            setup_paths = get_setup_paths(path)
            if setup_paths["pyproject_toml"] is not None:
                pyproject_path = Path(setup_paths["pyproject_toml"])
            if setup_paths["setup_py"] is not None:
                setup_path = Path(setup_paths["setup_py"]).as_posix()
        if setup_path and isinstance(setup_path, Path):
            setup_path = setup_path.as_posix()
        creation_kwargs = {
            "editable": editable,
            "extras": extras,
            "pyproject_path": pyproject_path,
            "setup_path": setup_path if setup_path else None,
            "uri_scheme": uri_scheme,
            "link": link,
            "uri": uri,
            "pyproject_requires": pyproject_requires,
            "pyproject_backend": pyproject_backend,
            "path": path or relpath,
        }
        if vcs_type:
            creation_kwargs["vcs"] = vcs_type
        if name:
            creation_kwargs["name"] = name
        _line = None
        ireq = None
        if not name or not parsed_line:
            if link is not None and link.url is not None:
                _line = unquote(link.url_without_fragment)
                if name:
                    _line = "{0}#egg={1}".format(_line, name)
                # if extras:
                #     _line = "{0}[{1}]".format(_line, ",".join(sorted(set(extras))))
            elif uri is not None:
                _line = uri
            else:
                _line = line
            if editable:
                if extras and (
                    (link and link.scheme == "file") or (uri and uri.startswith("file"))
                    or (not uri and not link)
                ):
                    _line = "{0}[{1}]".format(_line, ",".join(sorted(set(extras))))
                if ireq is None:
                    ireq = pip_shims.shims.install_req_from_editable(_line)
            else:
                _line = path if (uri_scheme and uri_scheme == "path") else _line
                if extras:
                    _line = "{0}[{1}]".format(_line, ",".join(sorted(set(extras))))
                if ireq is None:
                    ireq = pip_shims.shims.install_req_from_line(_line)
            if parsed_line is None:
                if editable:
                    _line = "-e {0}".format(editable)
                parsed_line = Line(_line)
            if ireq is None:
                ireq = parsed_line.ireq
            if extras and not ireq.extras:
                ireq.extras = set(extras)
            if not ireq.is_wheel:
                setup_info = SetupInfo.from_ireq(ireq)
                setupinfo_dict = setup_info.as_dict()
                setup_name = setupinfo_dict.get("name", None)
                if setup_name:
                    name = setup_name
                    build_requires = setupinfo_dict.get("build_requires", [])
                    build_backend = setupinfo_dict.get("build_backend", [])
                    if not creation_kwargs.get("pyproject_requires") and build_requires:
                        creation_kwargs["pyproject_requires"] = build_requires
                    if not creation_kwargs.get("pyproject_backend") and build_backend:
                        creation_kwargs["pyproject_backend"] = build_backend
                creation_kwargs["setup_info"] = setup_info
        if path or relpath:
            creation_kwargs["path"] = relpath if relpath else path
        if req is not None:
            creation_kwargs["req"] = req
        creation_req = creation_kwargs.get("req")
        if creation_kwargs.get("req") is not None:
            creation_req_line = getattr(creation_req, "line", None)
            if creation_req_line is None and line is not None:
                creation_kwargs["req"].line = line  # type: ignore
        if parsed_line.name:
            if name and len(parsed_line.name) != 7 and len(name) == 7:
                name = parsed_line.name
        if name:
            creation_kwargs["name"] = name
        cls_inst = cls(**creation_kwargs)  # type: ignore
        return cls_inst

    @classmethod
    def from_line(cls, line, extras=None):
        # type: (str, Optional[List[str]]) -> FileRequirement
        line = line.strip('"').strip("'")
        link = None
        path = None
        editable = line.startswith("-e ")
        line = line.split(" ", 1)[1] if editable else line
        setup_path = None
        name = None
        req = None
        if not extras:
            extras = []
        if not any([is_installable_file(line), is_valid_url(line), is_file_url(line)]):
            try:
                req = init_requirement(line)
            except Exception:
                raise RequirementError(
                    "Supplied requirement is not installable: {0!r}".format(line)
                )
            else:
                name = getattr(req, "name", None)
                line = getattr(req, "url", None)
        vcs_type, prefer, relpath, path, uri, link = cls.get_link_from_line(line)
        arg_dict = {
            "path": relpath if relpath else path,
            "uri": unquote(link.url_without_fragment),
            "link": link,
            "editable": editable,
            "setup_path": setup_path,
            "uri_scheme": prefer,
            "line": line,
            "extras": extras,
            # "name": name,
        }
        if req is not None:
            arg_dict["req"] = req
        if link and link.is_wheel:
            from pip_shims import Wheel

            arg_dict["name"] = Wheel(link.filename).name
        elif name:
            arg_dict["name"] = name
        elif link.egg_fragment:
            arg_dict["name"] = link.egg_fragment
        return cls.create(**arg_dict)

    @classmethod
    def from_pipfile(cls, name, pipfile):
        # type: (str, Dict[str, Any]) -> FileRequirement
        # Parse the values out. After this dance we should have two variables:
        # path - Local filesystem path.
        # uri - Absolute URI that is parsable with urlsplit.
        # One of these will be a string; the other would be None.
        uri = pipfile.get("uri")
        fil = pipfile.get("file")
        path = pipfile.get("path")
        if path:
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
            uri = pip_shims.shims.path_to_url(path)
        link = cls.get_link_from_line(uri).link
        arg_dict = {
            "name": name,
            "path": path,
            "uri": unquote(link.url_without_fragment),
            "editable": pipfile.get("editable", False),
            "link": link,
            "uri_scheme": uri_scheme,
            "extras": pipfile.get("extras", None)
        }

        extras = pipfile.get("extras", [])
        line = ""
        if name:
            if extras:
                line_name = "{0}[{1}]".format(name, ",".join(sorted(set(extras))))
            else:
                line_name = "{0}".format(name)
            line = "{0}@ {1}".format(line_name, link.url_without_fragment)
        else:
            line = link.url
        if pipfile.get("editable", False):
            line = "-e {0}".format(line)
        return cls.create(**arg_dict)

    @property
    def line_part(self):
        # type: () -> str
        link_url = None  # type: Optional[str]
        seed = None  # type: Optional[str]
        if self.link is not None:
            link_url = unquote(self.link.url_without_fragment)
        if self._uri_scheme and self._uri_scheme == "path":
            # We may need any one of these for passing to pip
            seed = self.path or link_url or self.uri
        elif (self._uri_scheme and self._uri_scheme == "file") or (
            (self.link.is_artifact or self.link.is_wheel) and self.link.url
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
        # type: () -> Dict[str, Dict[str, Any]]
        excludes = [
            "_base_line", "_has_hashed_name", "setup_path", "pyproject_path", "_uri_scheme",
            "pyproject_requires", "pyproject_backend", "setup_info", "_parsed_line"
        ]
        filter_func = lambda k, v: bool(v) is True and k.name not in excludes  # noqa
        pipfile_dict = attr.asdict(self, filter=filter_func).copy()
        name = pipfile_dict.pop("name")
        if "_uri_scheme" in pipfile_dict:
            pipfile_dict.pop("_uri_scheme")
        # For local paths and remote installable artifacts (zipfiles, etc)
        collision_keys = {"file", "uri", "path"}
        collision_order = ["file", "uri", "path"]  # type: List[str]
        key_match = next(iter(k for k in collision_order if k in pipfile_dict.keys()))
        if self._uri_scheme:
            dict_key = self._uri_scheme
            target_key = (
                dict_key
                if dict_key in pipfile_dict
                else key_match
            )
            if target_key is not None:
                winning_value = pipfile_dict.pop(target_key)
                collisions = [k for k in collision_keys if k in pipfile_dict]
                for key in collisions:
                    pipfile_dict.pop(key)
                pipfile_dict[dict_key] = winning_value
        elif (
            self.is_remote_artifact
            or (self.link is not None and self.link.is_artifact)
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


@attr.s(slots=True)
class VCSRequirement(FileRequirement):
    #: Whether the repository is editable
    editable = attr.ib(default=None)
    #: URI for the repository
    uri = attr.ib(default=None)
    #: path to the repository, if it's local
    path = attr.ib(default=None, validator=attr.validators.optional(validate_path))
    #: vcs type, i.e. git/hg/svn
    vcs = attr.ib(validator=attr.validators.optional(validate_vcs), default=None)
    #: vcs reference name (branch / commit / tag)
    ref = attr.ib(default=None)
    #: Subdirectory to use for installation if applicable
    subdirectory = attr.ib(default=None)
    _repo = attr.ib(default=None)
    _base_line = attr.ib(default=None)
    name = attr.ib()
    link = attr.ib()
    req = attr.ib()

    def __attrs_post_init__(self):
        if not self.uri:
            if self.path:
                self.uri = pip_shims.shims.path_to_url(self.path)
        split = urllib_parse.urlsplit(self.uri)
        scheme, rest = split[0], split[1:]
        vcs_type = ""
        if "+" in scheme:
            vcs_type, scheme = scheme.split("+", 1)
            vcs_type = "{0}+".format(vcs_type)
        new_uri = urllib_parse.urlunsplit((scheme,) + rest[:-1] + ("",))
        new_uri = "{0}{1}".format(vcs_type, new_uri)
        self.uri = new_uri

    @link.default
    def get_link(self):
        uri = self.uri if self.uri else pip_shims.shims.path_to_url(self.path)
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
        return (
            self.link.egg_fragment or self.req.name
            if getattr(self, "req", None)
            else super(VCSRequirement, self).get_name()
        )

    @property
    def vcs_uri(self):
        uri = self.uri
        if not any(uri.startswith("{0}+".format(vcs)) for vcs in VCS_LIST):
            uri = "{0}+{1}".format(self.vcs, uri)
        return uri

    @req.default
    def get_requirement(self):
        name = self.name or self.link.egg_fragment
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
        if not getattr(req, "url"):
            if url is not None:
                req.url = add_ssh_scheme_to_git_uri(url)
            elif self.uri is not None:
                req.url = self.parse_link_from_line(self.uri).link.url_without_fragment
        req.line = self.link.url
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
            self.uri != unquote(self.link.url_without_fragment)
            and "git+ssh://" in self.link.url
            and "git+git@" in self.uri
        ):
            req.line = self.uri
            req.url = self.link.url_without_fragment
        return req

    @property
    def repo(self):
        # type: () -> VCSRepository
        if self._repo is None:
            self._repo = self.get_vcs_repo()
        return self._repo

    def get_checkout_dir(self, src_dir=None):
        # type: (Optional[str]) -> str
        src_dir = os.environ.get("PIP_SRC", None) if not src_dir else src_dir
        checkout_dir = None
        if self.is_local:
            path = self.path
            if not path:
                path = pip_shims.shims.url_to_path(self.uri)
            if path and os.path.exists(path):
                checkout_dir = os.path.abspath(path)
                return checkout_dir
        if src_dir is not None:
            checkout_dir = os.path.join(os.path.abspath(src_dir), self.name)
            mkdir_p(src_dir)
            return checkout_dir
        return os.path.join(create_tracked_tempdir(prefix="requirementslib"), self.name)

    def get_vcs_repo(self, src_dir=None):
        # type: (Optional[str]) -> VCSRepository
        from .vcs import VCSRepository

        checkout_dir = self.get_checkout_dir(src_dir=src_dir)
        vcsrepo = VCSRepository(
            url=self.link.url,
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
            self.pyproject_path = os.path.join(checkout_dir, self.subdirectory, "pyproject.toml")
            pyproject_info = get_pyproject(os.path.join(checkout_dir, self.subdirectory))
        else:
            self.setup_path = os.path.join(checkout_dir, "setup.py")
            self.pyproject_path = os.path.join(checkout_dir, "pyproject.toml")
            pyproject_info = get_pyproject(checkout_dir)
        if pyproject_info is not None:
            pyproject_requires, pyproject_backend = pyproject_info
            self.pyproject_requires = pyproject_requires
            self.pyproject_backend = pyproject_backend
        return vcsrepo

    def get_commit_hash(self):
        hash_ = None
        hash_ = self.repo.get_commit_hash()
        return hash_

    def update_repo(self, src_dir=None, ref=None):
        if ref:
            self.ref = ref
        else:
            if self.ref:
                ref = self.ref
        repo_hash = None
        if not self.is_local and ref is not None:
            self.repo.checkout_ref(ref)
        repo_hash = self.repo.get_commit_hash()
        self.req.revision = repo_hash
        return repo_hash

    @contextmanager
    def locked_vcs_repo(self, src_dir=None):
        if not src_dir:
            src_dir = create_tracked_tempdir(prefix="requirementslib-", suffix="-src")
        vcsrepo = self.get_vcs_repo(src_dir=src_dir)
        self.req.revision = vcsrepo.get_commit_hash()

        # Remove potential ref in the end of uri after ref is parsed
        if "@" in self.link.show_url and "@" in self.uri:
            uri, ref = self.uri.rsplit("@", 1)
            checkout = self.req.revision
            if checkout and ref in checkout:
                self.uri = uri

        yield vcsrepo
        self._repo = vcsrepo

    @classmethod
    def from_pipfile(cls, name, pipfile):
        creation_args = {}
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
        for key in pipfile_keys:
            if key == "extras":
                extras = pipfile.get(key, None)
                if extras:
                    pipfile[key] = sorted(dedup([extra.lower() for extra in extras]))
            if key in VCS_LIST:
                creation_args["vcs"] = key
                target = pipfile.get(key)
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
                        creation_args["uri"] = pip_shims.shims.path_to_url(target)
            else:
                creation_args[key] = pipfile.get(key)
        creation_args["name"] = name
        return cls(**creation_args)

    @classmethod
    def from_line(cls, line, editable=None, extras=None):
        relpath = None
        if line.startswith("-e "):
            editable = True
            line = line.split(" ", 1)[1]
        vcs_type, prefer, relpath, path, uri, link = cls.get_link_from_line(line)
        if not extras and link.egg_fragment:
            name, extras = pip_shims.shims._strip_extras(link.egg_fragment)
            if extras:
                extras = parse_extras(extras)
        else:
            name = link.egg_fragment
        subdirectory = link.subdirectory_fragment
        ref = None
        if "@" in link.path and "@" in uri:
            uri, _, ref = uri.rpartition("@")
        if relpath and "@" in relpath:
            relpath, ref = relpath.rsplit("@", 1)
        creation_args = {
            "name": name,
            "path": relpath or path,
            "editable": editable,
            "extras": extras,
            "link": link,
            "vcs_type": vcs_type,
            "line": line,
            "uri": uri,
            "uri_scheme": prefer
        }
        if relpath:
            creation_args["relpath"] = relpath
        # return cls.create(**creation_args)
        return cls(
            name=name,
            ref=ref,
            vcs=vcs_type,
            subdirectory=subdirectory,
            link=link,
            path=relpath or path,
            editable=editable,
            uri=uri,
            extras=extras,
            base_line=line,
        )

    @property
    def line_part(self):
        """requirements.txt compatible line part sans-extras"""
        if self.is_local:
            base_link = self.link
            if not self.link:
                base_link = self.get_link()
            final_format = (
                "{{0}}#egg={0}".format(base_link.egg_fragment)
                if base_link.egg_fragment
                else "{0}"
            )
            base = final_format.format(self.vcs_uri)
        elif getattr(self, "_base_line", None):
            base = self._base_line
        else:
            base = getattr(self, "link", self.get_link()).url
        if base and self.extras and not extras_to_string(self.extras) in base:
            if self.subdirectory:
                base = "{0}".format(self.get_link().url)
            else:
                base = "{0}{1}".format(base, extras_to_string(sorted(self.extras)))
        if self.editable:
            base = "-e {0}".format(base)
        return base

    @staticmethod
    def _choose_vcs_source(pipfile):
        src_keys = [k for k in pipfile.keys() if k in ["path", "uri", "file"]]
        if src_keys:
            chosen_key = first(src_keys)
            vcs_type = pipfile.pop("vcs")
            _, pipfile_url = split_vcs_method_from_uri(pipfile.get(chosen_key))
            pipfile[vcs_type] = pipfile_url
            for removed in src_keys:
                pipfile.pop(removed)
        return pipfile

    @property
    def pipfile_part(self):
        excludes = [
            "_repo", "_base_line", "setup_path", "_has_hashed_name", "pyproject_path",
            "pyproject_requires", "pyproject_backend", "_setup_info", "_parsed_line"
        ]
        filter_func = lambda k, v: bool(v) is True and k.name not in excludes  # noqa
        pipfile_dict = attr.asdict(self, filter=filter_func).copy()
        if "vcs" in pipfile_dict:
            pipfile_dict = self._choose_vcs_source(pipfile_dict)
        name, _ = pip_shims.shims._strip_extras(pipfile_dict.pop("name"))
        return {name: pipfile_dict}


@attr.s
class Requirement(object):
    name = attr.ib()  # type: str
    vcs = attr.ib(default=None, validator=attr.validators.optional(validate_vcs))  # type: Optional[str]
    req = attr.ib(default=None)
    markers = attr.ib(default=None)
    specifiers = attr.ib(validator=attr.validators.optional(validate_specifiers))
    index = attr.ib(default=None)
    editable = attr.ib(default=None)
    hashes = attr.ib(default=attr.Factory(list), converter=list)
    extras = attr.ib(default=attr.Factory(list))
    abstract_dep = attr.ib(default=None)
    _ireq = None

    @name.default
    def get_name(self):
        return self.req.name

    @property
    def requirement(self):
        return self.req.req

    def get_hashes_as_pip(self, as_list=False):
        if self.hashes:
            if as_list:
                return [HASH_STRING.format(h) for h in self.hashes]
            return "".join([HASH_STRING.format(h) for h in self.hashes])
        return "" if not as_list else []

    @property
    def hashes_as_pip(self):
        self.get_hashes_as_pip()

    @property
    def markers_as_pip(self):
        if self.markers:
            return " ; {0}".format(self.markers).replace('"', "'")

        return ""

    @property
    def extras_as_pip(self):
        if self.extras:
            return "[{0}]".format(
                ",".join(sorted([extra.lower() for extra in self.extras]))
            )

        return ""

    @property
    def commit_hash(self):
        # type: () -> Optional[str]
        if not self.is_vcs:
            return None
        commit_hash = None
        with self.req.locked_vcs_repo() as repo:
            commit_hash = repo.get_commit_hash()
        return commit_hash

    @specifiers.default
    def get_specifiers(self):
        # type: () -> Optional[str]
        if self.req and self.req.req and self.req.req.specifier:
            return specs_to_string(self.req.req.specifier)
        return ""

    @property
    def is_vcs(self):
        # type: () -> bool
        return isinstance(self.req, VCSRequirement)

    @property
    def build_backend(self):
        # type: () -> Optional[str]
        if self.is_vcs or (self.is_file_or_url and self.req.is_local):
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
    def normalized_name(self):
        return canonicalize_name(self.name)

    def copy(self):
        return attr.evolve(self)

    @classmethod
    def from_line(cls, line):
        # type: (str) -> Requirement
        if isinstance(line, pip_shims.shims.InstallRequirement):
            line = format_requirement(line)
        hashes = None
        if "--hash=" in line:
            hashes = line.split(" --hash=")
            line, hashes = hashes[0], hashes[1:]
        editable = line.startswith("-e ")
        line = line.split(" ", 1)[1] if editable else line
        line, markers = split_markers_from_line(line)
        line, extras = pip_shims.shims._strip_extras(line)
        if extras:
            extras = parse_extras(extras)
        line = line.strip('"').strip("'").strip()
        line_with_prefix = "-e {0}".format(line) if editable else line
        vcs = None
        # Installable local files and installable non-vcs urls are handled
        # as files, generally speaking
        line_is_vcs = is_vcs(line)
        # check for pep-508 compatible requirements
        name, _, possible_url = line.partition("@")
        r = None  # type: Optional[Union[VCSRequirement, FileRequirement, NamedRequirement]]
        if is_installable_file(line) or (
            (is_valid_url(possible_url) or is_file_url(line) or is_valid_url(line)) and
            not (line_is_vcs or is_vcs(possible_url))
        ):
            r = FileRequirement.from_line(line_with_prefix, extras=extras)
        elif line_is_vcs:
            r = VCSRequirement.from_line(line_with_prefix, extras=extras)
            if isinstance(r, VCSRequirement):
                vcs = r.vcs
        elif line == "." and not is_installable_file(line):
            raise RequirementError(
                "Error parsing requirement %s -- are you sure it is installable?" % line
            )
        else:
            specs = "!=<>~"
            spec_matches = set(specs) & set(line)
            version = None
            name = "{0}".format(line)
            if spec_matches:
                spec_idx = min((line.index(match) for match in spec_matches))
                name = line[:spec_idx]
                version = line[spec_idx:]
            if not extras:
                name, extras = pip_shims.shims._strip_extras(name)
                if extras:
                    extras = parse_extras(extras)
            if version:
                name = "{0}{1}".format(name, version)
            r = NamedRequirement.from_line(line)
        req_markers = None
        if markers:
            req_markers = PackagingRequirement("fakepkg; {0}".format(markers))
        if r is not None and r.req is not None:
            r.req.marker = getattr(req_markers, "marker", None) if req_markers else None
            r.req.local_file = getattr(r.req, "local_file", False)
            name = getattr(r, "name", None)
            if name is None and getattr(r.req, "name", None) is not None:
                name = r.req.name
            elif name is None and getattr(r.req, "key", None) is not None:
                name = r.req.key
            if name is not None and getattr(r.req, "name", None) is None:
                r.req.name = name
        args = {
            "name": name,
            "vcs": vcs,
            "req": r,
            "markers": markers,
            "editable": editable,
        }
        if extras:
            extras = sorted(dedup([extra.lower() for extra in extras]))
            args["extras"] = extras
            if r is not None:
                r.extras = extras
            elif r is not None and r.extras is not None:
                args["extras"] = sorted(dedup([extra.lower() for extra in r.extras]))  # type: ignore
            if r.req is not None:
                r.req.extras = args["extras"]
        if hashes:
            args["hashes"] = hashes  # type: ignore
        cls_inst = cls(**args)
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
        vcs = first([vcs for vcs in VCS_LIST if vcs in _pipfile])
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
            req_markers = PackagingRequirement("fakepkg; {0}".format(markers))
            if r.req is not None:
                r.req.marker = req_markers.marker
        extras = _pipfile.get("extras")
        r.req.specifier = SpecifierSet(_pipfile["version"])
        r.req.extras = (
            sorted(dedup([extra.lower() for extra in extras])) if extras else []
        )
        args = {
            "name": r.name,
            "vcs": vcs,
            "req": r,
            "markers": markers,
            "extras": _pipfile.get("extras"),
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

        include_specifiers = True if self.specifiers else False
        if self.is_vcs:
            include_extras = False
        if self.is_file_or_url or self.is_vcs:
            include_specifiers = False
        parts = [
            self.req.line_part,
            self.extras_as_pip if include_extras else "",
            self.specifiers if include_specifiers else "",
            self.markers_as_pip if include_markers else "",
        ]
        if as_list:
            # This is used for passing to a subprocess call
            parts = ["".join(parts)]
        if include_hashes:
            hashes = self.get_hashes_as_pip(as_list=as_list)
            if as_list:
                parts.extend(hashes)
            else:
                parts.append(hashes)
        if sources and not (self.requirement.local_file or self.vcs):
            from ..utils import prepare_pip_source_args

            if self.index:
                sources = [s for s in sources if s.get("name") == self.index]
            source_list = prepare_pip_source_args(sources)
            if as_list:
                parts.extend(sources)
            else:
                index_string = " ".join(source_list)
                parts.extend([" ", index_string])
        if as_list:
            return parts
        line = "".join(parts)
        return line

    def get_markers(self):
        markers = self.markers
        if markers:
            fake_pkg = PackagingRequirement("fakepkg; {0}".format(markers))
            markers = fake_pkg.markers
        return markers

    def get_specifier(self):
        try:
            return Specifier(self.specifiers)
        except InvalidSpecifier:
            return LegacySpecifier(self.specifiers)

    def get_version(self):
        return pip_shims.shims.parse_version(self.get_specifier().version)

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
        return self.is_file_or_url and self.req.is_direct_url

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
        base_dict = {
            k: v
            for k, v in self.req.pipfile_part[name].items()
            if k not in ["req", "link", "setup_info"]
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
        if len(base_dict.keys()) == 1 and "version" in base_dict:
            base_dict = base_dict.get("version")
        return {name: base_dict}

    def as_ireq(self):
        kwargs = {
            "include_hashes": False,
        }
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

    def get_dependencies(self, sources=None):
        """Retrieve the dependencies of the current requirement.

        Retrieves dependencies of the current requirement.  This only works on pinned
        requirements.

        :param sources: Pipfile-formatted sources, defaults to None
        :param sources: list[dict], optional
        :return: A set of requirement strings of the dependencies of this requirement.
        :rtype: set(str)
        """

        from .dependencies import get_dependencies

        if not sources:
            sources = [
                {"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}
            ]
        return get_dependencies(self.as_ireq(), sources=sources)

    def get_abstract_dependencies(self, sources=None):
        """Retrieve the abstract dependencies of this requirement.

        Returns the abstract dependencies of the current requirement in order to resolve.

        :param sources: A list of sources (pipfile format), defaults to None
        :param sources: list, optional
        :return: A list of abstract (unpinned) dependencies
        :rtype: list[ :class:`~requirementslib.models.dependency.AbstractDependency` ]
        """

        from .dependencies import (
            AbstractDependency,
            get_dependencies,
            get_abstract_dependencies,
        )

        if not self.abstract_dep:
            parent = getattr(self, "parent", None)
            self.abstract_dep = AbstractDependency.from_requirement(self, parent=parent)
        if not sources:
            sources = [
                {"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}
            ]
        if is_pinned_requirement(self.ireq):
            deps = self.get_dependencies()
        else:
            ireq = sorted(self.find_all_matches(), key=lambda k: k.version)
            deps = get_dependencies(ireq.pop(), sources=sources)
        return get_abstract_dependencies(
            deps, sources=sources, parent=self.abstract_dep
        )

    def find_all_matches(self, sources=None, finder=None):
        """Find all matching candidates for the current requirement.

        Consults a finder to find all matching candidates.

        :param sources: Pipfile-formatted sources, defaults to None
        :param sources: list[dict], optional
        :return: A list of Installation Candidates
        :rtype: list[ :class:`~pip._internal.index.InstallationCandidate` ]
        """

        from .dependencies import get_finder, find_all_matches

        if not finder:
            finder = get_finder(sources=sources)
        return find_all_matches(finder, self.as_ireq())

    def run_requires(self, sources=None, finder=None):
        if self.req and self.req.setup_info is not None:
            info_dict = self.req.setup_info.as_dict()
        else:
            from .setup_info import SetupInfo
            if not finder:
                from .dependencies import get_finder
                finder = get_finder(sources=sources)
            info = SetupInfo.from_requirement(self, finder=finder)
            if info is None:
                return {}
            info_dict = info.get_info()
            if self.req and not self.req.setup_info:
                self.req.setup_info = info
        if self.req._has_hashed_name and info_dict.get("name"):
            self.req.name = self.name = info_dict["name"]
            if self.req.req.name != info_dict["name"]:
                self.req.req.name = info_dict["name"]
        return info_dict

    def merge_markers(self, markers):
        if not isinstance(markers, Marker):
            markers = Marker(markers)
        _markers = set(Marker(self.ireq.markers)) if self.ireq.markers else set(markers)
        _markers.add(markers)
        new_markers = Marker(" or ".join([str(m) for m in sorted(_markers)]))
        self.markers = str(new_markers)
        self.req.req.marker = new_markers
