# -*- coding: utf-8 -*-
from __future__ import unicode_literals, absolute_import

import json
from json import JSONEncoder

from . import filetypes, errors


class Dependency(object):
    """

    """

    def __init__(self, name, specs, line, source="pypi", meta={}, extras=[],
                 line_numbers=None, index_server=None, hashes=(),
                 dependency_type=None, section=None):
        """

        :param name:
        :param specs:
        :param line:
        :param source:
        :param extras:
        :param line_numbers:
        :param index_server:
        :param hashes:
        :param dependency_type:
        """
        self.name = name
        self.key = name.lower().replace("_", "-")
        self.specs = specs
        self.line = line
        self.source = source
        self.meta = meta
        self.line_numbers = line_numbers
        self.index_server = index_server
        self.hashes = hashes
        self.dependency_type = dependency_type
        self.extras = extras
        self.section = section

    def __str__(self):  # pragma: no cover
        """

        :return:
        """
        return "Dependency({name}, {specs}, {line})".format(
            name=self.name,
            specs=self.specs,
            line=self.line
        )

    def serialize(self):
        """

        :return:
        """
        return {
            "name": self.name,
            "specs": self.specs,
            "line": self.line,
            "source": self.source,
            "meta": self.meta,
            "line_numbers": self.line_numbers,
            "index_server": self.index_server,
            "hashes": self.hashes,
            "dependency_type": self.dependency_type,
            "extras": self.extras,
            "section": self.section
        }

    @classmethod
    def deserialize(cls, d):
        """

        :param d:
        :return:
        """
        return cls(**d)

    @property
    def full_name(self):
        """

        :return:
        """
        if self.extras:
            return "{}[{}]".format(self.name, ",".join(self.extras))
        return self.name


class DparseJSONEncoder(JSONEncoder):
    def default(self, o):
        from pipenv.patched.pip._vendor.packaging.specifiers import SpecifierSet

        if isinstance(o, SpecifierSet):
            return str(o)
        if isinstance(o, set):
            return list(o)

        return JSONEncoder.default(self, o)


class DependencyFile(object):
    """

    """

    def __init__(self, content, path=None, sha=None, file_type=None,
                 marker=((), ()), parser=None, resolve=False):
        """

        :param content:
        :param path:
        :param sha:
        :param marker:
        :param file_type:
        :param parser:
        """
        self.content = content
        self.file_type = file_type
        self.path = path
        self.sha = sha
        self.marker = marker

        self.dependencies = []
        self.resolved_files = []
        self.is_valid = False
        self.file_marker, self.line_marker = marker

        if parser:
            self.parser = parser
        else:
            from . import parser as parser_class
            if file_type is not None:
                if file_type == filetypes.requirements_txt:
                    self.parser = parser_class.RequirementsTXTParser
                elif file_type == filetypes.tox_ini:
                    self.parser = parser_class.ToxINIParser
                elif file_type == filetypes.conda_yml:
                    self.parser = parser_class.CondaYMLParser
                elif file_type == filetypes.pipfile:
                    self.parser = parser_class.PipfileParser
                elif file_type == filetypes.pipfile_lock:
                    self.parser = parser_class.PipfileLockParser
                elif file_type == filetypes.setup_cfg:
                    self.parser = parser_class.SetupCfgParser
                elif file_type == filetypes.poetry_lock:
                    self.parser = parser_class.PoetryLockParser

            elif path is not None:
                if path.endswith((".txt", ".in")):
                    self.parser = parser_class.RequirementsTXTParser
                elif path.endswith(".yml"):
                    self.parser = parser_class.CondaYMLParser
                elif path.endswith(".ini"):
                    self.parser = parser_class.ToxINIParser
                elif path.endswith("Pipfile"):
                    self.parser = parser_class.PipfileParser
                elif path.endswith("Pipfile.lock"):
                    self.parser = parser_class.PipfileLockParser
                elif path.endswith("setup.cfg"):
                    self.parser = parser_class.SetupCfgParser
                elif path.endswith(filetypes.poetry_lock):
                    self.parser = parser_class.PoetryLockParser

        if not hasattr(self, "parser"):
            raise errors.UnknownDependencyFileError

        self.parser = self.parser(self, resolve=resolve)

    @property
    def resolved_dependencies(self):
        deps = self.dependencies.copy()

        for d in self.resolved_files:
            if isinstance(d, DependencyFile):
                deps.extend(d.resolved_dependencies)

        return deps

    def serialize(self):
        """

        :return:
        """
        return {
            "file_type": self.file_type,
            "content": self.content,
            "path": self.path,
            "sha": self.sha,
            "dependencies": [dep.serialize() for dep in self.dependencies],
            "resolved_dependencies": [dep.serialize() for dep in
                                      self.resolved_dependencies]
        }

    @classmethod
    def deserialize(cls, d):
        """

        :param d:
        :return:
        """
        dependencies = [Dependency.deserialize(dep) for dep in
                        d.pop("dependencies", [])]
        instance = cls(**d)
        instance.dependencies = dependencies
        return instance

    def json(self):  # pragma: no cover
        """

        :return:
        """
        return json.dumps(self.serialize(), indent=2, cls=DparseJSONEncoder)

    def parse(self):
        """

        :return:
        """
        if self.parser.is_marked_file:
            self.is_valid = False
            return self
        self.parser.parse()

        self.is_valid = len(self.dependencies) > 0 or len(
            self.resolved_files) > 0
        return self
