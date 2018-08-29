# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import abc
import operator

from itertools import chain

import six

from ..utils import KNOWN_EXTS, unnest
from .path import SystemPath
from .python import PythonVersion
from .windows import WindowsFinder


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
