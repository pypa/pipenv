# -*- coding=utf-8 -*-
from __future__ import absolute_import
import abc
import sys
import hashlib
import os
import requirements
import six
from attr import attrs, attrib, Factory, validators
import attr
from ._compat import Link, path_to_url, _strip_extras, InstallRequirement
from distlib.markers import Evaluator
from packaging.markers import Marker, InvalidMarker
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from .utils import (
    SCHEME_LIST,
    VCS_LIST,
    is_installable_file,
    is_vcs,
    is_valid_url,
    pep423_name,
    get_converted_relative_path,
    multi_split,
    is_star,
)
from first import first

try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

HASH_STRING = " --hash={0}"


def _strip_ssh_from_git_uri(uri):
    """Return git+ssh:// formatted URI to git+git@ format"""
    if isinstance(uri, six.string_types):
        uri = uri.replace("git+ssh://", "git+")
    return uri


def _clean_git_uri(uri):
    """Cleans VCS uris from pip9 format"""
    if isinstance(uri, six.string_types):
        # Add scheme for parsing purposes, this is also what pip does
        if uri.startswith("git+") and "://" not in uri:
            uri = uri.replace("git+", "git+ssh://")
    return uri


def _split_markers(line):
    """Split markers from a dependency"""
    if not any(line.startswith(uri_prefix) for uri_prefix in SCHEME_LIST):
        marker_sep = ";"
    else:
        marker_sep = "; "
    markers = None
    if marker_sep in line:
        line, markers = line.split(marker_sep, 1)
        markers = markers.strip() if markers else None
    return line, markers


def _split_vcs_method(uri):
    """Split a vcs+uri formatted uri into (vcs, uri)"""
    vcs_start = "{0}+"
    vcs = first([vcs for vcs in VCS_LIST if uri.startswith(vcs_start.format(vcs))])
    if vcs:
        vcs, uri = uri.split("+", 1)
    return vcs, uri


def _validate_vcs(instance, attr_, value):
    if value not in VCS_LIST:
        raise ValueError("Invalid vcs {0!r}".format(value))


def _validate_path(instance, attr_, value):
    if not os.path.exists(value):
        raise ValueError("Invalid path {0!r}", format(value))


def _validate_markers(instance, attr_, value):
    try:
        Marker("{0}{1}".format(attr_.name, value))
    except InvalidMarker:
        raise ValueError("Invalid Marker {0}{1}".format(attr_, value))


def _validate_specifiers(instance, attr_, value):
    if value == "":
        return True
    try:
        SpecifierSet(value)
    except InvalidMarker:
        raise ValueError("Invalid Specifiers {0}".format(value))


def _filter_none(k, v):
    if v:
        return True
    return False


def _optional_instance_of(cls):
    return validators.optional(validators.instance_of(cls))


@attrs
class Source(object):
    # : URL to PyPI instance
    url = attrib(default="")
    # : If False, skip SSL checks
    verify_ssl = attrib(
        default=True, validator=validators.optional(validators.instance_of(bool))
    )
    # : human name to refer to this source (can be referenced in packages or dev-packages)
    name = attrib(default="")


@six.add_metaclass(abc.ABCMeta)
class BaseRequirement():

    @classmethod
    def from_line(cls, line):
        """Returns a requirement from a requirements.txt or pip-compatible line"""
        raise NotImplementedError

    @abc.abstractmethod
    def line_part(self):
        """Returns the current requirement as a pip-compatible line"""

    @classmethod
    def from_pipfile(cls, name, pipfile):
        """Returns a requirement from a pipfile entry"""
        raise NotImplementedError

    @abc.abstractmethod
    def pipfile_part(self):
        """Returns the current requirement as a pipfile entry"""

    @classmethod
    def attr_fields(cls):
        return [field.name for field in attr.fields(cls)]


@attrs
class PipenvMarkers(BaseRequirement):
    """System-level requirements - see PEP508 for more detail"""
    os_name = attrib(default=None, validator=validators.optional(_validate_markers))
    sys_platform = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )
    platform_machine = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )
    platform_python_implementation = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )
    platform_release = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )
    platform_system = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )
    platform_version = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )
    python_version = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )
    python_full_version = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )
    implementation_name = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )
    implementation_version = attrib(
        default=None, validator=validators.optional(_validate_markers)
    )

    @property
    def line_part(self):
        return " and ".join(
            [
                "{0} {1}".format(k, v)
                for k, v in attr.asdict(self, filter=_filter_none).items()
            ]
        )

    @property
    def pipfile_part(self):
        return {"markers": self.as_line}

    @classmethod
    def make_marker(cls, marker_string):
        marker = Marker(marker_string)
        marker_dict = {}
        for m in marker._markers:
            if isinstance(m, six.string_types):
                continue
            var, op, val = m
            if var.value in cls.attr_fields():
                marker_dict[var.value] = '{0} "{1}"'.format(op, val)
        return marker_dict

    @classmethod
    def from_line(cls, line):
        if ";" in line:
            line = line.rsplit(";", 1)[1].strip()
        marker_dict = cls.make_marker(line)
        return cls(**marker_dict)

    @classmethod
    def from_pipfile(cls, name, pipfile):
        found_keys = [k for k in pipfile.keys() if k in cls.attr_fields()]
        marker_strings = ["{0} {1}".format(k, pipfile[k]) for k in found_keys]
        if pipfile.get("markers"):
            marker_strings.append(pipfile.get("markers"))
        markers = {}
        for marker in marker_strings:
            marker_dict = cls.make_marker(marker)
            if marker_dict:
                markers.update(marker_dict)
        return cls(**markers)


@attrs
class NamedRequirement(BaseRequirement):
    name = attrib()
    version = attrib(validator=validators.optional(_validate_specifiers))
    req = attrib()

    @req.default
    def get_requirement(self):
        return first(requirements.parse("{0}{1}".format(self.name, self.version)))

    @classmethod
    def from_line(cls, line):
        req = first(requirements.parse(line))
        specifiers = None
        if req.specifier:
            specifiers = _specs_to_string(req.specs)
        return cls(name=req.name, version=specifiers, req=req)

    @classmethod
    def from_pipfile(cls, name, pipfile):
        creation_args = {}
        if hasattr(pipfile, "keys"):
            creation_args = {k: v for k, v in pipfile.items() if k in cls.attr_fields()}
        creation_args["name"] = name
        version = _get_version(pipfile)
        creation_args["version"] = version
        creation_args["req"] = first(requirements.parse("{0}{1}".format(name, version)))
        return cls(**creation_args)

    @property
    def line_part(self):
        return "{self.name}".format(self=self)

    @property
    def pipfile_part(self):
        pipfile_dict = attr.asdict(self, filter=_filter_none).copy()
        if "version" not in pipfile_dict:
            pipfile_dict["version"] = "*"
        name = pipfile_dict.pop("name")
        return {name: pipfile_dict}


@attrs
class FileRequirement(BaseRequirement):
    """File requirements for tar.gz installable files or wheels or setup.py
    containing directories."""
    path = attrib(default=None, validator=validators.optional(_validate_path))
    # : path to hit - without any of the VCS prefixes (like git+ / http+ / etc)
    uri = attrib()
    name = attrib()
    link = attrib()
    editable = attrib(default=None)
    req = attrib()
    _has_hashed_name = False
    _uri_scheme = None

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
        hashed_loc = hashlib.sha256(loc.encode("utf-8")).hexdigest()
        hash_fragment = hashed_loc[-7:]
        self._has_hashed_name = True
        return hash_fragment

    @link.default
    def get_link(self):
        target = "{0}#egg={1}".format(self.uri, self.name)
        return Link(target)

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
        return any(
            self.link.scheme.startswith(scheme)
            for scheme in ("http", "https", "ftp", "ftps", "uri")
        ) and (
            self.link.is_artifact or self.link.is_wheel
        ) and not self.req.editable

    @classmethod
    def from_line(cls, line):
        link = None
        path = None
        editable = line.startswith("-e ")
        line = line.split(" ", 1)[1] if editable else line
        if not any([is_installable_file(line), is_valid_url(line)]):
            raise ValueError(
                "Supplied requirement is not installable: {0!r}".format(line)
            )

        if is_valid_url(line) and not is_installable_file(line):
            link = Link(line)
        else:
            if is_valid_url(line):
                parsed = urlparse(line)
                link = Link('{0}'.format(line))
                if parsed.scheme == "file":
                    path = Path(parsed.path).absolute().as_posix()
                    if get_converted_relative_path(path) == ".":
                        path = "."
                    line = path
            else:
                _path = Path(line)
                link = Link(_path.absolute().as_uri())
                if _path.is_absolute() or _path.as_posix() == ".":
                    path = _path.as_posix()
                else:
                    path = get_converted_relative_path(line)
        arg_dict = {
            "path": path,
            "uri": link.url_without_fragment,
            "link": link,
            "editable": editable,
        }
        if link.egg_fragment:
            arg_dict["name"] = link.egg_fragment
        created = cls(**arg_dict)
        return created

    @classmethod
    def from_pipfile(cls, name, pipfile):
        uri_key = first((k for k in ["uri", "file"] if k in pipfile))
        uri = pipfile.get(uri_key, pipfile.get("path"))
        if not uri_key:
            abs_path = os.path.abspath(uri)
            uri = path_to_url(abs_path) if os.path.exists(abs_path) else None
        link = Link(uri) if uri else None
        arg_dict = {
            "name": name,
            "path": pipfile.get("path"),
            "uri": link.url_without_fragment,
            "editable": pipfile.get("editable"),
            "link": link,
        }
        return cls(**arg_dict)

    @property
    def line_part(self):
        seed = self.path or self.link.url or self.uri
        # add egg fragments to remote artifacts (valid urls only)
        if not self._has_hashed_name and self.is_remote_artifact:
            seed += "#egg={0}".format(self.name)
        editable = "-e " if self.editable else ""
        return "{0}{1}".format(editable, seed)

    @property
    def pipfile_part(self):
        pipfile_dict = {k: v for k, v in attr.asdict(self, filter=_filter_none).items()}
        name = pipfile_dict.pop("name")
        req = self.req
        # For local paths and remote installable artifacts (zipfiles, etc)
        if self.is_remote_artifact:
            dict_key = "file"
            # Look for uri first because file is a uri format and this is designed
            # to make sure we add file keys to the pipfile as a replacement of uri
            target_keys = [k for k in pipfile_dict.keys() if k in ["uri", "path"]]
            pipfile_dict[dict_key] = pipfile_dict.pop(first(target_keys))
            if len(target_keys) > 1:
                _ = pipfile_dict.pop(target_keys[1])
        else:
            collisions = [key for key in ["path", "uri", "file"] if key in pipfile_dict]
            if len(collisions) > 1:
                for k in collisions[1:]:
                    _ = pipfile_dict.pop(k)
        return {name: pipfile_dict}


@attrs
class VCSRequirement(FileRequirement):
    editable = attrib(default=None)
    uri = attrib(default=None)
    path = attrib(default=None, validator=validators.optional(_validate_path))
    vcs = attrib(validator=validators.optional(_validate_vcs), default=None)
    # : vcs reference name (branch / commit / tag)
    ref = attrib(default=None)
    subdirectory = attrib(default=None)
    name = attrib()
    link = attrib()
    req = attrib()
    _INCLUDE_FIELDS = (
        "editable", "uri", "path", "vcs", "ref", "subdirectory", "name", "link", "req"
    )

    @link.default
    def get_link(self):
        return build_vcs_link(
            self.vcs,
            _clean_git_uri(self.uri),
            name=self.name,
            ref=self.ref,
            subdirectory=self.subdirectory,
        )

    @name.default
    def get_name(self):
        return self.link.egg_fragment or self.req.name if self.req else ""

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
            self.uri != self.link.url
            and "git+ssh://" in self.link.url
            and "git+git@" in self.uri
        ):
            req.line = _strip_ssh_from_git_uri(req.line)
            req.uri = _strip_ssh_from_git_uri(req.uri)
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
                composed_uri = _clean_git_uri(
                    "{0}+{1}".format(key, pipfile.get(key))
                ).lstrip(
                    "{0}+".format(key)
                )
                is_url = is_valid_url(pipfile.get(key)) or is_valid_url(composed_uri)
                target_key = "uri" if is_url else "path"
                creation_args[target_key] = pipfile.get(key)
            else:
                creation_args[key] = pipfile.get(key)
        creation_args["name"] = name
        return cls(**creation_args)

    @classmethod
    def from_line(cls, line, editable=None):
        path = None
        if line.startswith("-e "):
            editable = True
            line = line.split(" ", 1)[1]
        vcs_line = _clean_git_uri(line)
        vcs_method, vcs_location = _split_vcs_method(vcs_line)
        if not is_valid_url(vcs_location) and os.path.exists(vcs_location):
            path = get_converted_relative_path(vcs_location)
            vcs_location = path_to_url(os.path.abspath(vcs_location))
        link = Link(vcs_line)
        name = link.egg_fragment
        uri = link.url_without_fragment
        if "git+git@" in line:
            uri = _strip_ssh_from_git_uri(uri)
        subdirectory = link.subdirectory_fragment
        ref = None
        if "@" in link.show_url:
            uri, ref = uri.rsplit("@", 1)
        return cls(
            name=name,
            ref=ref,
            vcs=vcs_method,
            subdirectory=subdirectory,
            link=link,
            path=path,
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
            _, pipfile_url = _split_vcs_method(pipfile.get(chosen_key))
            pipfile[vcs_type] = pipfile_url
            for removed in src_keys:
                _ = pipfile.pop(removed)
        return pipfile

    @property
    def pipfile_part(self):
        pipfile_dict = attr.asdict(self, filter=_filter_none).copy()
        if "vcs" in pipfile_dict:
            pipfile_dict = self._choose_vcs_source(pipfile_dict)
        name = pipfile_dict.pop("name")
        return {name: pipfile_dict}


@attrs
class Requirement(object):
    name = attrib()
    vcs = attrib(default=None, validator=validators.optional(_validate_vcs))
    req = attrib(default=None, validator=_optional_instance_of(BaseRequirement))
    markers = attrib(default=None)
    specifiers = attrib(validator=validators.optional(_validate_specifiers))
    index = attrib(default=None)
    editable = attrib(default=None)
    hashes = attrib(default=Factory(list), converter=list)
    extras = attrib(default=Factory(list))
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
            return "; {0}".format(self.markers)

        return ""

    @property
    def extras_as_pip(self):
        if self.extras:
            return "[{0}]".format(",".join(self.extras))

        return ""

    @specifiers.default
    def get_specifiers(self):
        if self.req and self.req.req.specifier:
            return _specs_to_string(self.req.req.specs)
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
        if not self.is_vcs and not self.is_file_or_url:
            return pep423_name(self.name)
        return self.name

    @classmethod
    def from_line(cls, line):
        hashes = None
        if "--hash=" in line:
            hashes = line.split(" --hash=")
            line, hashes = hashes[0], hashes[1:]
        editable = line.startswith("-e ")
        stripped_line = line.split(" ", 1)[1] if editable else line
        line, markers = _split_markers(line)
        line, extras = _strip_extras(line)
        vcs = None
        # Installable local files and installable non-vcs urls are handled
        # as files, generally speaking
        if (
            is_installable_file(stripped_line)
            or (is_valid_url(stripped_line) and not is_vcs(stripped_line))
        ):
            r = FileRequirement.from_line(line)
        elif is_vcs(stripped_line):
            r = VCSRequirement.from_line(line)
            vcs = r.vcs
        else:
            name = multi_split(stripped_line, "!=<>~")[0]
            if not extras:
                name, extras = _strip_extras(name)
            r = NamedRequirement.from_line(stripped_line)
        if extras:
            extras = first(
                requirements.parse("fakepkg{0}".format(_extras_to_string(extras)))
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
    def from_pipfile(cls, name, indexes, pipfile):
        _pipfile = {}
        if hasattr(pipfile, "keys"):
            _pipfile = dict(pipfile).copy()
        _pipfile["version"] = _get_version(pipfile)
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

    def as_line(self, include_index=False, project=None):
        line = "{0}{1}{2}{3}{4}".format(
            self.req.line_part,
            self.extras_as_pip,
            self.specifiers if self.specifiers else "",
            self.markers_as_pip,
            self.hashes_as_pip,
        )
        if include_index and not (self.requirement.local_file or self.vcs):
            from .utils import prepare_pip_source_args

            if self.index:
                pip_src_args = [project.get_source(self.index)]
            else:
                pip_src_args = project.sources
            index_string = " ".join(prepare_pip_source_args(pip_src_args))
            line = "{0} {1}".format(line, index_string)
        return line

    def as_pipfile(self, include_index=False):
        good_keys = (
            "hashes", "extras", "markers", "editable", "version", "index"
        ) + VCS_LIST
        req_dict = {
            k: v
            for k, v in attr.asdict(self, recurse=False, filter=_filter_none).items()
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
                _ = base_dict.pop(k)
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
                ireq_line = ireq_line[len("-e "):]
                self._ireq = InstallRequirement.from_editable(ireq_line)
            else:
                self._ireq = InstallRequirement.from_line(ireq_line)
        return self._ireq


def _extras_to_string(extras):
    """Turn a list of extras into a string"""
    if isinstance(extras, six.string_types):
        if extras.startswith("["):
            return extras

        else:
            extras = [extras]
    return "[{0}]".format(",".join(extras))


def _specs_to_string(specs):
    """Turn a list of specifier tuples into a string"""
    if specs:
        if isinstance(specs, six.string_types):
            return specs
        return ",".join(["".join(spec) for spec in specs])
    return ""


def build_vcs_link(vcs, uri, name=None, ref=None, subdirectory=None, extras=None):
    if extras is None:
        extras = []
    vcs_start = "{0}+".format(vcs)
    if not uri.startswith(vcs_start):
        uri = "{0}{1}".format(vcs_start, uri)
    uri = _clean_git_uri(uri)
    if ref:
        uri = "{0}@{1}".format(uri, ref)
    if name:
        uri = "{0}#egg={1}".format(uri, name)
        if extras:
            extras = _extras_to_string(extras)
            uri = "{0}{1}".format(uri, extras)
    if subdirectory:
        uri = "{0}&subdirectory={1}".format(uri, subdirectory)
    return Link(uri)


def _get_version(pipfile_entry):
    if str(pipfile_entry) == "{}" or is_star(pipfile_entry):
        return ""

    elif hasattr(pipfile_entry, "keys") and "version" in pipfile_entry:
        if is_star(pipfile_entry.get("version")):
            return ""
        return pipfile_entry.get("version", "")

    if isinstance(pipfile_entry, six.string_types):
        return pipfile_entry
    return ""
