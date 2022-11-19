import copy
import itertools
import os
from json import JSONDecodeError
from pathlib import Path

import pipenv.vendor.attr as attr
from pipenv.vendor.plette import lockfiles

from ..exceptions import LockfileCorruptException, MissingParameter, PipfileNotFound
from ..utils import is_editable, is_vcs, merge_items
from .project import ProjectFile
from .requirements import Requirement
from .utils import optional_instance_of

DEFAULT_NEWLINES = "\n"


def preferred_newlines(f):
    if isinstance(f.newlines, str):
        return f.newlines
    return DEFAULT_NEWLINES


is_lockfile = optional_instance_of(lockfiles.Lockfile)
is_projectfile = optional_instance_of(ProjectFile)


@attr.s(slots=True)
class Lockfile(object):
    path = attr.ib(validator=optional_instance_of(Path), type=Path)
    _requirements = attr.ib(default=attr.Factory(list), type=list)
    _dev_requirements = attr.ib(default=attr.Factory(list), type=list)
    projectfile = attr.ib(validator=is_projectfile, type=ProjectFile)
    _lockfile = attr.ib(validator=is_lockfile, type=lockfiles.Lockfile)
    newlines = attr.ib(default=DEFAULT_NEWLINES, type=str)

    @path.default
    def _get_path(self):
        return Path(os.curdir).joinpath("Pipfile.lock").absolute()

    @projectfile.default
    def _get_projectfile(self):
        return self.load_projectfile(self.path)

    @_lockfile.default
    def _get_lockfile(self):
        return self.projectfile.model

    @property
    def lockfile(self):
        return self._lockfile

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
        lockfile = self._lockfile
        lockfile.__setitem__(k, v)

    def __getitem__(self, k, *args, **kwargs):
        retval = None
        lockfile = self._lockfile
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
        lockfile = super(Lockfile, self).__getattribute__("_lockfile")
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
        """Read the specified project file and provide an interface for
        writing/updating.

        :param str path: Path to the target file.
        :return: A project file with the model and location for interaction
        :rtype: :class:`~requirementslib.models.project.ProjectFile`
        """
        pf = ProjectFile.read(path, lockfiles.Lockfile, invalid_ok=True)
        return pf

    @classmethod
    def lockfile_from_pipfile(cls, pipfile_path):
        from .pipfile import Pipfile

        if os.path.isfile(pipfile_path):
            if not os.path.isabs(pipfile_path):
                pipfile_path = os.path.abspath(pipfile_path)
            pipfile = Pipfile.load(os.path.dirname(pipfile_path))
            return lockfiles.Lockfile.with_meta_from(pipfile._pipfile)
        raise PipfileNotFound(pipfile_path)

    @classmethod
    def load_projectfile(cls, path, create=True, data=None):
        """Given a path, load or create the necessary lockfile.

        :param str path: Path to the project root or lockfile
        :param bool create: Whether to create the lockfile if not found, defaults to True
        :raises OSError: Thrown if the project root directory doesn't exist
        :raises FileNotFoundError: Thrown if the lockfile doesn't exist and ``create=False``
        :return: A project file instance for the supplied project
        :rtype: :class:`~requirementslib.models.project.ProjectFile`
        """

        if not path:
            path = os.curdir
        path = Path(path).absolute()
        project_path = path if path.is_dir() else path.parent
        lockfile_path = path if path.is_file() else project_path / "Pipfile.lock"
        if not project_path.exists():
            raise OSError("Project does not exist: %s" % project_path.as_posix())
        elif not lockfile_path.exists() and not create:
            raise FileNotFoundError(
                "Lockfile does not exist: %s" % lockfile_path.as_posix()
            )
        projectfile = cls.read_projectfile(lockfile_path.as_posix())
        if not lockfile_path.exists():
            if not data:
                path_str = lockfile_path.as_posix()
                if path_str[-5:] == ".lock":
                    pipfile = Path(path_str[:-5])
                else:
                    pipfile = project_path.joinpath("Pipfile")
                lf = cls.lockfile_from_pipfile(pipfile)
            else:
                lf = lockfiles.Lockfile(data)
            projectfile.model = lf
        return projectfile

    @classmethod
    def from_data(cls, path, data, meta_from_project=True):
        """Create a new lockfile instance from a dictionary.

        :param str path: Path to the project root.
        :param dict data: Data to load into the lockfile.
        :param bool meta_from_project: Attempt to populate the meta section from the
            project root, default True.
        """

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
    def load(cls, path, create=True):
        """Create a new lockfile instance.

        :param project_path: Path to  project root or lockfile
        :type project_path: str or :class:`pathlib.Path`
        :param str lockfile_name: Name of the lockfile in the project root directory
        :param pipfile_path: Path to the project pipfile
        :type pipfile_path: :class:`pathlib.Path`
        :returns: A new lockfile representing the supplied project paths
        :rtype: :class:`~requirementslib.models.lockfile.Lockfile`
        """

        try:
            projectfile = cls.load_projectfile(path, create=create)
        except JSONDecodeError:
            path = os.path.abspath(path)
            path = Path(
                os.path.join(path, "Pipfile.lock") if os.path.isdir(path) else path
            )
            formatted_path = path.as_posix()
            backup_path = "%s.bak" % formatted_path
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
    def create(cls, path, create=True):
        return cls.load(path, create=create)

    def get_section(self, name):
        return self._lockfile.get(name)

    @property
    def develop(self):
        return self._lockfile.develop

    @property
    def default(self):
        return self._lockfile.default

    def get_requirements(self, dev=True, only=False, categories=None):
        """Produces a generator which generates requirements from the desired
        section.

        :param bool dev: Indicates whether to use dev requirements, defaults to False
        :return: Requirements from the relevant pipfile
        :rtype: :class:`Iterator[~requirementslib.models.requirements.Requirement]`
        """
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
                    self._lockfile[category] = category_deps
                deps = merge_items([deps, category_deps])
        else:
            deps = self.get_deps(dev=dev, only=only)
        for k, v in deps.items():
            yield Requirement.from_pipfile(k, v)

    def requirements_list(self, category):
        if self._lockfile.get(category):
            return [
                {name: entry._data} for name, entry in self._lockfile[category].items()
            ]
        return []

    def as_requirements(self, category, include_hashes=False):
        """Returns a list of requirements in pip-style format."""
        lines = []
        section = list(self.get_requirements(categories=[category]))
        for req in section:
            kwargs = {"include_hashes": include_hashes}
            if req.editable:
                kwargs["include_markers"] = False
            r = req.as_line(**kwargs)
            lines.append(r.strip())
        return lines

    def write(self):
        self.projectfile.model = copy.deepcopy(self._lockfile)
        self.projectfile.write()
