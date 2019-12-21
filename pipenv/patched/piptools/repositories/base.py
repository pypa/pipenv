# coding: utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

from abc import ABCMeta, abstractmethod
from contextlib import contextmanager

from six import add_metaclass


@add_metaclass(ABCMeta)
class BaseRepository(object):
    def clear_caches(self):
        """Should clear any caches used by the implementation."""

    def freshen_build_caches(self):
        """Should start with fresh build/source caches."""

    @abstractmethod
    def find_best_match(self, ireq):
        """
        Return a Version object that indicates the best match for the given
        InstallRequirement according to the repository.
        """

    @abstractmethod
    def get_dependencies(self, ireq):
        """
        Given a pinned, URL, or editable InstallRequirement, returns a set of
        dependencies (also InstallRequirements, but not necessarily pinned).
        They indicate the secondary dependencies for the given requirement.
        """

    @abstractmethod
    def get_hashes(self, ireq):
        """
        Given a pinned InstallRequire, returns a set of hashes that represent
        all of the files for a given requirement. It is not acceptable for an
        editable or unpinned requirement to be passed to this function.
        """

    @abstractmethod
    @contextmanager
    def allow_all_wheels(self):
        """
        Monkey patches pip.Wheel to allow wheels from all platforms and Python versions.
        """
