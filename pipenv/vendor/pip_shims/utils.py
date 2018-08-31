# -*- coding=utf-8 -*-
from functools import wraps
import sys

STRING_TYPES = (str,)
if sys.version_info < (3, 0):
    STRING_TYPES = STRING_TYPES + (unicode,)


def memoize(obj):
    cache = obj.cache = {}

    @wraps(obj)
    def memoizer(*args, **kwargs):
        key = str(args) + str(kwargs)
        if key not in cache:
            cache[key] = obj(*args, **kwargs)
        return cache[key]
    return memoizer


@memoize
def _parse(version):
    if isinstance(version, STRING_TYPES):
        return tuple((int(i) for i in version.split(".")))
    return version


def get_package(module, subimport=None):
    package = None
    if subimport:
        package = subimport
    else:
        module, _, package = module.rpartition(".")
    return module, package
