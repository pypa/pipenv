# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import copy
import itertools
import os
import sys

from pipenv.vendor import attr
import plette.models.base
import plette.pipfiles
import tomlkit
from vistir.compat import FileNotFoundError, Path

from ..environment import MYPY_RUNNING
from ..exceptions import RequirementError
from ..utils import is_editable, is_vcs, merge_items
from .project import ProjectFile
from .requirements import Requirement
from .utils import get_url_name, optional_instance_of, tomlkit_value_to_python

if MYPY_RUNNING:
    from typing import Union, Any, Dict, Iterable, Mapping, List, Text

    package_type = Dict[Text, Dict[Text, Union[List[Text], Text]]]
    source_type = Dict[Text, Union[Text, bool]]
    sources_type = Iterable[source_type]
    meta_type = Dict[Text, Union[int, Dict[Text, Text], sources_type]]
    lockfile_type = Dict[Text, Union[package_type, meta_type]]


is_pipfile = optional_instance_of(plette.pipfiles.Pipfile)
is_path = optional_instance_of(Path)
is_projectfile = optional_instance_of(ProjectFile)


def reorder_source_keys(data):
    # type: (tomlkit.toml_document.TOMLDocument) -> tomlkit.toml_document.TOMLDocument
    sources = []  # type: sources_type
    for source_key in ["source", "sources"]:
        sources.extend(data.get(source_key, tomlkit.aot()).value)
    new_source_aot = tomlkit.aot()
    for entry in sources:
        table = tomlkit.table()  # type: tomlkit.items.Table
        source_entry = PipfileLoader.populate_source(entry.copy())
        for key in ["name", "url", "verify_ssl"]:
            table.update({key: source_entry[key]})
        new_source_aot.append(table)
    data["source"] = new_source_aot
    if data.get("sources", None):
        del data["sources"]
    return data


class PipfileLoader(plette.pipfiles.Pipfile):
    @classmethod
    def validate(cls, data):
        # type: (tomlkit.toml_document.TOMLDocument) -> None
        for key, klass in plette.pipfiles.PIPFILE_SECTIONS.items():
            if key not in data or key == "sources":
                continue
            try:
                klass.validate(data[key])
            except Exception:
                pass

    @classmethod
    def ensure_package_sections(cls, data):
        # type: (tomlkit.toml_document.TOMLDocument[Text, Any]) -> tomlkit.toml_document.TOMLDocument[Text, Any]
        """
        Ensure that all pipfile package sections are present in the given toml document

        :param :class:`~tomlkit.toml_document.TOMLDocument` data: The toml document to
            ensure package sections are present on
        :return: The updated toml document, ensuring ``packages`` and ``dev-packages``
            sections are present
        :rtype: :class:`~tomlkit.toml_document.TOMLDocument`
        """
        package_keys = (
            k for k in plette.pipfiles.PIPFILE_SECTIONS.keys() if k.endswith("packages")
        )
        for key in package_keys:
            if key not in data:
                data.update({key: tomlkit.table()})
        return data

    @classmethod
    def populate_source(cls, source):
        """Derive missing values of source from the existing fields."""
        # Only URL pararemter is mandatory, let the KeyError be thrown.
        if "name" not in source:
            source["name"] = get_url_name(source["url"])
        if "verify_ssl" not in source:
            source["verify_ssl"] = "https://" in source["url"]
        if not isinstance(source["verify_ssl"], bool):
            source["verify_ssl"] = str(source["verify_ssl"]).lower() == "true"
        return source

    @classmethod
    def load(cls, f, encoding=None):
        # type: (Any, Text) -> PipfileLoader
        content = f.read()
        if encoding is not None:
            content = content.decode(encoding)
        _data = tomlkit.loads(content)
        should_reload = "source" not in _data
        _data = reorder_source_keys(_data)
        if should_reload:
            if "sources" in _data:
                content = tomlkit.dumps(_data)
            else:
                # HACK: There is no good way to prepend a section to an existing
                # TOML document, but there's no good way to copy non-structural
                # content from one TOML document to another either. Modify the
                # TOML content directly, and load the new in-memory document.
                sep = "" if content.startswith("\n") else "\n"
                content = plette.pipfiles.DEFAULT_SOURCE_TOML + sep + content
        data = tomlkit.loads(content)
        data = cls.ensure_package_sections(data)
        instance = cls(data)
        instance._data = dict(instance._data)
        return instance

    def __contains__(self, key):
        # type: (Text) -> bool
        if key not in self._data:
            package_keys = self._data.get("packages", {}).keys()
            dev_package_keys = self._data.get("dev-packages", {}).keys()
            return any(key in pkg_list for pkg_list in (package_keys, dev_package_keys))
        return True

    def __getattribute__(self, key):
        # type: (Text) -> Any
        if key == "source":
            return self._data[key]
        return super(PipfileLoader, self).__getattribute__(key)


@attr.s(slots=True)
class Pipfile(object):
    path = attr.ib(validator=is_path, type=Path)
    projectfile = attr.ib(validator=is_projectfile, type=ProjectFile)
    _pipfile = attr.ib(type=PipfileLoader)
    _pyproject = attr.ib(
        default=attr.Factory(tomlkit.document), type=tomlkit.toml_document.TOMLDocument
    )
    build_system = attr.ib(default=attr.Factory(dict), type=dict)
    _requirements = attr.ib(default=attr.Factory(list), type=list)
    _dev_requirements = attr.ib(default=attr.Factory(list), type=list)

    @path.default
    def _get_path(self):
        # type: () -> Path
        return Path(os.curdir).absolute()

    @projectfile.default
    def _get_projectfile(self):
        # type: () -> ProjectFile
        return self.load_projectfile(os.curdir, create=False)

    @_pipfile.default
    def _get_pipfile(self):
        # type: () -> Union[plette.pipfiles.Pipfile, PipfileLoader]
        return self.projectfile.model

    @property
    def root(self):
        return self.path.parent

    @property
    def extended_keys(self):
        return [
            k
            for k in itertools.product(
                ("packages", "dev-packages"), ("", "vcs", "editable")
            )
        ]

    @property
    def pipfile(self):
        # type: () -> Union[PipfileLoader, plette.pipfiles.Pipfile]
        return self._pipfile

    def get_deps(self, dev=False, only=True):
        # type: (bool, bool) -> Dict[Text, Dict[Text, Union[List[Text], Text]]]
        deps = {}  # type: Dict[Text, Dict[Text, Union[List[Text], Text]]]
        if dev:
            deps.update(dict(self.pipfile._data.get("dev-packages", {})))
            if only:
                return deps
        return tomlkit_value_to_python(
            merge_items([deps, dict(self.pipfile._data.get("packages", {}))])
        )

    def get(self, k):
        # type: (Text) -> Any
        return self.__getitem__(k)

    def __contains__(self, k):
        # type: (Text) -> bool
        check_pipfile = k in self.extended_keys or self.pipfile.__contains__(k)
        if check_pipfile:
            return True
        return False

    def __getitem__(self, k, *args, **kwargs):
        # type: ignore
        retval = None
        pipfile = self._pipfile
        section = None
        pkg_type = None
        try:
            retval = pipfile[k]
        except KeyError:
            if "-" in k:
                section, _, pkg_type = k.rpartition("-")
                vals = getattr(pipfile.get(section, {}), "_data", {})
                vals = tomlkit_value_to_python(vals)
                if pkg_type == "vcs":
                    retval = {k: v for k, v in vals.items() if is_vcs(v)}
                elif pkg_type == "editable":
                    retval = {k: v for k, v in vals.items() if is_editable(v)}
            if retval is None:
                raise
        else:
            retval = getattr(retval, "_data", retval)
        return retval

    def __getattr__(self, k, *args, **kwargs):
        # type: ignore
        retval = None
        pipfile = super(Pipfile, self).__getattribute__("_pipfile")
        try:
            retval = super(Pipfile, self).__getattribute__(k)
        except AttributeError:
            retval = getattr(pipfile, k, None)
        if retval is not None:
            return retval
        return super(Pipfile, self).__getattribute__(k, *args, **kwargs)

    @property
    def requires_python(self):
        # type: () -> bool
        return getattr(
            self._pipfile.requires,
            "python_version",
            getattr(self._pipfile.requires, "python_full_version", None),
        )

    @property
    def allow_prereleases(self):
        # type: () -> bool
        return self._pipfile.get("pipenv", {}).get("allow_prereleases", False)

    @classmethod
    def read_projectfile(cls, path):
        # type: (Text) -> ProjectFile
        """Read the specified project file and provide an interface for writing/updating.

        :param Text path: Path to the target file.
        :return: A project file with the model and location for interaction
        :rtype: :class:`~requirementslib.models.project.ProjectFile`
        """
        pf = ProjectFile.read(path, PipfileLoader, invalid_ok=True)
        return pf

    @classmethod
    def load_projectfile(cls, path, create=False):
        # type: (Text, bool) -> ProjectFile
        """
        Given a path, load or create the necessary pipfile.

        :param Text path: Path to the project root or pipfile
        :param bool create: Whether to create the pipfile if not found, defaults to True
        :raises OSError: Thrown if the project root directory doesn't exist
        :raises FileNotFoundError: Thrown if the pipfile doesn't exist and ``create=False``
        :return: A project file instance for the supplied project
        :rtype: :class:`~requirementslib.models.project.ProjectFile`
        """
        if not path:
            raise RuntimeError("Must pass a path to classmethod 'Pipfile.load'")
        if not isinstance(path, Path):
            path = Path(path).absolute()
        pipfile_path = path if path.is_file() else path.joinpath("Pipfile")
        project_path = pipfile_path.parent
        if not project_path.exists():
            raise FileNotFoundError("%s is not a valid project path!" % path)
        elif not pipfile_path.exists() or not pipfile_path.is_file():
            if not create:
                raise RequirementError("%s is not a valid Pipfile" % pipfile_path)
        return cls.read_projectfile(pipfile_path.as_posix())

    @classmethod
    def load(cls, path, create=False):
        # type: (Text, bool) -> Pipfile
        """
        Given a path, load or create the necessary pipfile.

        :param Text path: Path to the project root or pipfile
        :param bool create: Whether to create the pipfile if not found, defaults to True
        :raises OSError: Thrown if the project root directory doesn't exist
        :raises FileNotFoundError: Thrown if the pipfile doesn't exist and ``create=False``
        :return: A pipfile instance pointing at the supplied project
        :rtype:: class:`~requirementslib.models.pipfile.Pipfile`
        """

        projectfile = cls.load_projectfile(path, create=create)
        pipfile = projectfile.model
        creation_args = {
            "projectfile": projectfile,
            "pipfile": pipfile,
            "path": Path(projectfile.location),
        }
        return cls(**creation_args)

    def write(self):
        # type: () -> None
        self.projectfile.model = copy.deepcopy(self._pipfile)
        self.projectfile.write()

    @property
    def dev_packages(self):
        # type: () -> List[Requirement]
        return self.dev_requirements

    @property
    def packages(self):
        # type: () -> List[Requirement]
        return self.requirements

    @property
    def dev_requirements(self):
        # type: () -> List[Requirement]
        if not self._dev_requirements:
            packages = tomlkit_value_to_python(self.pipfile.get("dev-packages", {}))
            self._dev_requirements = [
                Requirement.from_pipfile(k, v)
                for k, v in packages.items()
                if v is not None
            ]
        return self._dev_requirements

    @property
    def requirements(self):
        # type: () -> List[Requirement]
        if not self._requirements:
            packages = tomlkit_value_to_python(self.pipfile.get("packages", {}))
            self._requirements = [
                Requirement.from_pipfile(k, v)
                for k, v in packages.items()
                if v is not None
            ]
        return self._requirements

    def _read_pyproject(self):
        # type: () -> None
        pyproject = self.path.parent.joinpath("pyproject.toml")
        if pyproject.exists():
            self._pyproject = tomlkit.loads(pyproject.read_text())
            build_system = self._pyproject.get("build-system", None)
            if build_system and not build_system.get("build_backend"):
                build_system["build-backend"] = "setuptools.build_meta:__legacy__"
            elif not build_system or not build_system.get("requires"):
                build_system = {
                    "requires": ["setuptools>=40.8", "wheel"],
                    "build-backend": "setuptools.build_meta:__legacy__",
                }
            self.build_system = build_system

    @property
    def build_requires(self):
        # type: () -> List[Text]
        if not self.build_system:
            self._read_pyproject()
        return self.build_system.get("requires", [])

    @property
    def build_backend(self):
        # type: () -> Text
        pyproject = self.path.parent.joinpath("pyproject.toml")
        if not self.build_system:
            self._read_pyproject()
        return self.build_system.get("build-backend", None)
