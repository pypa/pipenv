# -*- coding: utf-8 -*-
from __future__ import absolute_import
import attr
import hashlib
import os
import requirements
from first import first
from pkg_resources import RequirementParseError
from six.moves.urllib import parse as urllib_parse
from six.moves.urllib import request as urllib_request
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
    VcsSupport,
)
from ..exceptions import RequirementError
from ..utils import (
    VCS_LIST,
    is_installable_file,
    is_vcs,
    is_valid_url,
    pep423_name,
    get_converted_relative_path,
    multi_split,
)


@attr.s
class NamedRequirement(BaseRequirement):
    name = attr.ib()
    version = attr.ib(validator=attr.validators.optional(validate_specifiers))
    req = attr.ib()

    @req.default
    def get_requirement(self):
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
    _uri_scheme = None

    @classmethod
    def get_link_from_line(cls, line):
        relpath = None
        if line.startswith("-e "):
            editable = True
            line = line.split(" ", 1)[1]
        vcs_line = add_ssh_scheme_to_git_uri(line)
        added_ssh_scheme = True if vcs_line != line else False
        parsed_url = urllib_parse.urlsplit(vcs_line)
        vcs_type = None
        scheme = parsed_url.scheme
        if '+' in parsed_url.scheme:
            vcs_type, scheme = parsed_url.scheme.split('+')
        if (scheme == 'file' or not scheme) and parsed_url.path and os.path.exists(parsed_url.path):
            path = Path(parsed_url.path).absolute().as_posix()
            uri = path_to_url(path)
            if not parsed_url.scheme:
                relpath = get_converted_relative_path(path)
            uri = '{0}#{1}'.format(uri, parsed_url.fragment) if parsed_url.fragment else uri
        else:
            path = None
            uri = urllib_parse.urlunsplit((scheme,) + parsed_url[1:])
        vcs_line = '{0}+{1}'.format(vcs_type, uri) if vcs_type else uri
        link = Link(vcs_line)
        if added_ssh_scheme:
            uri = strip_ssh_from_git_uri(uri)
        return vcs_type, relpath, uri, link

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
            return os.path.basename(Wheel(self.link.path).name)
        if self._uri_scheme != "uri" and self.path and self.setup_path:
            from distutils.core import run_setup

            try:
                dist = run_setup(self.setup_path.as_posix(), stop_after="init")
                name = dist.get_name()
            except (FileNotFoundError, IOError) as e:
                dist = None
            except (NameError, RuntimeError) as e:
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

        if is_valid_url(line) and not is_installable_file(line):
            vcs_type, relpath, uri, link = cls.get_link_from_line(line)
        else:
            if is_valid_url(line):
                parsed = urlparse(line)
                vcs_type, relpath, uri, link = cls.get_link_from_line(line)
                # link = Link("{0}".format(line))
                if parsed.scheme == "file":
                    path = Path(relpath)
                    setup_path = path / "setup.py"
                    path = path.absolute().as_posix()
            else:
                vcs_type, relpath, uri, link = cls.get_link_from_line(line)
                path = Path(relpath)
                setup_path = path / "setup.py"
                path = path.as_posix()
                # link = Link(unquote(_path.absolute().as_uri()))
                # if _path.is_absolute() or _path.as_posix() == ".":
                #     path = _path.as_posix()
                # else:
                #     path = get_converted_relative_path(line)
        # print(link)
        print(uri)
        arg_dict = {
            "path": path,
            "uri": link.url_without_fragment,
            "link": link,
            "editable": editable,
            "setup_path": setup_path,
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
        link = Link(unquote(uri)) if uri else None
        arg_dict = {
            "name": name,
            "path": pipfile.get("path"),
            "uri": unquote(link.url_without_fragment if link else uri),
            "editable": pipfile.get("editable"),
            "link": link,
        }
        return cls(**arg_dict)

    @property
    def line_part(self):
        seed = self.formatted_path or self.link.url or self.uri
        # add egg fragments to remote artifacts (valid urls only)
        if not self._has_hashed_name and self.is_remote_artifact:
            seed += "#egg={0}".format(self.name)
        editable = "-e " if self.editable else ""
        return "{0}{1}".format(editable, seed)

    @property
    def pipfile_part(self):
        pipfile_dict = {k: v for k, v in attr.asdict(self, filter=filter_none).items()}
        name = pipfile_dict.pop("name")
        if "setup_path" in pipfile_dict:
            pipfile_dict.pop("setup_path")
        req = self.req
        # For local paths and remote installable artifacts (zipfiles, etc)
        if self.is_remote_artifact:
            dict_key = "file"
            # Look for uri first because file is a uri format and this is designed
            # to make sure we add file keys to the pipfile as a replacement of uri
            target_keys = [k for k in pipfile_dict.keys() if k in ["uri", "path"]]
            pipfile_dict[dict_key] = pipfile_dict.pop(first(target_keys))
            if len(target_keys) > 1:
                pipfile_dict.pop(target_keys[1])
        else:
            collisions = [key for key in ["path", "uri", "file"] if key in pipfile_dict]
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
        print(self.uri)
        split = urllib_parse.urlsplit(self.uri)
        scheme, rest = split[0], split[1:]
        vcs_type = ""
        if '+' in scheme:
            vcs_type, scheme = scheme.split('+', 1)
            vcs_type = "{0}+".format(vcs_type)
        new_uri = urllib_parse.urlunsplit((scheme,) + rest)
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
            self.uri != self.link.url
            and "git+ssh://" in self.link.url
            and "git+git@" in self.uri
        ):
            req.line = strip_ssh_from_git_uri(req.line)
            req.uri = strip_ssh_from_git_uri(req.uri)
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
        vcs_line = add_ssh_scheme_to_git_uri(line)
        added_ssh_scheme = True if vcs_line != line else False
        parsed_url = urllib_parse.urlsplit(vcs_line)
        vcs_type = None
        scheme = parsed_url.scheme
        if '+' in parsed_url.scheme:
            vcs_type, scheme = parsed_url.scheme.split('+')
        if (scheme == 'file' or not scheme) and parsed_url.path and os.path.exists(parsed_url.path):
            path = Path(parsed_url.path).absolute().as_posix()
            uri = path_to_url(path)
            if not parsed_url.scheme:
                relpath = get_converted_relative_path(path)
            uri = '{0}#{1}'.format(uri, parsed_url.fragment) if parsed_url.fragment else uri                
        else:
            path = None
            uri = urllib_parse.urlunsplit((scheme,) + parsed_url[1:])
        vcs_line = '{0}+{1}'.format(vcs_type, uri) if vcs_type else uri
        link = Link(vcs_line)
        name = link.egg_fragment
        uri = link.url_without_fragment
        if added_ssh_scheme:
            uri = strip_ssh_from_git_uri(uri)
        subdirectory = link.subdirectory_fragment
        ref = None
        if "@" in link.show_url:
            uri, ref = uri.rsplit("@", 1)
        return cls(
            name=name,
            ref=ref,
            vcs=vcs_type,
            subdirectory=subdirectory,
            link=link,
            path=relpath,
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
        line = line.strip('"').strip("'")
        line_with_prefix = "-e {0}".format(line) if editable else line
        vcs = None
        # Installable local files and installable non-vcs urls are handled
        # as files, generally speaking
        if (
            is_installable_file(line)
            or (is_valid_url(line) and not is_vcs(line))
        ):
            r = FileRequirement.from_line(line_with_prefix)
        elif is_vcs(line):
            r = VCSRequirement.from_line(line_with_prefix)
            vcs = r.vcs
        elif line == '.' and not is_installable_file(line):
            raise RequirementError('Error parsing requirement %s -- are you sure it is installable?' % line)
        else:
            specs = '!=<>~'
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
                name = '{0}{1}'.format(name, version)
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
        if self.is_named or self.is_vcs:
            return self.as_line()
        return self.req.req.line

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
                ireq_line = ireq_line[len("-e "):]
                self._ireq = InstallRequirement.from_editable(ireq_line)
            else:
                self._ireq = InstallRequirement.from_line(ireq_line)
        return self._ireq
