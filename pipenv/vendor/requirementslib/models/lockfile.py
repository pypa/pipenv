import copy
import itertools
import os
from json import JSONDecodeError
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from pipenv.vendor.plette import lockfiles
from pipenv.vendor.pydantic import Field

from ..exceptions import LockfileCorruptException, MissingParameter, PipfileNotFound
from ..utils import is_editable, is_vcs, merge_items
from .common import ReqLibBaseModel
from .project import ProjectFile
from .requirements import Requirement

DEFAULT_NEWLINES = "\n"


def preferred_newlines(f):
    if isinstance(f.newlines, str):
        return f.newlines
    return DEFAULT_NEWLINES


class Lockfile(ReqLibBaseModel):
    path: Path = Field(
        default_factory=lambda: Path(os.curdir).joinpath("Pipfile.lock").absolute()
    )
    _requirements: Optional[list] = Field(default_factory=list)
    _dev_requirements: Optional[list] = Field(default_factory=list)
    projectfile: ProjectFile = None
    lockfile: lockfiles.Lockfile
    newlines: str = DEFAULT_NEWLINES

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        # keep_untouched = (cached_property,)

    @property
    def section_keys(self):
        return set(self.lockfile.keys()) - {"_meta"}

    @property
    def extended_keys(self):
        return [k for k in itertools.product(self.section_keys, ["", "vcs", "editable"])]

    def get(self, k):
        return self.__getitem__(k)

    def __contains__(self, k):
        check_lockfile = k in self.extended_keys or self.lockfile.__contains__(k)
        if check_lockfile:
            return True
        return super(Lockfile, self).__contains__(k)

    def __setitem__(self, k, v):
        lockfile = self.lockfile
        lockfile.__setitem__(k, v)

    def __getitem__(self, k, *args, **kwargs):
        retval = None
        lockfile = self.lockfile
        try:
            retval = lockfile[k]
        except KeyError:
            if "-" in k:
                section, _, pkg_type = k.rpartition("-")
                vals = getattr(lockfile.get(section, {}), "_data", {})
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
        lockfile = self.lockfile
        try:
            return super(Lockfile, self).__getattribute__(k)
        except AttributeError:
            retval = getattr(lockfile, k, None)
        if retval is not None:
            return retval
        return super(Lockfile, self).__getattribute__(k, *args, **kwargs)

    def get_deps(self, dev=False, only=True):
        deps = {}
        if dev:
            deps.update(self.develop._data)
            if only:
                return deps
        deps = merge_items([deps, self.default._data])
        return deps

    @classmethod
    def read_projectfile(cls, path):
        pf = ProjectFile.read(path, lockfiles.Lockfile, invalid_ok=True)
        return pf

    @classmethod
    def lockfile_from_pipfile(cls, pipfile_path):
        from .pipfile import Pipfile

        if os.path.isfile(pipfile_path):
            if not os.path.isabs(pipfile_path):
                pipfile_path = os.path.abspath(pipfile_path)
            pipfile = Pipfile.load(os.path.dirname(pipfile_path))
            return lockfiles.Lockfile.with_meta_from(pipfile.pipfile)
        raise PipfileNotFound(pipfile_path)

    @classmethod
    def load_projectfile(
        cls, path: Optional[str] = None, create: bool = True, data: Optional[Dict] = None
    ) -> "ProjectFile":
        if not path:
            path = os.curdir
        path = Path(path).absolute()
        project_path = path if path.is_dir() else path.parent
        lockfile_path = path if path.is_file() else project_path / "Pipfile.lock"
        if not project_path.exists():
            raise OSError(f"Project does not exist: {project_path.as_posix()}")
        elif not lockfile_path.exists() and not create:
            raise FileNotFoundError(
                f"Lockfile does not exist: {lockfile_path.as_posix()}"
            )
        projectfile = cls.read_projectfile(lockfile_path.as_posix())
        if not lockfile_path.exists():
            if not data:
                pipfile = project_path.joinpath("Pipfile")
                lf = cls.lockfile_from_pipfile(pipfile)
            else:
                lf = lockfiles.Lockfile(data)
            projectfile.model = lf
        else:
            if data:
                raise ValueError("Cannot pass data when loading existing lockfile")
            with open(lockfile_path.as_posix(), "r") as f:
                projectfile.model = lockfiles.Lockfile.load(f)
        return projectfile

    @classmethod
    def from_data(
        cls, path: Optional[str], data: Optional[Dict], meta_from_project: bool = True
    ) -> "Lockfile":
        if path is None:
            raise MissingParameter("path")
        if data is None:
            raise MissingParameter("data")
        if not isinstance(data, dict):
            raise TypeError("Expecting a dictionary for parameter 'data'")
        path = os.path.abspath(str(path))
        if os.path.isdir(path):
            project_path = path
        elif not os.path.isdir(path) and os.path.isdir(os.path.dirname(path)):
            project_path = os.path.dirname(path)
        pipfile_path = os.path.join(project_path, "Pipfile")
        lockfile_path = os.path.join(project_path, "Pipfile.lock")
        if meta_from_project:
            lockfile = cls.lockfile_from_pipfile(pipfile_path)
            lockfile.update(data)
        else:
            lockfile = lockfiles.Lockfile(data)
        projectfile = ProjectFile(
            line_ending=DEFAULT_NEWLINES, location=lockfile_path, model=lockfile
        )
        return cls(
            projectfile=projectfile,
            lockfile=lockfile,
            newlines=projectfile.line_ending,
            path=Path(projectfile.location),
        )

    @classmethod
    def load(cls, path: Optional[str], create: bool = True) -> "Lockfile":
        try:
            projectfile = cls.load_projectfile(path, create=create)
        except JSONDecodeError:
            path = os.path.abspath(path)
            path = Path(
                os.path.join(path, "Pipfile.lock") if os.path.isdir(path) else path
            )
            formatted_path = path.as_posix()
            backup_path = f"{formatted_path}.bak"
            LockfileCorruptException.show(formatted_path, backup_path=backup_path)
            path.rename(backup_path)
            cls.load(formatted_path, create=True)
        lockfile_path = Path(projectfile.location)
        creation_args = {
            "projectfile": projectfile,
            "lockfile": projectfile.model,
            "newlines": projectfile.line_ending,
            "path": lockfile_path,
        }
        return cls(**creation_args)

    @classmethod
    def create(cls, path: Optional[str], create: bool = True) -> "Lockfile":
        return cls.load(path, create=create)

    def get_section(self, name: str) -> Optional[Dict]:
        return self.lockfile.get(name)

    @property
    def develop(self) -> Dict:
        return self.lockfile.develop

    @property
    def default(self) -> Dict:
        return self.lockfile.default

    def get_requirements(
        self, dev: bool = True, only: bool = False, categories: Optional[List[str]] = None
    ) -> Iterator[Requirement]:
        if categories:
            deps = {}
            for category in categories:
                if category == "packages":
                    category = "default"
                elif category == "dev-packages":
                    category = "develop"
                try:
                    category_deps = self[category]
                except KeyError:
                    category_deps = {}
                    self.lockfile[category] = category_deps
                deps = merge_items([deps, category_deps])
        else:
            deps = self.get_deps(dev=dev, only=only)
        for k, v in deps.items():
            yield Requirement.from_pipfile(k, v)

    def requirements_list(self, category: str) -> List[Dict]:
        if self.lockfile.get(category):
            return [
                {name: entry._data} for name, entry in self.lockfile[category].items()
            ]
        return []

    def as_requirements(self, category: str, include_hashes: bool = False) -> List[str]:
        lines = []
        section = list(self.get_requirements(categories=[category]))
        for req in section:
            kwargs = {"include_hashes": include_hashes}
            if req.editable:
                kwargs["include_markers"] = False
            r = req.as_line(**kwargs)
            lines.append(r.strip())
        return lines

    def write(self) -> None:
        self.projectfile.model = copy.deepcopy(self.lockfile)
        self.projectfile.write()
