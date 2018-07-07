# -*- coding: utf-8 -*-
from __future__ import absolute_import

import attr
import collections
import hashlib
import os
import requirements

from first import first
from six.moves.urllib import parse as urllib_parse

from .baserequirement import BaseRequirement
from .markers import PipenvMarkers
from .utils import (
    HASH_STRING,
    extras_to_string,
    get_version,
    specs_to_string,
    validate_specifiers,
    validate_path,
    validate_vcs,
    build_vcs_link,
    add_ssh_scheme_to_git_uri,
    strip_ssh_from_git_uri,
    split_vcs_method_from_uri,
    filter_none,
    optional_instance_of,
    split_markers_from_line,
)
from .._compat import (
    Link,
    path_to_url,
    url_to_path,
    _strip_extras,
    InstallRequirement,
    Path,
    urlparse,
    unquote,
    Wheel,
    FileNotFoundError,
)
from ..exceptions import RequirementError
from ..utils import (
    VCS_LIST,
    is_installable_file,
    is_vcs,
    is_valid_url,
    pep423_name,
    get_converted_relative_path,
)


@attr.s
class NamedRequirement(BaseRequirement):
    name = attr.ib()
    version = attr.ib(validator=attr.validators.optional(validate_specifiers))
    req = attr.ib()

    @req.default
    def get_requirement(self):
        from pkg_resources import RequirementParseError
        try:
            req = first(requirements.parse("{0}{1}".format(self.name, self.version)))
        except RequirementParseError:
            raise RequirementError(
                "Error parsing requirement: %s%s" % (self.name, self.version)
            )
        return req

    @classmethod
    def from_line(cls, line):
        req = first(requirements.parse(line))
        specifiers = None
        if req.specifier:
            specifiers = specs_to_string(req.specs)
        return cls(name=req.name, version=specifiers, req=req)

    @classmethod
    def from_pipfile(cls, name, pipfile):
        creation_args = {}
        if hasattr(pipfile, "keys"):
            creation_args = {k: v for k, v in pipfile.items() if k in cls.attr_fields()}
        creation_args["name"] = name
        version = get_version(pipfile)
        creation_args["version"] = version
        creation_args["req"] = first(requirements.parse("{0}{1}".format(name, version)))
        return cls(**creation_args)

    @property
    def line_part(self):
        return "{self.name}".format(self=self)

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


@attr.s
class FileRequirement(BaseRequirement):
    """File requirements for tar.gz installable files or wheels or setup.py
    containing directories."""

    setup_path = attr.ib(default=None)
    path = attr.ib(default=None, validator=attr.validators.optional(validate_path))
    # : path to hit - without any of the VCS prefixes (like git+ / http+ / etc)
    editable = attr.ib(default=None)
    uri = attr.ib()
    link = attr.ib()
    name = attr.ib()
    req = attr.ib()
    _has_hashed_name = False
    _uri_scheme = attr.ib(default=None)

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
            link = Link(uri)
            try:
                relpath = get_converted_relative_path(path)
            except ValueError:
                relpath = None
            return LinkInfo(None, "path", relpath, path, uri, link)

        # This is an URI. We'll need to perform some elaborated parsing.

        parsed_url = urllib_parse.urlsplit(fixed_line)
        if added_ssh_scheme and ':' in parsed_url.netloc:
            original_netloc, original_path_start = parsed_url.netloc.rsplit(':', 1)
            uri_path = '/{0}{1}'.format(original_path_start, parsed_url.path)
            original_url = parsed_url
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
                parsed_url._replace(scheme=original_scheme, fragment="")
            )

        if added_ssh_scheme:
            original_uri = urllib_parse.urlunsplit(original_url._replace(scheme=original_scheme, fragment=""))
            uri = strip_ssh_from_git_uri(original_uri)

        # Re-attach VCS prefix to build a Link.
        link = Link(
            urllib_parse.urlunsplit(parsed_url._replace(scheme=original_scheme))
        )

        return LinkInfo(vcs_type, prefer, relpath, path, uri, link)

    @uri.default
    def get_uri(self):
        if self.path and not self.uri:
            self._uri_scheme = "path"
            self.uri = path_to_url(os.path.abspath(self.path))

    @name.default
    def get_name(self):
        loc = self.path or self.uri
        if loc:
            self._uri_scheme = "path" if self.path else "uri"
        name = None
        if self.link and self.link.egg_fragment:
            return self.link.egg_fragment
        elif self.link and self.link.is_wheel:
            return Wheel(self.link.filename).name
        if (
            self._uri_scheme != "uri"
            and self.path
            and self.setup_path
            and self.setup_path.exists()
        ):
            from distutils.core import run_setup

            old_curdir = os.path.abspath(os.getcwd())
            try:
                os.chdir(str(self.setup_path.parent))
                dist = run_setup(self.setup_path.as_posix(), stop_after="init")
                name = dist.get_name()
            except (FileNotFoundError, IOError) as e:
                dist = None
            except Exception as e:
                from .._compat import InstallRequirement, make_abstract_dist

                try:
                    if not isinstance(Path, self.path):
                        _path = Path(self.path)
                    else:
                        _path = self.path
                    if self.editable:
                        _ireq = InstallRequirement.from_editable(_path.as_uri())
                    else:
                        _ireq = InstallRequirement.from_line(_path.as_posix())
                    dist = make_abstract_dist(_ireq).get_dist()
                    name = dist.project_name
                except (TypeError, ValueError, AttributeError) as e:
                    dist = None
            finally:
                os.chdir(old_curdir)
        hashed_loc = hashlib.sha256(loc.encode("utf-8")).hexdigest()
        hashed_name = hashed_loc[-7:]
        if not name or name == "UNKNOWN":
            self._has_hashed_name = True
            name = hashed_name
        if self.link and not self._has_hashed_name:
            self.link = Link("{0}#egg={1}".format(self.link.url, name))
        return name

    @link.default
    def get_link(self):
        target = "{0}".format(self.uri)
        if hasattr(self, "name"):
            target = "{0}#egg={1}".format(target, self.name)
        link = Link(target)
        return link

    @req.default
    def get_requirement(self):
        prefix = "-e " if self.editable else ""
        line = "{0}{1}".format(prefix, self.link.url)
        req = first(requirements.parse(line))
        if self.path and self.link and self.link.scheme.startswith("file"):
            req.local_file = True
            req.path = self.path
            req.uri = None
            self._uri_scheme = "file"
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
            and not self.req.editable
        )

    @property
    def formatted_path(self):
        if self.path:
            path = self.path
            if not isinstance(path, Path):
                path = Path(path)
            return path.as_posix()
        return

    @classmethod
    def from_line(cls, line):
        line = line.strip('"').strip("'")
        link = None
        path = None
        editable = line.startswith("-e ")
        line = line.split(" ", 1)[1] if editable else line
        setup_path = None
        if not any([is_installable_file(line), is_valid_url(line)]):
            raise RequirementError(
                "Supplied requirement is not installable: {0!r}".format(line)
            )
        vcs_type, prefer, relpath, path, uri, link = cls.get_link_from_line(line)
        setup_path = Path(path) / "setup.py" if path else None
        arg_dict = {
            "path": relpath if relpath else path,
            "uri": unquote(link.url_without_fragment),
            "link": link,
            "editable": editable,
            "setup_path": setup_path,
            "uri_scheme": prefer,
        }
        if link and link.is_wheel:
            arg_dict["name"] = Wheel(link.filename).name
        elif link.egg_fragment:
            arg_dict["name"] = link.egg_fragment
        created = cls(**arg_dict)
        return created

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
            uri = path_to_url(path)
        link = Link(uri)

        arg_dict = {
            "name": name,
            "path": path,
            "uri": unquote(link.url_without_fragment),
            "editable": pipfile.get("editable", False),
            "link": link,
            "uri_scheme": uri_scheme,
        }
        return cls(**arg_dict)

    @property
    def line_part(self):
        if self._uri_scheme and self._uri_scheme == 'path':
            seed = self.path or unquote(self.link.url_without_fragment) or self.uri
        elif (
            (self._uri_scheme and self._uri_scheme == "file")
            or ((self.link.is_artifact or self.link.is_wheel)
            and self.link.url)
        ):
            seed = unquote(self.link.url_without_fragment) or self.uri
        # add egg fragments to remote artifacts (valid urls only)
        if not self._has_hashed_name and self.is_remote_artifact:
            seed += "#egg={0}".format(self.name)
        editable = "-e " if self.editable else ""
        return "{0}{1}".format(editable, seed)

    @property
    def pipfile_part(self):
        pipfile_dict = attr.asdict(self, filter=filter_none).copy()
        name = pipfile_dict.pop("name")
        if "_uri_scheme" in pipfile_dict:
            pipfile_dict.pop("_uri_scheme")
        if "setup_path" in pipfile_dict:
            pipfile_dict.pop("setup_path")
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


@attr.s
class VCSRequirement(FileRequirement):
    editable = attr.ib(default=None)
    uri = attr.ib(default=None)
    path = attr.ib(default=None, validator=attr.validators.optional(validate_path))
    vcs = attr.ib(validator=attr.validators.optional(validate_vcs), default=None)
    # : vcs reference name (branch / commit / tag)
    ref = attr.ib(default=None)
    subdirectory = attr.ib(default=None)
    name = attr.ib()
    link = attr.ib()
    req = attr.ib()
    _INCLUDE_FIELDS = (
        "editable",
        "uri",
        "path",
        "vcs",
        "ref",
        "subdirectory",
        "name",
        "link",
        "req",
    )

    def __attrs_post_init__(self):
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
        return build_vcs_link(
            self.vcs,
            add_ssh_scheme_to_git_uri(self.uri),
            name=self.name,
            ref=self.ref,
            subdirectory=self.subdirectory,
        )

    @name.default
    def get_name(self):
        return (
            self.link.egg_fragment or self.req.name
            if self.req
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
        prefix = "-e " if self.editable else ""
        line = "{0}{1}".format(prefix, self.link.url)
        req = first(requirements.parse(line))
        if self.path and self.link and self.link.scheme.startswith("file"):
            req.local_file = True
            req.path = self.path
        if self.editable:
            req.editable = True
        req.link = self.link
        if (
            self.uri != unquote(self.link.url_without_fragment)
            and "git+ssh://" in self.link.url
            and "git+git@" in self.uri
        ):
            req.line = self.uri
            req.uri = self.uri
        if not req.name:
            raise ValueError(
                "pipenv requires an #egg fragment for version controlled "
                "dependencies. Please install remote dependency "
                "in the form {0}#egg=<package-name>.".format(req.uri)
            )
        if self.vcs and not req.vcs:
            req.vcs = self.vcs
        if self.ref and not req.revision:
            req.revision = self.ref
        return req

    @classmethod
    def from_pipfile(cls, name, pipfile):
        creation_args = {}
        pipfile_keys = [
            k
            for k in ("ref", "vcs", "subdirectory", "path", "editable", "file", "uri")
            + VCS_LIST
            if k in pipfile
        ]
        for key in pipfile_keys:
            if key in VCS_LIST:
                creation_args["vcs"] = key
                composed_uri = add_ssh_scheme_to_git_uri(
                    "{0}+{1}".format(key, pipfile.get(key))
                ).split("+", 1)[1]
                is_url = is_valid_url(pipfile.get(key)) or is_valid_url(composed_uri)
                target_key = "uri" if is_url else "path"
                creation_args[target_key] = pipfile.get(key)
            else:
                creation_args[key] = pipfile.get(key)
        creation_args["name"] = name
        return cls(**creation_args)

    @classmethod
    def from_line(cls, line, editable=None):
        relpath = None
        if line.startswith("-e "):
            editable = True
            line = line.split(" ", 1)[1]
        vcs_type, prefer, relpath, path, uri, link = cls.get_link_from_line(line)
        name = link.egg_fragment
        subdirectory = link.subdirectory_fragment
        ref = None
        if "@" in link.show_url and "@" in uri:
            uri, ref = uri.rsplit("@", 1)
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
        )

    @property
    def line_part(self):
        """requirements.txt compatible line part sans-extras"""
        if self.req:
            return self.req.line
        base = "{0}".format(self.link)
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
        pipfile_dict = attr.asdict(self, filter=filter_none).copy()
        if "vcs" in pipfile_dict:
            pipfile_dict = self._choose_vcs_source(pipfile_dict)
        name = pipfile_dict.pop("name")
        return {name: pipfile_dict}


@attr.s
class Requirement(object):
    name = attr.ib()
    vcs = attr.ib(default=None, validator=attr.validators.optional(validate_vcs))
    req = attr.ib(default=None, validator=optional_instance_of(BaseRequirement))
    markers = attr.ib(default=None)
    specifiers = attr.ib(validator=attr.validators.optional(validate_specifiers))
    index = attr.ib(default=None)
    editable = attr.ib(default=None)
    hashes = attr.ib(default=attr.Factory(list), converter=list)
    extras = attr.ib(default=attr.Factory(list))
    _ireq = None
    _INCLUDE_FIELDS = ("name", "markers", "index", "editable", "hashes", "extras")

    @name.default
    def get_name(self):
        return self.req.name

    @property
    def requirement(self):
        return self.req.req

    @property
    def hashes_as_pip(self):
        if self.hashes:
            return "".join([HASH_STRING.format(h) for h in self.hashes])

        return ""

    @property
    def markers_as_pip(self):
        if self.markers:
            return "; {0}".format(self.markers.replace('"', "'"))

        return ""

    @property
    def extras_as_pip(self):
        if self.extras:
            return "[{0}]".format(",".join(self.extras))

        return ""

    @specifiers.default
    def get_specifiers(self):
        if self.req and self.req.req.specifier:
            return specs_to_string(self.req.req.specs)
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
        return pep423_name(self.name)

    @classmethod
    def from_line(cls, line):
        hashes = None
        if "--hash=" in line:
            hashes = line.split(" --hash=")
            line, hashes = hashes[0], hashes[1:]
        editable = line.startswith("-e ")
        line = line.split(" ", 1)[1] if editable else line
        line, markers = split_markers_from_line(line)
        line, extras = _strip_extras(line)
        line = line.strip('"').strip("'").strip()
        line_with_prefix = "-e {0}".format(line) if editable else line
        vcs = None
        # Installable local files and installable non-vcs urls are handled
        # as files, generally speaking
        if is_installable_file(line) or (is_valid_url(line) and not is_vcs(line)):
            r = FileRequirement.from_line(line_with_prefix)
        elif is_vcs(line):
            r = VCSRequirement.from_line(line_with_prefix)
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
                name, extras = _strip_extras(name)
            if version:
                name = "{0}{1}".format(name, version)
            r = NamedRequirement.from_line(line)
        if extras:
            extras = first(
                requirements.parse("fakepkg{0}".format(extras_to_string(extras)))
            ).extras
            r.req.extras = extras
        if markers:
            r.req.markers = markers
        args = {
            "name": r.name,
            "vcs": vcs,
            "req": r,
            "markers": markers,
            "editable": editable,
        }
        if extras:
            args["extras"] = extras
        if hashes:
            args["hashes"] = hashes
        return cls(**args)

    @classmethod
    def from_pipfile(cls, name, pipfile):
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
        args = {
            "name": r.name,
            "vcs": vcs,
            "req": r,
            "markers": PipenvMarkers.from_pipfile(name, _pipfile).line_part,
            "extras": _pipfile.get("extras"),
            "editable": _pipfile.get("editable", False),
            "index": _pipfile.get("index"),
        }
        if any(key in _pipfile for key in ["hash", "hashes"]):
            args["hashes"] = _pipfile.get("hashes", [pipfile.get("hash")])
        return cls(**args)

    def as_line(self, sources=None):
        """Format this requirement as a line in requirements.txt.

        If `sources` provided, it should be an sequence of mappings, containing
        all possible sources to be used for this requirement.

        If `sources` is omitted or falsy, no index information will be included
        in the requirement line.
        """
        line = "{0}{1}{2}{3}{4}".format(
            self.req.line_part,
            self.extras_as_pip,
            self.specifiers if self.specifiers else "",
            self.markers_as_pip,
            self.hashes_as_pip,
        )
        if sources and not (self.requirement.local_file or self.vcs):
            from ..utils import prepare_pip_source_args

            if self.index:
                sources = [s for s in sources if s.get("name") == self.index]
            index_string = " ".join(prepare_pip_source_args(sources))
            line = "{0} {1}".format(line, index_string)
        return line

    @property
    def constraint_line(self):
        return self.as_line()

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
        if "hashes" in base_dict and len(base_dict["hashes"]) == 1:
            base_dict["hash"] = base_dict.pop("hashes")[0]
        if len(base_dict.keys()) == 1 and "version" in base_dict:
            base_dict = base_dict.get("version")
        return {name: base_dict}

    @property
    def pipfile_entry(self):
        return self.as_pipfile().copy().popitem()

    @property
    def ireq(self):
        if not self._ireq:
            ireq_line = self.as_line()
            if ireq_line.startswith("-e "):
                ireq_line = ireq_line[len("-e ") :]
                self._ireq = InstallRequirement.from_editable(ireq_line)
            else:
                self._ireq = InstallRequirement.from_line(ireq_line)
        return self._ireq
