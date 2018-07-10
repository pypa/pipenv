# -*- coding=utf-8 -*-
from __future__ import print_function, absolute_import
import abc
import operator
import six
from ..utils import KNOWN_EXTS


@six.add_metaclass(abc.ABCMeta)
class BaseFinder(object):
    def get_versions(self):
        """Return the available versions from the finder"""
        raise NotImplementedError

    @classmethod
    def create(cls):
        raise NotImplementedError

    @property
    def version_paths(self):
        return self.versions.values()

    @property
    def expanded_paths(self):
        return (p.paths.values() for p in self.version_paths)


class BasePath(object):
    def which(self, name):
        """Search in this path for an executable.

        :param executable: The name of an executable to search for.
        :type executable: str
        :returns: :class:`~pythonfinder.models.PathEntry` instance.
        """

        valid_names = [name] + [
            "{0}.{1}".format(name, ext).lower() if ext else "{0}".format(name).lower()
            for ext in KNOWN_EXTS
        ]
        children = self.children
        found = next((children[(self.path / child).as_posix()] for child in valid_names if (self.path / child).as_posix() in children), None)
        return found

    def find_python_version(self, major, minor=None, patch=None, pre=None, dev=None):
        """Search or self for the specified Python version and return the first match.

        :param major: Major version number.
        :type major: int
        :param minor: Minor python version, defaults to None
        :param minor: int, optional
        :param patch: Patch python version, defaults to None
        :param patch: int, optional
        :returns: A :class:`~pythonfinder.models.PathEntry` instance matching the version requested.
        """

        version_matcher = operator.methodcaller(
            "matches", major, minor=minor, patch=patch, pre=pre, dev=dev
        )
        is_py = operator.attrgetter("is_python")
        py_version = operator.attrgetter("as_python")
        if not self.is_dir:
            if self.is_python and self.as_python.matches(major, minor=minor, patch=patch, pre=pre, dev=dev):
                return self
            return
        finder = ((child, child.as_python) for child in self.children.values() if child.is_python and child.as_python)
        py_filter = filter(
            None, filter(lambda child: version_matcher(child[1]), finder)
        )
        version_sort = operator.attrgetter("version")
        return next(
            (c[0] for c in sorted(py_filter, key=lambda child: child[1].version, reverse=True)), None
        )


from .path import SystemPath
from .windows import WindowsFinder
from .python import PythonVersion
