# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals, print_function

import attr
import copy
import os

from vistir.compat import Path, FileNotFoundError

from .requirements import Requirement
from .project import ProjectFile
from .utils import optional_instance_of
from ..exceptions import RequirementError
import plette.pipfiles


is_pipfile = optional_instance_of(plette.pipfiles.Pipfile)
is_path = optional_instance_of(Path)
is_projectfile = optional_instance_of(ProjectFile)


@attr.s(slots=True)
class Pipfile(object):
    path = attr.ib(validator=is_path, type=Path)
    projectfile = attr.ib(validator=is_projectfile, type=ProjectFile)
    _pipfile = attr.ib(type=plette.pipfiles.Pipfile)
    requirements = attr.ib(default=attr.Factory(list), type=list)
    dev_requirements = attr.ib(default=attr.Factory(list), type=list)

    @path.default
    def _get_path(self):
        return Path(os.curdir).absolute()

    @projectfile.default
    def _get_projectfile(self):
        return self.load_projectfile(os.curdir, create=False)

    @_pipfile.default
    def _get_pipfile(self):
        return self.projectfile.model

    def __getattr__(self, k, *args, **kwargs):
        retval = None
        pipfile = super(Pipfile, self).__getattribute__("_pipfile")
        try:
            return super(Pipfile, self).__getattribute__(k)
        except AttributeError:
            retval = getattr(pipfile, k, None)
        if not retval:
            retval = super(Pipfile, self).__getattribute__(k, *args, **kwargs)
        return retval

    @property
    def requires_python(self):
        return self._pipfile.requires.requires_python

    @property
    def allow_prereleases(self):
        return self._pipfile.get("pipenv", {}).get("allow_prereleases", False)

    @classmethod
    def read_projectfile(cls, path):
        """Read the specified project file and provide an interface for writing/updating.

        :param str path: Path to the target file.
        :return: A project file with the model and location for interaction
        :rtype: :class:`~requirementslib.models.project.ProjectFile`
        """
        pf = ProjectFile.read(
            path,
            plette.pipfiles.Pipfile,
            invalid_ok=True
        )
        return pf

    @classmethod
    def load_projectfile(cls, path, create=False):
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
            path = Path(path)
        pipfile_path = path if path.name == "Pipfile" else path.joinpath("Pipfile")
        project_path = pipfile_path.parent
        if not project_path.exists():
            raise FileNotFoundError("%s is not a valid project path!" % path)
        elif not pipfile_path.exists() or not pipfile_path.is_file():
            if not create:
                raise RequirementError("%s is not a valid Pipfile" % pipfile_path)
        return cls.read_projectfile(pipfile_path.as_posix())

    @classmethod
    def load(cls, path, create=False):
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
            Requirement.from_pipfile(k, v._data) for k, v in pipfile.get("dev-packages", {}).items()
        ]
        requirements = [
            Requirement.from_pipfile(k, v._data) for k, v in pipfile.get("packages", {}).items()
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
        self.projectfile.model = copy.deepcopy(self._pipfile)
        self.projectfile.write()

    @property
    def dev_packages(self, as_requirements=True):
        if as_requirements:
            return self.dev_requirements
        return self._pipfile.get('dev-packages', {})

    @property
    def packages(self, as_requirements=True):
        if as_requirements:
            return self.requirements
        return self._pipfile.get('packages', {})
