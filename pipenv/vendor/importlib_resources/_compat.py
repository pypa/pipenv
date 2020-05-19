from __future__ import absolute_import

# flake8: noqa

try:
    from pathlib import Path, PurePath
except ImportError:
    from pathlib2 import Path, PurePath                         # type: ignore


try:
    from contextlib import suppress
except ImportError:
    from contextlib2 import suppress                         # type: ignore


try:
    from functools import singledispatch
except ImportError:
    from singledispatch import singledispatch                   # type: ignore


try:
    from abc import ABC                                         # type: ignore
except ImportError:
    from abc import ABCMeta

    class ABC(object):                                          # type: ignore
        __metaclass__ = ABCMeta


try:
    FileNotFoundError = FileNotFoundError                       # type: ignore
except NameError:
    FileNotFoundError = OSError                                 # type: ignore


try:
    from importlib import metadata
except ImportError:
    import importlib_metadata as metadata  # type: ignore


try:
    from zipfile import Path as ZipPath  # type: ignore
except ImportError:
    from zipp import Path as ZipPath  # type: ignore


try:
    from typing import runtime_checkable  # type: ignore
except ImportError:
    def runtime_checkable(cls):  # type: ignore
        return cls


try:
    from typing import Protocol  # type: ignore
except ImportError:
    Protocol = ABC  # type: ignore


class PackageSpec(object):
	def __init__(self, **kwargs):
		vars(self).update(kwargs)


def package_spec(package):
	return getattr(package, '__spec__', None) or \
		PackageSpec(
			origin=package.__file__,
			loader=getattr(package, '__loader__', None),
		)
