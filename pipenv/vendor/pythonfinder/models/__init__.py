# -*- coding=utf-8 -*-
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

        valid_names = [
            "{0}.{1}".format(name, ext).lower() if ext else "{0}".format(name).lower()
            for ext in KNOWN_EXTS
        ]
        finder = filter(operator.attrgetter("is_executable"), self.children.values())
        name_getter = operator.attrgetter("path.name")
        return next(
            (child for child in finder if name_getter(child).lower() in valid_names),
            None,
        )

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
            if self.is_python:
                return self if version_matcher(self.as_python) else None
            return
        finder = (c for c in self.children.values() if is_py(c) and py_version(c))
        py_filter = filter(
            None, filter(lambda c: version_matcher(py_version(c)), finder)
        )
        version_sort = operator.attrgetter("py_version.version")
        return next(
            (c for c in sorted(py_filter, key=version_sort, reverse=True)), None
        )


from .path import SystemPath
from .windows import WindowsFinder
from .python import PythonVersion
