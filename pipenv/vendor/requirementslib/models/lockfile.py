# -*- coding: utf-8 -*-
from __future__ import absolute_import

import copy
import os

import attr
import plette.lockfiles
import six

from vistir.compat import Path, FileNotFoundError

from .project import ProjectFile
from .requirements import Requirement

from .utils import optional_instance_of

DEFAULT_NEWLINES = u"\n"


def preferred_newlines(f):
    if isinstance(f.newlines, six.text_type):
        return f.newlines
    return DEFAULT_NEWLINES


is_lockfile = optional_instance_of(plette.lockfiles.Lockfile)
is_projectfile = optional_instance_of(ProjectFile)


@attr.s(slots=True)
class Lockfile(object):
    path = attr.ib(validator=optional_instance_of(Path), type=Path)
    _requirements = attr.ib(default=attr.Factory(list), type=list)
    _dev_requirements = attr.ib(default=attr.Factory(list), type=list)
    projectfile = attr.ib(validator=is_projectfile, type=ProjectFile)
    _lockfile = attr.ib(validator=is_lockfile, type=plette.lockfiles.Lockfile)
    newlines = attr.ib(default=DEFAULT_NEWLINES, type=six.text_type)

    @path.default
    def _get_path(self):
        return Path(os.curdir).absolute()

    @projectfile.default
    def _get_projectfile(self):
        return self.load_projectfile(self.path)

    @_lockfile.default
    def _get_lockfile(self):
        return self.projectfile.lockfile

    def __getattr__(self, k, *args, **kwargs):
        retval = None
        lockfile = super(Lockfile, self).__getattribute__("_lockfile")
        try:
            return super(Lockfile, self).__getattribute__(k)
        except AttributeError:
            retval = getattr(lockfile, k, None)
        if not retval:
            retval = super(Lockfile, self).__getattribute__(k, *args, **kwargs)
        return retval

    @classmethod
    def read_projectfile(cls, path):
        """Read the specified project file and provide an interface for writing/updating.

        :param str path: Path to the target file.
        :return: A project file with the model and location for interaction
        :rtype: :class:`~requirementslib.models.project.ProjectFile`
        """

        pf = ProjectFile.read(
            path,
            plette.lockfiles.Lockfile,
            invalid_ok=True
        )
        return pf

    @classmethod
    def load_projectfile(cls, path, create=True):
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
        lockfile_path = project_path / "Pipfile.lock"
        if not project_path.exists():
            raise OSError("Project does not exist: %s" % project_path.as_posix())
        elif not lockfile_path.exists() and not create:
            raise FileNotFoundError("Lockfile does not exist: %s" % lockfile_path.as_posix())
        projectfile = cls.read_projectfile(lockfile_path.as_posix())
        return projectfile

    @classmethod
    def load(cls, path, create=True):
        """Create a new lockfile instance.

        :param project_path: Path to  project root
        :type project_path: str or :class:`pathlib.Path`
        :param str lockfile_name: Name of the lockfile in the project root directory
        :param pipfile_path: Path to the project pipfile
        :type pipfile_path: :class:`pathlib.Path`
        :returns: A new lockfile representing the supplied project paths
        :rtype: :class:`~requirementslib.models.lockfile.Lockfile`
        """

        projectfile = cls.load_projectfile(path, create=create)
        lockfile_path = Path(projectfile.location)
        creation_args = {
            "projectfile": projectfile,
            "lockfile": projectfile.model,
            "newlines": projectfile.line_ending,
            "path": lockfile_path
        }
        return cls(**creation_args)

    @classmethod
    def create(cls, path, create=True):
        return cls.load(path, create=create)

    @property
    def develop(self):
        return self._lockfile.develop

    @property
    def default(self):
        return self._lockfile.default

    def get_requirements(self, dev=False):
        """Produces a generator which generates requirements from the desired section.

        :param bool dev: Indicates whether to use dev requirements, defaults to False
        :return: Requirements from the relevant the relevant pipfile
        :rtype: :class:`~requirementslib.models.requirements.Requirement`
        """

        section = self.develop if dev else self.default
        for k in section.keys():
            yield Requirement.from_pipfile(k, section[k]._data)

    @property
    def dev_requirements(self):
        if not self._dev_requirements:
            self._dev_requirements = list(self.get_requirements(dev=True))
        return self._dev_requirements

    @property
    def requirements(self):
        if not self._requirements:
            self._requirements = list(self.get_requirements(dev=False))
        return self._requirements

    @property
    def dev_requirements_list(self):
        return [{name: entry._data} for name, entry in self._lockfile.develop.items()]

    @property
    def requirements_list(self):
        return [{name: entry._data} for name, entry in self._lockfile.default.items()]

    def write(self):
        self.projectfile.model = copy.deepcopy(self._lockfile)
        self.projectfile.write()

    def as_requirements(self, include_hashes=False, dev=False):
        """Returns a list of requirements in pip-style format"""
        lines = []
        section = self.dev_requirements if dev else self.requirements
        for req in section:
            kwargs = {
                "include_hashes": include_hashes,
            }
            if req.editable:
                kwargs["include_markers"] = False
            r = req.as_line(**kwargs)
            lines.append(r.strip())
        return lines
