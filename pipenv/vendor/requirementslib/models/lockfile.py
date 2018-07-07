# -*- coding: utf-8 -*-
from __future__ import absolute_import
import attr
import json
from .requirements import Requirement
from .utils import optional_instance_of
from .._compat import Path, FileNotFoundError


@attr.s
class Lockfile(object):
    dev_requirements = attr.ib(default=attr.Factory(list))
    requirements = attr.ib(default=attr.Factory(list))
    path = attr.ib(default=None, validator=optional_instance_of(Path))
    pipfile_hash = attr.ib(default=None)

    @classmethod
    def create(cls, project_path, lockfile_name="Pipfile.lock"):
        """Create a new lockfile instance

        :param project_path: Path to the project root
        :type project_path: str or :class:`~pathlib.Path`
        :returns: List[:class:`~requirementslib.Requirement`] objects
        """

        if not isinstance(project_path, Path):
            project_path = Path(project_path)
        lockfile_path = project_path / lockfile_name
        requirements = []
        dev_requirements = []
        if not lockfile_path.exists():
            raise FileNotFoundError("No such lockfile: %s" % lockfile_path)

        with lockfile_path.open(encoding="utf-8") as f:
            lockfile = json.loads(f.read())
        for k in lockfile["develop"].keys():
            dev_requirements.append(Requirement.from_pipfile(k, lockfile["develop"][k]))
        for k in lockfile["default"].keys():
            requirements.append(Requirement.from_pipfile(k, lockfile["default"][k]))
        return cls(
            path=lockfile_path,
            requirements=requirements,
            dev_requirements=dev_requirements,
        )

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
