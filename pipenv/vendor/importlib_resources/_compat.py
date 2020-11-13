from __future__ import absolute_import
import sys

# flake8: noqa

if sys.version_info > (3,5):
    from pathlib import Path, PurePath
else:
    from pathlib2 import Path, PurePath                         # type: ignore


if sys.version_info > (3,):
    from contextlib import suppress
else:
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
    NotADirectoryError = NotADirectoryError                       # type: ignore
except NameError:
    NotADirectoryError = OSError                                 # type: ignore


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


__metaclass__ = type


class PackageSpec:
    def __init__(self, **kwargs):
        vars(self).update(kwargs)


class TraversableResourcesAdapter:
    def __init__(self, spec):
        self.spec = spec
        self.loader = LoaderAdapter(spec)

    def __getattr__(self, name):
        return getattr(self.spec, name)


class LoaderAdapter:
    """
    Adapt loaders to provide TraversableResources and other
    compatibility.
    """
    def __init__(self, spec):
        self.spec = spec

    @property
    def path(self):
        # Python < 3
        return self.spec.origin

    def get_resource_reader(self, name):
        # Python < 3.9
        from . import readers

        def _zip_reader(spec):
            with suppress(AttributeError):
                return readers.ZipReader(spec.loader, spec.name)

        def _namespace_reader(spec):
            with suppress(AttributeError, ValueError):
                return readers.NamespaceReader(spec.submodule_search_locations)

        def _available_reader(spec):
            with suppress(AttributeError):
                return spec.loader.get_resource_reader(spec.name)

        def _native_reader(spec):
            reader = _available_reader(spec)
            return reader if hasattr(reader, 'files') else None

        return (
            # native reader if it supplies 'files'
            _native_reader(self.spec) or
            # local ZipReader if a zip module
            _zip_reader(self.spec) or
            # local NamespaceReader if a namespace module
            _namespace_reader(self.spec) or
            # local FileReader
            readers.FileReader(self)
            )


def package_spec(package):
    """
    Construct a minimal package spec suitable for
    matching the interfaces this library relies upon
    in later Python versions.
    """
    spec = getattr(package, '__spec__', None) or \
        PackageSpec(
            origin=package.__file__,
            loader=getattr(package, '__loader__', None),
            name=package.__name__,
            submodule_search_locations=getattr(package, '__path__', None),
        )
    return TraversableResourcesAdapter(spec)
