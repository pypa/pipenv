# -*- coding: utf-8 -*-

from __future__ import absolute_import

import collections
import copy
import hashlib
import os

from contextlib import contextmanager

import attr
import pip_shims

from first import first
from packaging.markers import Marker
from packaging.requirements import Requirement as PackagingRequirement
from packaging.specifiers import Specifier, SpecifierSet, LegacySpecifier, InvalidSpecifier
from packaging.utils import canonicalize_name
from six.moves.urllib import parse as urllib_parse
from six.moves.urllib.parse import unquote
from vistir.compat import FileNotFoundError, Path
from vistir.misc import dedup
from vistir.path import (
    create_tracked_tempdir,
    get_converted_relative_path,
    is_file_url,
    is_valid_url,
)

from ..exceptions import RequirementError
from ..utils import (
    VCS_LIST,
    is_installable_file,
    is_vcs,
    ensure_setup_py,
    add_ssh_scheme_to_git_uri,
    strip_ssh_from_git_uri,
)
from .setup_info import SetupInfo
from .utils import (
    HASH_STRING,
    build_vcs_link,
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
    get_pyproject
)


@attr.s(slots=True)
class NamedRequirement(object):
    name = attr.ib()
    version = attr.ib(validator=attr.validators.optional(validate_specifiers))
    req = attr.ib()
    extras = attr.ib(default=attr.Factory(list))
    editable = attr.ib(default=False)

    @req.default
    def get_requirement(self):
        req = init_requirement(
            "{0}{1}".format(canonicalize_name(self.name), self.version)
        )
        return req

    @classmethod
    def from_line(cls, line):
        req = init_requirement(line)
        specifiers = None
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
        extras = None
        if req.extras:
            extras = list(req.extras)
        return cls(name=name, version=specifiers, req=req, extras=extras)

    @classmethod
    def from_pipfile(cls, name, pipfile):
        creation_args = {}
        if hasattr(pipfile, "keys"):
            attr_fields = [field.name for field in attr.fields(cls)]
            creation_args = {k: v for k, v in pipfile.items() if k in attr_fields}
        creation_args["name"] = name
        version = get_version(pipfile)
        extras = creation_args.get("extras", None)
        creation_args["version"] = version
        req = init_requirement("{0}{1}".format(name, version))
        if extras:
            req.extras += tuple(extras)
        creation_args["req"] = req
        return cls(**creation_args)

    @property
    def line_part(self):
        # FIXME: This should actually be canonicalized but for now we have to
        # simply lowercase it and replace underscores, since full canonicalization
        # also replaces dots and that doesn't actually work when querying the index
        return "{0}".format(normalize_name(self.name))

    @property
    def pipfile_part(self):
        pipfile_dict = attr.asdict(self, filter=filter_none).copy()
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
    setup_path = attr.ib(default=None)
    #: path to hit - without any of the VCS prefixes (like git+ / http+ / etc)
    path = attr.ib(default=None, validator=attr.validators.optional(validate_path))
    #: Whether the package is editable
    editable = attr.ib(default=False)
    #: Extras if applicable
    extras = attr.ib(default=attr.Factory(list))
    _uri_scheme = attr.ib(default=None)
    #: URI of the package
    uri = attr.ib()
    #: Link object representing the package to clone
    link = attr.ib()
    #: PyProject Requirements
    pyproject_requires = attr.ib(default=attr.Factory(list))
    #: PyProject Build System
    pyproject_backend = attr.ib(default=None)
    #: PyProject Path
    pyproject_path = attr.ib(default=None)
    _has_hashed_name = attr.ib(default=False)
    #: Package name
    name = attr.ib()
    #: A :class:`~pkg_resources.Requirement` isntance
    req = attr.ib()
    #: Setup metadata e.g. dependencies
    setup_info = attr.ib(default=None)

    @classmethod
    def get_link_from_line(cls, line):
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
        fixed_line = add_ssh_scheme_to_git_uri(line)
        added_ssh_scheme = fixed_line != line

        # We can assume a lot of things if this is a local filesystem path.
        if "://" not in fixed_line:
            p = Path(fixed_line).absolute()
            path = p.as_posix()
            uri = p.as_uri()
            link = create_link(uri)
            try:
                relpath = get_converted_relative_path(path)
            except ValueError:
                relpath = None
            return LinkInfo(None, "path", relpath, path, uri, link)

        # This is an URI. We'll need to perform some elaborated parsing.

        parsed_url = urllib_parse.urlsplit(fixed_line)
        original_url = parsed_url._replace()
        if added_ssh_scheme and ":" in parsed_url.netloc:
            original_netloc, original_path_start = parsed_url.netloc.rsplit(":", 1)
            uri_path = "/{0}{1}".format(original_path_start, parsed_url.path)
            parsed_url = original_url._replace(netloc=original_netloc, path=uri_path)

        # Split the VCS part out if needed.
        original_scheme = parsed_url.scheme
        if "+" in original_scheme:
            vcs_type, scheme = original_scheme.split("+", 1)
            parsed_url = parsed_url._replace(scheme=scheme)
            prefer = "uri"
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
        if self.setup_path:
            return os.path.dirname(os.path.abspath(self.setup_path))

    @property
    def dependencies(self):
        build_deps = []
        setup_deps = []
        deps = {}
        if self.setup_info:
            setup_info = self.setup_info.as_dict()
            deps.update(setup_info.get("requires", {}))
            setup_deps.extend(setup_info.get("setup_requires", []))
            build_deps.extend(setup_info.get("build_requires", []))
        if self.pyproject_requires:
            build_deps.extend(self.pyproject_requires)
        return deps, setup_deps, build_deps

    @uri.default
    def get_uri(self):
        if self.path and not self.uri:
            self._uri_scheme = "path"
            return pip_shims.shims.path_to_url(os.path.abspath(self.path))
        elif getattr(self, "req", None) and getattr(self.req, "url"):
            return self.req.url

    @name.default
    def get_name(self):
        loc = self.path or self.uri
        if loc and not self._uri_scheme:
            self._uri_scheme = "path" if self.path else "file"
        name = None
        if getattr(self, "req", None) and getattr(self.req, "name") and self.req.name is not None:
            if self.is_direct_url:
                return self.req.name
        if self.link and self.link.egg_fragment and not self._has_hashed_name:
            return self.link.egg_fragment
        elif self.link and self.link.is_wheel:
            from pip_shims import Wheel
            self._has_hashed_name = False
            return Wheel(self.link.filename).name
        elif self.link and ((self.link.scheme == "file" or self.editable) or (
            self.path and self.setup_path and os.path.isfile(str(self.setup_path))
        )):
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
            if getattr(self, "req", None):
                _ireq.req = copy.deepcopy(self.req)
            else:
                if self.extras:
                    _ireq.extras = set(self.extras)
            from .setup_info import SetupInfo
            subdir = getattr(self, "subdirectory", None)
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
        hashed_loc = hashlib.sha256(loc.encode("utf-8")).hexdigest()
        hashed_name = hashed_loc[-7:]
        if not name or name.lower() == "unknown":
            self._has_hashed_name = True
            name = hashed_name
        else:
            self._has_hashed_name = False
        name_in_link = getattr(self.link, "egg_fragment", "") if self.link else ""
        if not self._has_hashed_name and name_in_link != name:
            self.link = create_link("{0}#egg={1}".format(self.link.url, name))
        return name

    @link.default
    def get_link(self):
        target = "{0}".format(self.uri)
        if hasattr(self, "name") and not self._has_hashed_name:
            target = "{0}#egg={1}".format(target, self.name)
        link = create_link(target)
        return link

    @req.default
    def get_requirement(self):
        req = init_requirement(normalize_name(self.name))
        req.editable = False
        req.line = self.link.url_without_fragment
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
    def is_remote_artifact(self):
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
        return self.is_remote_artifact

    @property
    def formatted_path(self):
        if self.path:
            path = self.path
            if not isinstance(path, Path):
                path = Path(path)
            return path.as_posix()
        return

    @classmethod
    def create(
        cls, path=None, uri=None, editable=False, extras=None, link=None, vcs_type=None,
        name=None, req=None, line=None, uri_scheme=None, setup_path=None, relpath=None
    ):
        if relpath and not path:
            path = relpath
        if not path and uri and link.scheme == "file":
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
            link = create_link(uri)
        if not uri:
            uri = unquote(link.url_without_fragment)
        if not extras:
            extras = []
        pyproject_path = None
        if path is not None:
            pyproject_requires = get_pyproject(os.path.abspath(path))
        pyproject_backend = None
        pyproject_requires = None
        if pyproject_requires is not None:
            pyproject_requires, pyproject_backend = pyproject_requires
        if path:
            pyproject_path = Path(path).joinpath("pyproject.toml")
            if not pyproject_path.exists():
                pyproject_path = None
        if not setup_path and path is not None:
            setup_path = Path(path).joinpath("setup.py")
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
            "pyproject_backend": pyproject_backend
        }
        if vcs_type:
            creation_kwargs["vcs_type"] = vcs_type
        _line = None
        if not name:
            _line = unquote(link.url_without_fragment) if link.url else uri
            if editable:
                if extras:
                    _line = "{0}[{1}]".format(_line, ",".join(sorted(set(extras))))
                ireq = pip_shims.shims.install_req_from_editable(_line)
            else:
                _line = path if (uri_scheme and uri_scheme == "path") else _line
                if extras:
                    _line = "{0}[{1}]".format(_line, ",".join(sorted(set(extras))))
                ireq = pip_shims.shims.install_req_from_line(_line)
            if extras and not ireq.extras:
                ireq.extras = set(extras)
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
        if req:
            creation_kwargs["req"] = req
        if creation_kwargs.get("req") and line and not getattr(creation_kwargs["req"], "line", None):
            creation_kwargs["req"].line = line
        if name:
            creation_kwargs["name"] = name
        cls_inst = cls(**creation_kwargs)
        if not _line:
            if editable and uri_scheme == "path":
                _line = relpath if relpath else path
            else:
                _line = unquote(cls_inst.link.url_without_fragment) or cls_inst.uri
                _line = "{0}#egg={1}".format(line, cls_inst.name) if not cls_inst._has_hashed_name else _line
        cls_inst.req.line = line if line else _line
        return cls_inst

    @classmethod
    def from_line(cls, line, extras=None):
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
            "extras": extras
        }
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
        link = create_link(uri)
        arg_dict = {
            "name": name,
            "path": path,
            "uri": unquote(link.url_without_fragment),
            "editable": pipfile.get("editable", False),
            "link": link,
            "uri_scheme": uri_scheme,
        }
        if link.scheme != "file" and not pipfile.get("editable", False):
            arg_dict["line"] = "{0}@ {1}".format(name, link.url_without_fragment)
        return cls.create(**arg_dict)

    @property
    def line_part(self):
        if self._uri_scheme and self._uri_scheme == "path":
            # We may need any one of these for passing to pip
            seed = self.path or unquote(self.link.url_without_fragment) or self.uri
        elif (self._uri_scheme and self._uri_scheme == "file") or (
            (self.link.is_artifact or self.link.is_wheel) and self.link.url
        ):
            seed = unquote(self.link.url_without_fragment) or self.uri
        # add egg fragments to remote artifacts (valid urls only)
        if not self._has_hashed_name and self.is_remote_artifact:
            seed += "#egg={0}".format(self.name)
        editable = "-e " if self.editable else ""
        return "{0}{1}".format(editable, seed)

    @property
    def pipfile_part(self):
        excludes = [
            "_base_line", "_has_hashed_name", "setup_path", "pyproject_path",
            "pyproject_requires", "pyproject_backend", "setup_info"
        ]
        filter_func = lambda k, v: bool(v) is True and k.name not in excludes
        pipfile_dict = attr.asdict(self, filter=filter_func).copy()
        name = pipfile_dict.pop("name")
        if "_uri_scheme" in pipfile_dict:
            pipfile_dict.pop("_uri_scheme")
        # For local paths and remote installable artifacts (zipfiles, etc)
        collision_keys = {"file", "uri", "path"}
        if self._uri_scheme:
            dict_key = self._uri_scheme
            target_key = (
                dict_key
                if dict_key in pipfile_dict
                else next(
                    (k for k in ("file", "uri", "path") if k in pipfile_dict), None
                )
            )
            if target_key:
                winning_value = pipfile_dict.pop(target_key)
                collisions = (k for k in collision_keys if k in pipfile_dict)
                for key in collisions:
                    pipfile_dict.pop(key)
                pipfile_dict[dict_key] = winning_value
        elif (
            self.is_remote_artifact
            or self.link.is_artifact
            and (self._uri_scheme and self._uri_scheme == "file")
        ):
            dict_key = "file"
            # Look for uri first because file is a uri format and this is designed
            # to make sure we add file keys to the pipfile as a replacement of uri
            target_key = next(
                (k for k in ("file", "uri", "path") if k in pipfile_dict), None
            )
            winning_value = pipfile_dict.pop(target_key)
            key_to_remove = (k for k in collision_keys if k in pipfile_dict)
            for key in key_to_remove:
                pipfile_dict.pop(key)
            pipfile_dict[dict_key] = winning_value
        else:
            collisions = [key for key in ["path", "file", "uri"] if key in pipfile_dict]
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
        return build_vcs_link(
            self.vcs,
            add_ssh_scheme_to_git_uri(uri),
            name=self.name,
            ref=self.ref,
            subdirectory=self.subdirectory,
            extras=self.extras,
        )

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
        url = self.uri or self.link.url_without_fragment
        if not name:
            raise ValueError(
                "pipenv requires an #egg fragment for version controlled "
                "dependencies. Please install remote dependency "
                "in the form {0}#egg=<package-name>.".format(url)
            )
        req = init_requirement(canonicalize_name(self.name))
        req.editable = self.editable
        if not getattr(req, "url") and self.uri:
            req.url = self.uri
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
            req.url = self.uri
        return req

    @property
    def is_local(self):
        if is_file_url(self.uri):
            return True
        return False

    @property
    def repo(self):
        if self._repo is None:
            self._repo = self.get_vcs_repo()
        return self._repo

    def get_checkout_dir(self, src_dir=None):
        src_dir = os.environ.get("PIP_SRC", None) if not src_dir else src_dir
        checkout_dir = None
        if self.is_local:
            path = self.path
            if not path:
                path = pip_shims.shims.url_to_path(self.uri)
            if path and os.path.exists(path):
                checkout_dir = os.path.abspath(path)
                return checkout_dir
        return os.path.join(create_tracked_tempdir(prefix="requirementslib"), self.name)

    def get_vcs_repo(self, src_dir=None):
        from .vcs import VCSRepository

        checkout_dir = self.get_checkout_dir(src_dir=src_dir)
        link = build_vcs_link(
            self.vcs,
            self.uri,
            name=self.name,
            ref=self.ref,
            subdirectory=self.subdirectory,
            extras=self.extras,
        )
        vcsrepo = VCSRepository(
            url=link.url,
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
        elif self._base_line:
            base = self._base_line
        else:
            base = self.link.url
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
            "pyproject_requires", "pyproject_backend", "setup_info"
        ]
        filter_func = lambda k, v: bool(v) is True and k.name not in excludes
        pipfile_dict = attr.asdict(self, filter=filter_func).copy()
        if "vcs" in pipfile_dict:
            pipfile_dict = self._choose_vcs_source(pipfile_dict)
        name, _ = pip_shims.shims._strip_extras(pipfile_dict.pop("name"))
        return {name: pipfile_dict}


@attr.s
class Requirement(object):
    name = attr.ib()
    vcs = attr.ib(default=None, validator=attr.validators.optional(validate_vcs))
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
        if not self.is_vcs:
            return None
        commit_hash = None
        with self.req.locked_vcs_repo() as repo:
            commit_hash = repo.get_commit_hash()
        return commit_hash

    @specifiers.default
    def get_specifiers(self):
        if self.req and self.req.req.specifier:
            return specs_to_string(self.req.req.specifier)
        return

    @property
    def is_vcs(self):
        return isinstance(self.req, VCSRequirement)

    @property
    def is_file_or_url(self):
        return isinstance(self.req, FileRequirement)

    @property
    def is_named(self):
        return isinstance(self.req, NamedRequirement)

    @property
    def normalized_name(self):
        return canonicalize_name(self.name)

    def copy(self):
        return attr.evolve(self)

    @classmethod
    def from_line(cls, line):
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
        if is_installable_file(line) or (
            (is_valid_url(possible_url) or is_file_url(line) or is_valid_url(line)) and
            not (line_is_vcs or is_vcs(possible_url))
        ):
            r = FileRequirement.from_line(line_with_prefix, extras=extras)
        elif line_is_vcs:
            r = VCSRequirement.from_line(line_with_prefix, extras=extras)
            vcs = r.vcs
        elif line == "." and not is_installable_file(line):
            raise RequirementError(
                "Error parsing requirement %s -- are you sure it is installable?" % line
            )
        else:
            specs = "!=<>~"
            spec_matches = set(specs) & set(line)
            version = None
            name = line
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
        r.req.marker = getattr(req_markers, "marker", None) if req_markers else None
        r.req.local_file = getattr(r.req, "local_file", False)
        name = getattr(r.req, "name", None)
        if not name:
            name = getattr(r.req, "project_name", None)
            r.req.name = name
        if not name:
            name = getattr(r.req, "key", None)
            if name:
                r.req.name = name
        args = {
            "name": r.name,
            "vcs": vcs,
            "req": r,
            "markers": markers,
            "editable": editable,
        }
        if extras:
            extras = sorted(dedup([extra.lower() for extra in extras]))
            args["extras"] = extras
            r.req.extras = extras
            r.extras = extras
        elif r.extras:
            args["extras"] = sorted(dedup([extra.lower() for extra in r.extras]))
        if hashes:
            args["hashes"] = hashes
        cls_inst = cls(**args)
        if not cls_inst.is_named and not cls_inst.editable and not name:
            if cls_inst.is_vcs:
                ireq = pip_shims.shims.install_req_from_req(cls_inst.as_line(include_hashes=False))
                info = SetupInfo.from_ireq(ireq)
                if info is not None:
                    info_dict = info.as_dict()
                    cls_inst.req.setup_info = info
                else:
                    info_dict = {}
            else:
                info_dict = cls_inst.run_requires()
            found_name = info_dict.get("name", old_name)
            if old_name != found_name:
                cls_inst.req.req.line.replace(old_name, found_name)
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
        r.req.marker = getattr(req_markers, "marker", None)
        r.req.specifier = SpecifierSet(_pipfile["version"])
        extras = _pipfile.get("extras")
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
        if cls_inst.is_named:
            cls_inst.req.req.line = cls_inst.as_line()
        old_name = cls_inst.req.req.name or cls_inst.req.name
        if not cls_inst.is_named and not cls_inst.editable and not name:
            if cls_inst.is_vcs:
                ireq = pip_shims.shims.install_req_from_req(cls_inst.as_line(include_hashes=False))
                info = SetupInfo.from_ireq(ireq)
                if info is not None:
                    info_dict = info.as_dict()
                    cls_inst.req.setup_info = info
                else:
                    info_dict = {}
            else:
                info_dict = cls_inst.run_requires()
            found_name = info_dict.get("name", old_name)
            if old_name != found_name:
                cls_inst.req.req.line.replace(old_name, found_name)
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
            if k not in ["req", "link"]
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
        ireq_line = self.as_line(include_hashes=False)
        if self.editable or self.req.editable:
            if ireq_line.startswith("-e "):
                ireq_line = ireq_line[len("-e ") :]
            with ensure_setup_py(self.req.setup_path):
                ireq = pip_shims.shims.install_req_from_editable(ireq_line)
        else:
            ireq = pip_shims.shims.install_req_from_line(ireq_line)
        if not getattr(ireq, "req", None):
            ireq.req = self.req.req
        else:
            ireq.req.extras = self.req.req.extras
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
