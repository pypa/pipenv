# -*- coding: utf-8 -*-
from __future__ import absolute_import
import abc
import attr
import six


@six.add_metaclass(abc.ABCMeta)
class BaseRequirement:
    @classmethod
    def from_line(cls, line):
        """Returns a requirement from a requirements.txt or pip-compatible line"""
        raise NotImplementedError

    @abc.abstractmethod
    def line_part(self):
        """Returns the current requirement as a pip-compatible line"""

    @classmethod
    def from_pipfile(cls, name, pipfile):
        """Returns a requirement from a pipfile entry"""
        raise NotImplementedError

    @abc.abstractmethod
    def pipfile_part(self):
        """Returns the current requirement as a pipfile entry"""

    @classmethod
    def attr_fields(cls):
        return [field.name for field in attr.fields(cls)]
