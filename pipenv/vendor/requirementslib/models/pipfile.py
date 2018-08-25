# -*- coding: utf-8 -*-
import os

from vistir.compat import Path

from .requirements import Requirement
from ..exceptions import RequirementError
import plette.pipfiles


class Pipfile(plette.pipfiles.Pipfile):

    @property
    def requires_python(self):
        return self.requires.requires_python

    @property
    def allow_prereleases(self):
        return self.get("pipenv", {}).get("allow_prereleases", False)

    @classmethod
    def load(cls, path):
        if not isinstance(path, Path):
            path = Path(path)
        pipfile_path = path / "Pipfile"
        if not path.exists():
            raise FileNotFoundError("%s is not a valid project path!" % path)
        elif not pipfile_path.exists() or not pipfile_path.is_file():
            raise RequirementError("%s is not a valid Pipfile" % pipfile_path)
        with pipfile_path.open(encoding="utf-8") as fp:
            pipfile = super(Pipfile, cls).load(fp)
        pipfile.dev_requirements = [
            Requirement.from_pipfile(k, v) for k, v in pipfile.dev_packages.items()
        ]
        pipfile.requirements = [
            Requirement.from_pipfile(k, v) for k, v in pipfile.packages.items()
        ]
        pipfile.path = pipfile_path
        return pipfile

    # def resolve(self):
    # It would be nice to still use this api someday
    #     option_sources = [s.expanded for s in self.sources]
    #     pip_args = []
    #     if self.pipenv.allow_prereleases:
    #         pip_args.append('--pre')
    #     pip_options = get_pip_options(pip_args, sources=option_sources)
    #     finder = get_finder(sources=option_sources, pip_options=pip_options)
    #     resolver = DependencyResolver.create(finder=finder, allow_prereleases=self.pipenv.allow_prereleases)
    #     pkg_dict = {}
    #     for pkg in self.dev_packages.requirements + self.packages.requirements:
    #         pkg_dict[pkg.name] = pkg
    #     resolver.resolve(list(pkg_dict.values()))
    #     return resolver

    @property
    def dev_packages(self, as_requirements=True):
        if as_requirements:
            return self.dev_requirements
        return self.dev_packages

    @property
    def packages(self, as_requirements=True):
        if as_requirements:
            return self.requirements
        return self.packages
