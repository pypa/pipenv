# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import copy
import os
import sys

import attr
import tomlkit

import plette.models.base
import plette.pipfiles

from vistir.compat import FileNotFoundError, Path

from ..exceptions import RequirementError
from ..utils import is_editable, is_vcs, merge_items
from .project import ProjectFile
from .requirements import Requirement
from .utils import optional_instance_of

from ..environment import MYPY_RUNNING
if MYPY_RUNNING:
    from typing import Union, Any, Dict, Iterable, Sequence, Mapping, List, NoReturn
    package_type = Dict[str, Dict[str, Union[List[str], str]]]
    source_type = Dict[str, Union[str, bool]]
    sources_type = Iterable[source_type]
    meta_type = Dict[str, Union[int, Dict[str, str], sources_type]]
    lockfile_type = Dict[str, Union[package_type, meta_type]]


# Let's start by patching plette to make sure we can validate data without being broken
try:
    import cerberus
except ImportError:
    cerberus = None

VALIDATORS = plette.models.base.VALIDATORS


def patch_plette():
    # type: () -> None

    global VALIDATORS

    def validate(cls, data):
        # type: (Any, Dict[str, Any]) -> None
        if not cerberus:    # Skip validation if Cerberus is not available.
            return
        schema = cls.__SCHEMA__
        key = id(schema)
        try:
            v = VALIDATORS[key]
        except KeyError:
            v = VALIDATORS[key] = cerberus.Validator(schema, allow_unknown=True)
        if v.validate(dict(data), normalize=False):
            return
        raise plette.models.base.ValidationError(data, v)

    names = ["plette.models.base", plette.models.base.__name__]
    names = [name for name in names if name in sys.modules]
    for name in names:
        if name in sys.modules:
            module = sys.modules[name]
        else:
            module = plette.models.base
        original_fn = getattr(module, "validate")
        for key in ["__qualname__", "__name__", "__module__"]:
            original_val = getattr(original_fn, key, None)
            if original_val is not None:
                setattr(validate, key, original_val)
        setattr(module, "validate", validate)
        sys.modules[name] = module


patch_plette()


is_pipfile = optional_instance_of(plette.pipfiles.Pipfile)
is_path = optional_instance_of(Path)
is_projectfile = optional_instance_of(ProjectFile)


def reorder_source_keys(data):
    # type: ignore
    sources = data["source"]  # type: sources_type
    for i, entry in enumerate(sources):
        table = tomlkit.table()  # type: Mapping
        table["name"] = entry["name"]
        table["url"] = entry["url"]
        table["verify_ssl"] = entry["verify_ssl"]
        data["source"][i] = table
    return data


class PipfileLoader(plette.pipfiles.Pipfile):
    @classmethod
    def validate(cls, data):
        # type: (Dict[str, Any]) -> None
        for key, klass in plette.pipfiles.PIPFILE_SECTIONS.items():
            if key not in data or key == "source":
                continue
            try:
                klass.validate(data[key])
            except Exception:
                pass

    @classmethod
    def load(cls, f, encoding=None):
        # type: (Any, str) -> PipfileLoader
        content = f.read()
        if encoding is not None:
            content = content.decode(encoding)
        _data = tomlkit.loads(content)
        _data["source"] = _data.get("source", []) + _data.get("sources", [])
        _data = reorder_source_keys(_data)
        if "source" not in _data:
            if "sources" in _data:
                _data["source"] = _data["sources"]
                content = tomlkit.dumps(_data)
            else:
                # HACK: There is no good way to prepend a section to an existing
                # TOML document, but there's no good way to copy non-structural
                # content from one TOML document to another either. Modify the
                # TOML content directly, and load the new in-memory document.
                sep = "" if content.startswith("\n") else "\n"
                content = plette.pipfiles.DEFAULT_SOURCE_TOML + sep + content
        data = tomlkit.loads(content)
        instance = cls(data)
        instance._data = dict(instance._data)
        return instance

    def __getattribute__(self, key):
        # type: (str) -> Any
        if key == "source":
            return self._data[key]
        return super(PipfileLoader, self).__getattribute__(key)


@attr.s(slots=True)
class Pipfile(object):
    path = attr.ib(validator=is_path, type=Path)
    projectfile = attr.ib(validator=is_projectfile, type=ProjectFile)
    _pipfile = attr.ib(type=PipfileLoader)
    _pyproject = attr.ib(default=attr.Factory(tomlkit.document), type=tomlkit.toml_document.TOMLDocument)
    build_system = attr.ib(default=attr.Factory(dict), type=dict)
    requirements = attr.ib(default=attr.Factory(list), type=list)
    dev_requirements = attr.ib(default=attr.Factory(list), type=list)

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
    def pipfile(self):
        # type: () -> Union[PipfileLoader, plette.pipfiles.Pipfile]
        return self._pipfile

    def get_deps(self, dev=False, only=True):
        # type: (bool, bool) -> Dict[str, Dict[str, Union[List[str], str]]]
        deps = {}  # type: Dict[str, Dict[str, Union[List[str], str]]]
        if dev:
            deps.update(self.pipfile._data["dev-packages"])
            if only:
                return deps
        return merge_items([deps, self.pipfile._data["packages"]])

    def get(self, k):
        # type: (str) -> Any
        return self.__getitem__(k)

    def __contains__(self, k):
        # type: (str) -> bool
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
        return self._pipfile.requires.requires_python

    @property
    def allow_prereleases(self):
        # type: () -> bool
        return self._pipfile.get("pipenv", {}).get("allow_prereleases", False)

    @classmethod
    def read_projectfile(cls, path):
        # type: (str) -> ProjectFile
        """Read the specified project file and provide an interface for writing/updating.

        :param str path: Path to the target file.
        :return: A project file with the model and location for interaction
        :rtype: :class:`~requirementslib.models.project.ProjectFile`
        """
        pf = ProjectFile.read(
            path,
            PipfileLoader,
            invalid_ok=True
        )
        return pf

    @classmethod
    def load_projectfile(cls, path, create=False):
        # type: (str, bool) -> ProjectFile
        """Given a path, load or create the necessary pipfile.

        :param str path: Path to the project root or pipfile
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
        # type: (str, bool) -> Pipfile
        """Given a path, load or create the necessary pipfile.

        :param str path: Path to the project root or pipfile
        :param bool create: Whether to create the pipfile if not found, defaults to True
        :raises OSError: Thrown if the project root directory doesn't exist
        :raises FileNotFoundError: Thrown if the pipfile doesn't exist and ``create=False``
        :return: A pipfile instance pointing at the supplied project
        :rtype:: class:`~requirementslib.models.pipfile.Pipfile`
        """

        projectfile = cls.load_projectfile(path, create=create)
        pipfile = projectfile.model
        dev_requirements = [
            Requirement.from_pipfile(k, getattr(v, "_data", v)) for k, v in pipfile.get("dev-packages", {}).items()
        ]
        requirements = [
            Requirement.from_pipfile(k, getattr(v, "_data", v)) for k, v in pipfile.get("packages", {}).items()
        ]
        creation_args = {
            "projectfile": projectfile,
            "pipfile": pipfile,
            "dev_requirements": dev_requirements,
            "requirements": requirements,
            "path": Path(projectfile.location)
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

    def _read_pyproject(self):
        # type: () -> None
        pyproject = self.path.parent.joinpath("pyproject.toml")
        if pyproject.exists():
            self._pyproject = tomlkit.load(pyproject)
            build_system = self._pyproject.get("build-system", None)
            if not os.path.exists(self.path_to("setup.py")):
                if not build_system or not build_system.get("requires"):
                    build_system = {
                        "requires": ["setuptools>=38.2.5", "wheel"],
                        "build-backend": "setuptools.build_meta",
                    }
                self._build_system = build_system

    @property
    def build_requires(self):
        # type: () -> List[str]
        return self.build_system.get("requires", [])

    @property
    def build_backend(self):
        # type: () -> str
        return self.build_system.get("build-backend", None)
