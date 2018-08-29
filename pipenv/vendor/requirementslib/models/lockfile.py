# -*- coding: utf-8 -*-
from __future__ import absolute_import

import json
import os

import plette.lockfiles
import six

from vistir.compat import Path
from vistir.contextmanagers import atomic_open_for_write

from .requirements import Requirement


DEFAULT_NEWLINES = u"\n"


def preferred_newlines(f):
    if isinstance(f.newlines, six.text_type):
        return f.newlines
    return DEFAULT_NEWLINES


class Lockfile(plette.lockfiles.Lockfile):
    def __init__(self, *args, **kwargs):
        path = kwargs.pop("path", None)
        self._requirements = kwargs.pop("requirements", [])
        self._dev_requirements = kwargs.pop("dev_requirements", [])
        self.path = Path(path) if path else None
        self.newlines = u"\n"
        super(Lockfile, self).__init__(*args, **kwargs)

    @classmethod
    def load(cls, path):
        if not path:
            path = os.curdir
        path = Path(path).absolute()
        if path.is_dir():
            path = path / "Pipfile.lock"
        elif path.name == "Pipfile":
            path = path.parent / "Pipfile.lock"
        if not path.exists():
            raise OSError("Path does not exist: %s" % path)
        return cls.create(path.parent, lockfile_name=path.name)

    @classmethod
    def create(cls, project_path, lockfile_name="Pipfile.lock"):
        """Create a new lockfile instance

        :param project_path: Path to  project root
        :type project_path: str or :class:`~pathlib.Path`
        :returns: List[:class:`~requirementslib.Requirement`] objects
        """

        if not isinstance(project_path, Path):
            project_path = Path(project_path)
        lockfile_path = project_path / lockfile_name
        with lockfile_path.open(encoding="utf-8") as f:
            lockfile = super(Lockfile, cls).load(f)
            lockfile.newlines = preferred_newlines(f)
        lockfile.path = lockfile_path
        return lockfile

    def get_requirements(self, dev=False):
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
        return [{name: entry._data} for name, entry in self.develop.items()]

    @property
    def requirements_list(self):
        return [{name: entry._data} for name, entry in self.develop.items()]

    def write(self):
        open_kwargs = {"newline": self.newlines}
        with atomic_open_for_write(self.path.as_posix(), **open_kwargs) as f:
            super(Lockfile, self).dump(f, encoding="utf-8")

    def as_requirements(self, include_hashes=False, dev=False):
        """Returns a list of requirements in pip-style format"""
        lines = []
        section = self.dev_requirements if dev else self.requirements
        for req in section:
            r = req.as_line()
            if not include_hashes:
                r = r.split("--hash", 1)[0]
            lines.append(r.strip())
        return lines
