# -*- coding=utf-8 -*-
from __future__ import absolute_import
import sys
from pipenv import PIPENV_VENDOR, PIPENV_PATCHED

sys.path.insert(0, PIPENV_VENDOR)
sys.path.insert(0, PIPENV_PATCHED)
import hashlib
import os
import requirements
import six
import attr
from attr import attrs, attrib, Factory, validators
from collections import defaultdict
from pip9.index import Link
from pip9.download import path_to_url, url_to_path
from pip9.req.req_install import _strip_extras
from pip9._vendor.distlib.markers import Evaluator
from pip9._vendor.packaging.markers import Marker, InvalidMarker
from pip9._vendor.packaging.specifiers import SpecifierSet, InvalidSpecifier
from pipenv.utils import SCHEME_LIST, VCS_LIST, is_installable_file, is_vcs, multi_split, get_converted_relative_path, is_star, is_pinned, is_valid_url
from first import first

try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path

HASH_STRING = ' --hash={0}'


def _validate_vcs(instance, attr_, value):
    if value not in VCS_LIST:
        raise ValueError('Invalid vcs {0!r}'.format(value))


def _validate_path(instance, attr_, value):
    if not os.path.exists(value):
        raise ValueError('Invalid path {0!r}',format(value))


def _validate_markers(instance, attr_, value):
    try:
        Marker('{0}{1}'.format(attr_, value))
    except InvalidMarker:
        raise ValueError('Invalid Marker {0}{1}'.format(attr_, value))


def _validate_specifiers(instance, attr_, value):
    try:
        SpecifierSet(value)
    except InvalidMarker:
        raise ValueError('Invalid Specifiers {0}'.format(value))

_optional_instance_of = lambda cls: validators.optional(validators.instance_of(cls))


@attrs
class Source(object):
    #: URL to PyPI instance
    url = attrib(default='')
    #: If False, skip SSL checks
    verify_ssl = attrib(default=True, validator=validators.optional(validators.instance_of(bool)))
    #: human name to refer to this source (can be referenced in packages or dev-packages)
    name = attrib(default='')


@attrs
class PipenvMarkers(object):
    """System-level requirements - see PEP508 for more detail"""
    os_name = attrib(default=None, validator=_validate_markers)
    sys_platform = attrib(default=None, validator=_validate_markers)
    platform_machine = attrib(default=None, validator=_validate_markers)
    platform_python_implementation = attrib(default=None, validator=_validate_markers)
    platform_release = attrib(default=None, validator=_validate_markers)
    platform_system = attrib(default=None, validator=_validate_markers)
    platform_version = attrib(default=None, validator=_validate_markers)
    python_version = attrib(default=None, validator=_validate_markers)
    python_full_version = attrib(default=None, validator=_validate_markers)
    implementation_name = attrib(default=None, validator=_validate_markers)
    implementation_version = attrib(default=None, validator=_validate_markers)

    @property
    def line_part(self):
        return ' and '.join(['{0} {1}'.format(k, v) for k, v in self.__dict__.items() if v])

    @property
    def pipfile_part(self):
        return {'markers': self.as_line}


@attrs
class NamedRequirement(object):
    name = attrib()
    version = attrib(validator=_validate_specifiers)
    req = attrib(default=None)

    @classmethod
    def from_line(cls, line):
        req = requirements.parse(line)
        return cls(name=req.name, version=req.specifier, req=req)

    @property
    def line_part(self):
        return '{self.name}{self.version}'.format(self=self)

    @property
    def pipfile_part(self):
        pipfile_dict = attr.asdict(self)
        name = pipfile_dict.pop('name')
        return {name: pipfile_dict}


@attrs
class FileRequirement(object):
    """File requirements for tar.gz installable files or wheels or setup.py
    containing directories."""
    path = attrib(default=None, validator=_validate_path)
    #: path to hit - without any of the VCS prefixes (like git+ / http+ / etc)
    uri = attrib()
    name = attrib()
    link = attrib()
    editable = attrib(default=None)
    req = attrib()

    @uri.default
    def get_uri(self):
        if self.path and not self.uri:
            self.uri = path_to_url(os.path.abspath(self.path))

    @name.default
    def get_name(self):
        loc = self.path or self.uri
        hashed_loc = hashlib.sha256(loc.encode('utf-8')).hexdigest()
        hash_fragment = hashed_loc[-7:]
        return hash_fragment

    @req.default
    def get_requirement(self):
        base = '{0}'.format(self.link)
        if self.editable:
            base = '-e {0}'.format(base)
        return first(requirements.parse(base))

    @link.default
    def get_link(self):
        target = '{0}#egg={1}'.format(self.uri, self.name)
        return Link(self.uri)

    @property
    def line_part(self):
        seed = self.path or self.link.url or self.uri
        editable = '-e ' if self.editable else ''
        return '{0}{1}'.format(editable, seed)

    @property
    def pipfile_part(self):
        pipfile_dict = {k: v for k, v in self.__dict__.items() if v}
        name = pipfile_dict.pop('name')
        if self.path:
            pipfile_dict.pop('uri')
        return {name: pipfile_dict}


@attrs
class VCSRequirement(FileRequirement):
    #: vcs reference name (branch / commit / tag)
    ref = attrib(default=None)
    subdirectory = attrib(default=None)
    vcs = attrib(validator=validators.optional(_validate_vcs), default=None)
    uri = attrib(converter=_clean_git_uri)

    @link.default
    def get_link(self):
        return build_vcs_link(self.vcs, self.uri, self.name, self.subdirectory)

    @name.default
    def get_name(self):
        return self.link.egg_fragment or self.link.filename

    @property
    def vcs_uri(self):
        uri = self.uri
        if not any(uri.startswith('{0}+'.format(vcs)) for vcs in VCS_LIST):
            uri = '{0}+{1}'.format(self.vcs, uri)
        return uri

    @req.default
    def get_requirement(self):
        return first(requirements.parse(self.line_part))

    @classmethod
    def from_line(cls, line, editable=None):
        if line.startswith('-e '):
            editable = True
            line = line.split(' ', 1)[1]
        if not is_valid_url(line):
            line = path_to_url(line)
        link = Link(line)
        name = link.egg_fragment
        uri = link.url_without_fragment
        subdirectory =  link.subdirectory_fragment
        vcs, uri = _split_vcs_method(uri)
        ref = None
        if '@' in uri:
            uri, ref = uri.rsplit('@', 1)
        return cls(name=name, ref=ref, vcs=vcs, subdirectory=subdirectory, link=link, path=path, editable=editable)

    @property
    def line_part(self):
        """requirements.txt compatible line part sans-extras"""
        base = '{0}'.format(self.link)
        if self.editable:
            base = '-e {0}'.format(base)
        return base

    @property
    def pipfile_part(self):
        pipfile_dict = {k: v for k, v in self.__dict__.items() if v}
        name = pipfile_dict.pop('name')
        if self.path:
            pipfile_dict.pop('uri')
        return {name: pipfile_dict}


@attrs
class NewRequirement(object):
    name = attrib(default='')
    vcs = attrib(default=None, validator=validators.optional(_validate_vcs))
    req = attrib(default=None, validator=_optional_instance_of(FileRequirement))
    markers = attrib(default=None)
    specifiers = attrib(default=None, validator=_validate_specifiers)
    index = attrib(default=None)
    editable = attrib(default=None)
    extras = attrib(default=Factory(list))
    hashes = attrib(default=Factory(list))

    @classmethod
    def from_line(cls, line):
        hashes = None
        if '--hash=' in line:
            hashes = line.split(' --hash=')
            line, hashes = hashes[0], hashes[1:]
        original_line = line
        editable = line.startswith('-e ')
        line = line.split(' 'm 1) if editable else line
        line, markers = PipenvRequirement._split_markers(line)
        line, extras = _strip_extras(line)
        vcs = None
        if is_installable_file(line):
            r = FileRequirement(path=line)
        elif is_vcs(line):
            r = VCSRequirement.from_line(line)
        else:
            r = NamedRequirement.from_line(line)


@attrs
class PipfileRequirement(object):
    path = attrib(default=None)
    uri = attrib(default=None)
    name = attrib(default=None)
    extras = attrib(default=Factory(list))
    markers = attrib(default='')
    editable = attrib(default=False)
    vcs = attrib(validator=validators.optional(_validate_vcs), default=None)
    version = attrib(default='')
    index = attrib(default=None)
    _hash = attrib(default=None)
    hashes = attrib(default=Factory(list))
    ref = attrib(default=None)
    subdirectory = attrib(default=None)
    _link = attrib()

    @_link.default
    def _init_link(self):
        if not self.vcs:
            return None

        uri = self.uri if self.uri else path_to_url(os.path.abspath(self.path))
        return build_vcs_link(
            self.vcs,
            uri,
            name=self.name,
            ref=self.ref,
            subdirectory=self.subdirectory,
        )

    def __attrs_post_init__(self):
        if self._hash and not self.hashes:
            self.hashes = [self._hash]
        if self.vcs and self.uri and self._link:
            self.uri = _strip_ssh_from_git_uri(self._link.url)

    @classmethod
    def create(cls, name, pipfile):
        _pipfile = {}
        if hasattr(pipfile, 'keys'):
            _pipfile = dict(pipfile).copy()
        _pipfile['name'] = name
        _pipfile['version'] = cls._get_version(pipfile)
        editable = _pipfile.pop(
            'editable'
        ) if 'editable' in _pipfile else False
        vcs_type = first([vcs for vcs in VCS_LIST if vcs in _pipfile])
        vcs = _pipfile.pop(vcs_type) if vcs_type else None
        _pipfile_vcs_key = None
        if vcs:
            _pipfile_vcs_key = 'uri' if is_valid_url(vcs) else 'path'
        _pipfile['editable'] = editable
        _pipfile['vcs'] = vcs_type
        if _pipfile_vcs_key and not _pipfile.get(_pipfile_vcs_key):
            _pipfile[_pipfile_vcs_key] = vcs
        markers = _pipfile.get('markers')
        _extra_markers = [k for k in _pipfile.keys() if k in Evaluator.allowed_values.keys()]
        if _extra_markers:
            markers = list(markers) if markers else []
            for marker in _extra_markers:
                marker = marker.strip()
                marker_value = _pipfile.pop(marker).strip()
                marker_string = '{0}{1}'.format(marker, marker_value)
                markers.append(marker_string)
            _pipfile['markers'] = ' and '.join(markers)
        return cls(**_pipfile)

    @staticmethod
    def _get_version(pipfile_entry):
        if str(pipfile_entry) == '{}' or is_star(pipfile_entry):
            return ''

        elif isinstance(pipfile_entry, six.string_types):
            return pipfile_entry

        return pipfile_entry.get('version', '')

    @property
    def pip_version(self):
        if is_star(self.version):
            return self.name

        return '{0}{1}'.format(self.name, self.version)

    @property
    def requirement(self):
        req_uri = self.uri
        if self.path and not self.uri:
            req_uri = path_to_url(os.path.abspath(self.path))
        line = self._link.url if self._link else (req_uri if req_uri else self.pip_version)
        return PipenvRequirement._create_requirement(
            name=self.pip_version,
            path=self.path,
            uri=req_uri,
            markers=self.markers,
            extras=self.extras,
            index=self.index,
            hashes=self.hashes,
            vcs=self.vcs,
            editable=self.editable,
            link=self._link,
            line=line,
        )


@attrs
class PipenvRequirement(object):
    """Requirement for Pipenv Use

    Provides the following methods:
        - as_pipfile
        - as_lockfile
        - as_requirement
        - from_line
        - from_pipfile
        - resolve
    """
    _editable_prefix = '-e '
    path = attrib(default=None)
    uri = attrib(default=None)
    name = attrib(default=None)
    extras = attrib(default=Factory(list))
    markers = attrib(default='')
    editable = attrib(default=False)
    vcs = attrib(validator=validators.optional(_validate_vcs), default=None)
    link = attrib(default=None)
    line = attrib(default=None)
    requirement = attrib(default=None)
    index = attrib(default=Factory(list))
    specs = attrib(default='')
    hashes = attrib(default=Factory(list))

    @classmethod
    def create(cls, req):
        creation_attrs = {'requirement': req}
        for prop in [
            'name',
            'extras',
            'markers',
            'line',
            'link',
            'vcs',
            'editable',
            'uri',
            'path',
            'hashes',
            'index',
        ]:
            creation_attrs[prop] = getattr(req, prop, None)
        return cls(**creation_attrs)

    @property
    def original_line(self):
        _editable = ''
        if self.editable:
            _editable += self._editable_prefix
        if self.line and (self.path or self.uri):
            # original_line adds in -e if necessary
            if self.line.startswith(self._editable_prefix):
                return self.line

            return '{0}{1}'.format(_editable, self.line)

        return self.constructed_line

    @property
    def constructed_line(self):
        _editable = ''
        if self.editable:
            _editable += self._editable_prefix
        line = ''
        if self.link:
            line = '{0}{1}'.format(_editable, self.link.url)
        elif self.path or self.uri:
            line = '{0}{1}'.format(_editable, self.path or self.uri)
        else:
            line += self.name
        if not self.vcs:
            line = '{0}{1}{2}{3}{4}'.format(
                line,
                self.extras_as_pip,
                self.specifiers_as_pip,
                self.markers_as_pip,
                self.hashes_as_pip,
            )
        else:
            line = self.line
            if _editable == self._editable_prefix and not self.line.startswith(
                _editable
            ):
                line = '{0}{1}'.format(_editable, self.line)
            line = '{0}{1}{2}{3}'.format(
                line,
                self.extras_as_pip,
                self.markers_as_pip,
                self.hashes_as_pip,
            )
        return line

    @property
    def extras_as_pip(self):
        if self.extras:
            return '[{0}]'.format(','.join(self.extras))

        return ''

    @property
    def markers_as_pip(self):
        if self.markers:
            return '; {0}'.format(self.markers)

        return ''

    @property
    def specifiers_as_pip(self):
        if hasattr(self.requirement, 'specs'):
            return ','.join([''.join(spec) for spec in self.requirement.specs])

        return ''

    @property
    def hashes_as_pip(self):
        if self.hashes:
            if isinstance(self.hashes, six.string_types):
                return HASH_STRING.format(self.hashes)

            return ''.join([HASH_STRING.format(h) for h in self.hashes])

        return ''

    @classmethod
    def from_pipfile(cls, name, indexes, pipfile_entry):
        pipfile = PipfileRequirement.create(name, pipfile_entry)
        return cls.create(pipfile.requirement)

    @classmethod
    def from_line(cls, line):
        """Pre-clean requirement strings passed to the requirements parser.

        Ensures that we can accept both local and relative paths, file and VCS URIs,
        remote URIs, and package names, and that we pass only valid requirement strings
        to the requirements parser. Performs necessary modifications to requirements
        object if the user input was a local relative path.

        :param str dep: A requirement line
        :returns: :class:`requirements.Requirement` object
        """
        hashes = None
        if '--hash=' in line:
            hashes = line.split(' --hash=')
            line, hashes = hashes[0], hashes[1:]
        editable = False
        original_line = line
        _editable = ''
        if line.startswith('-e '):
            editable = True
            _editable += cls._editable_prefix
            line = line.split(' ', 1)[1]
        line, markers = cls._split_markers(line)
        line, extras = _strip_extras(line)
        req_dict = defaultdict(None)
        vcs = None
        if is_installable_file(line):
            req_dict = cls._prep_path(line)
            req_dict['original_line'] = '{0}{1}'.format(
                _editable, req_dict['original_line']
            )
        elif is_vcs(line):
            req_dict = cls._prep_vcs(line)
            vcs = first(
                _split_vcs_method(
                    req_dict.get('uri', req_dict.get('path', line))
                )
            )
            req_dict['original_line'] = '{0}{1}'.format(
                _editable, req_dict['original_line']
            )
        else:
            req_dict = {
                'line': line,
                'original_line': original_line,
                'name': multi_split(line, '!=<>~')[0],
            }
        return cls.create(
            cls._create_requirement(
                line=req_dict['original_line'],
                name=req_dict.get('name'),
                path=req_dict.get('path'),
                uri=req_dict.get('uri'),
                link=req_dict.get('link'),
                hashes=hashes,
                markers=markers,
                extras=extras,
                editable=editable,
                vcs=vcs,
            )
        )

    def as_pipfile(self):
        """"Converts a requirement to a Pipfile-formatted one."""
        req_dict = {}
        req = self.requirement
        req_dict = {}
        if req.local_file:
            hashable_path = req.uri or req.path
            dict_key = 'file' if req.uri else 'path'
            hashed_path = hashlib.sha256(
                hashable_path.encode('utf-8')
            ).hexdigest(
            )
            req_dict[dict_key] = hashable_path
            req_dict['name'] = hashed_path[
                len(hashed_path) - 7:
            ] if not req.vcs else req.name
        elif req.vcs:
            if req.name is None:
                raise ValueError(
                    'pipenv requires an #egg fragment for version controlled '
                    'dependencies. Please install remote dependency '
                    'in the form {0}#egg=<package-name>.'.format(req.uri)
                )

            if req.uri and req.uri.startswith('{0}+'.format(req.vcs)):
                if req_dict.get('uri'):
                    # req_dict['uri'] = req.uri[len(req.vcs) + 1:]
                    del req_dict['uri']
                req_dict.update(
                    {
                        req.vcs: req.uri[
                            len(req.vcs) + 1:
                        ] if req.uri else req.path
                    }
                )
            if req.subdirectory:
                req_dict.update({'subdirectory': req.subdirectory})
            if req.revision:
                req_dict.update({'ref': req.revision})
        elif req.specs:
            # Comparison operators: e.g. Django>1.10
            specs = ','.join([''.join(spec) for spec in req.specs])
            req_dict.update({'version': specs})
        else:
            req_dict.update({'version': '*'})
        if self.extras:
            req_dict.update({'extras': self.extras})
        if req.editable:
            req_dict.update({'editable': req.editable})
        if self.hashes:
            hash_key = 'hashes'
            hashes = self.hashes
            if isinstance(hashes, six.string_types) or len(hashes) == 1:
                hash_key = 'hash'
                if len(hashes) == 1:
                    hashes = first(hashes)
            req_dict.update({hash_key: hashes})
        if 'name' not in req_dict:
            req_dict['name'] = req.name or req.line or req.link.egg_fragment
        name = req_dict.pop('name')
        if len(req_dict.keys()) == 1 and req_dict.get('version'):
            return {name: req_dict.get('version')}

        return {name: req_dict}

    def as_requirement(self, project=None, include_index=False):
        """Creates a requirements.txt compatible output of the current dependency.

        :param project: Pipenv Project, defaults to None
        :param project: :class:`pipenv.project.Project`, optional
        :param include_index: Whether to include the resolved index, defaults to False
        :param include_index: bool, optional
        """
        line = self.constructed_line
        if include_index and not (self.requirement.local_file or self.vcs):
            from .utils import prepare_pip_source_args

            if self.index:
                pip_src_args = [project.get_source(self.index)]
            else:
                pip_src_args = project.sources
            index_string = ' '.join(prepare_pip_source_args(pip_src_args))
            line = '{0} {1}'.format(line, index_string)
        return line

    @staticmethod
    def _split_markers(line):
        """Split markers from a dependency"""
        if not any(line.startswith(uri_prefix) for uri_prefix in SCHEME_LIST):
            marker_sep = ';'
        else:
            marker_sep = '; '
        markers = None
        if marker_sep in line:
            line, markers = line.split(marker_sep, 1)
            markers = markers.strip() if markers else None
        return line, markers

    @staticmethod
    def _prep_path(line):
        _path = Path(line)
        link = Link(_path.absolute().as_uri())
        if _path.is_absolute() or _path.as_posix() == '.':
            path = _path.as_posix()
        else:
            path = get_converted_relative_path(line)
        name_or_url = link.egg_fragment if link.egg_fragment else link.url_without_fragment
        name = link.egg_fragment or link.show_url or link.filename
        return {
            'link': link,
            'path': path,
            'line': name_or_url,
            'original_line': line,
            'name': name,
        }

    @staticmethod
    def _prep_vcs(line):
        # Generate a Link object for parsing egg fragments
        link = Link(line)
        # Save the original path to store in the pipfile
        original_uri = link.url
        # Construct the requirement using proper git+ssh:// replaced uris or names if available
        formatted_line = _clean_git_uri(line)
        return {
            'link': link,
            'uri': formatted_line,
            'line': original_uri,
            'original_line': line,
            'name': link.egg_fragment,
        }

    @classmethod
    def _create_requirement(
        cls,
        line=None,
        name=None,
        path=None,
        uri=None,
        extras=None,
        markers=None,
        editable=False,
        vcs=None,
        link=None,
        hashes=None,
        index=None,
    ):
        _editable = cls._editable_prefix if editable else ''
        _line = line or uri or path or name
        # We don't want to only use the name on properly
        # formatted VCS inputs
        if link:
            _line = link.url
        elif vcs or is_vcs(_line):
            _line = uri or path or line
            _line = '{0}{1}'.format(_editable, _line)
        req = first(requirements.parse(_line))
        req.line = line or path or uri or getattr(link, 'url', req.line)
        if editable:
            req.editable = True
        if req.name and not any(
            getattr(req, prop) for prop in ['uri', 'path']
        ):
        ### This is the stuff I still need to reimplement
            if link and link.scheme.startswith('file') and path:
                req.path = path
                req.local_file = True
            elif link and uri:
                req.uri = link.url_without_fragment
        elif req.local_file and path and not req.vcs:
            req.uri = None
            req.path = path
        elif req.vcs and not req.local_file and uri != link.url:
            req.uri = _strip_ssh_from_git_uri(req.uri)
            req.line = line or _strip_ssh_from_git_uri(req.line)
        if markers:
            req.markers = markers
        if extras:
            # Bizarrely this is also what pip does...
            req.extras = first(
                requirements.parse(
                    'fakepkg{0}'.format(_extras_to_string(extras))
                )
            ).extras
        req.link = link
        if hashes:
            req.hashes = hashes
        if index:
            req.index = index
        return req


def _strip_ssh_from_git_uri(uri):
    """Return git+ssh:// formatted URI to git+git@ format"""
    if isinstance(uri, six.string_types):
        uri = uri.replace('git+ssh://', 'git+')
    return uri


def _clean_git_uri(uri):
    """Cleans VCS uris from pip9 format"""
    if isinstance(uri, six.string_types):
        # Add scheme for parsing purposes, this is also what pip does
        if uri.startswith('git+') and '://' not in uri:
            uri = uri.replace('git+', 'git+ssh://')
    return uri


def _split_vcs_method(uri):
    """Split a vcs+uri formatted uri into (vcs, uri)"""
    vcs_start = '{0}+'
    vcs = first(
        [vcs for vcs in VCS_LIST if uri.startswith(vcs_start.format(vcs))]
    )
    if vcs:
        vcs, uri = uri.split('+', 1)
    return vcs, uri


def _extras_to_string(extras):
    """Turn a list of extras into a string"""
    if isinstance(extras, six.string_types):
        if extras.startswith('['):
            return extras

        else:
            extras = [extras]
    return '[{0}]'.format(','.join(extras))


def build_vcs_link(
    vcs, uri, name=None, ref=None, subdirectory=None, extras= []
):
    vcs_start = '{0}+'.format(vcs)
    if not uri.startswith(vcs_start):
        uri = '{0}{1}'.format(vcs_start, uri)
    uri = _clean_git_uri(uri)
    if ref:
        uri = '{0}@{1}'.format(uri, ref)
    if name:
        uri = '{0}#egg={1}'.format(uri, name)
        if extras:
            extras = _extras_to_string(extras)
            uri = '{0}{1}'.format(uri, extras)
    if subdirectory:
        uri = '{0}&subdirectory={1}'.format(uri, subdirectory)
    return Link(uri)


def _get_version(pipfile_entry):
    if str(pipfile_entry) == '{}' or is_star(pipfile_entry):
        return ''

    elif isinstance(pipfile_entry, six.string_types):
        return pipfile_entry

    return pipfile_entry.get('version', '')
