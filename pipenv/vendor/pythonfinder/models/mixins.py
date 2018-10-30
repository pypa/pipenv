# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import abc
import attr
import operator
import six

from ..utils import ensure_path, KNOWN_EXTS, unnest


@attr.s
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
        found = next(
            (
                children[(self.path / child).as_posix()]
                for child in valid_names
                if (self.path / child).as_posix() in children
            ),
            None,
        )
        return found

    def find_all_python_versions(
        self,
        major=None,
        minor=None,
        patch=None,
        pre=None,
        dev=None,
        arch=None,
        name=None,
    ):
        """Search for a specific python version on the path. Return all copies

        :param major: Major python version to search for.
        :type major: int
        :param int minor: Minor python version to search for, defaults to None
        :param int patch: Patch python version to search for, defaults to None
        :param bool pre: Search for prereleases (default None) - prioritize releases if None
        :param bool dev: Search for devreleases (default None) - prioritize releases if None
        :param str arch: Architecture to include, e.g. '64bit', defaults to None
        :param str name: The name of a python version, e.g. ``anaconda3-5.3.0``
        :return: A list of :class:`~pythonfinder.models.PathEntry` instances matching the version requested.
        :rtype: List[:class:`~pythonfinder.models.PathEntry`]
        """

        call_method = (
            "find_all_python_versions" if self.is_dir else "find_python_version"
        )
        sub_finder = operator.methodcaller(
            call_method,
            major=major,
            minor=minor,
            patch=patch,
            pre=pre,
            dev=dev,
            arch=arch,
            name=name,
        )
        if not self.is_dir:
            return sub_finder(self)
        path_filter = filter(None, (sub_finder(p) for p in self.children.values()))
        version_sort = operator.attrgetter("as_python.version_sort")
        return [c for c in sorted(path_filter, key=version_sort, reverse=True)]

    def find_python_version(
        self,
        major=None,
        minor=None,
        patch=None,
        pre=None,
        dev=None,
        arch=None,
        name=None,
    ):
        """Search or self for the specified Python version and return the first match.

        :param major: Major version number.
        :type major: int
        :param int minor: Minor python version to search for, defaults to None
        :param int patch: Patch python version to search for, defaults to None
        :param bool pre: Search for prereleases (default None) - prioritize releases if None
        :param bool dev: Search for devreleases (default None) - prioritize releases if None
        :param str arch: Architecture to include, e.g. '64bit', defaults to None
        :param str name: The name of a python version, e.g. ``anaconda3-5.3.0``
        :returns: A :class:`~pythonfinder.models.PathEntry` instance matching the version requested.
        """

        version_matcher = operator.methodcaller(
            "matches",
            major=major,
            minor=minor,
            patch=patch,
            pre=pre,
            dev=dev,
            arch=arch,
            name=name,
        )
        is_py = operator.attrgetter("is_python")
        py_version = operator.attrgetter("as_python")
        if not self.is_dir:
            if self.is_python and self.as_python and version_matcher(self.py_version):
                return attr.evolve(self)
            return
        finder = (
            (child, child.as_python)
            for child in unnest(self.pythons.values())
            if child.as_python
        )
        py_filter = filter(
            None, filter(lambda child: version_matcher(child[1]), finder)
        )
        version_sort = operator.attrgetter("version_sort")
        return next(
            (
                c[0]
                for c in sorted(
                    py_filter, key=lambda child: child[1].version_sort, reverse=True
                )
            ),
            None,
        )


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
