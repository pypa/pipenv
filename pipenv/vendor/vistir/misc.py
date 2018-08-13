# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

import json
import locale
import os
import subprocess
import sys

from collections import OrderedDict

from .cmdparse import Script
from .compat import Path, partialmethod


__all__ = [
    "shell_escape", "unnest", "dedup", "run", "load_path", "partialclass"
]


def shell_escape(cmd):
    """Escape strings for use in :func:`~subprocess.Popen` and :func:`run`.

    This is a passthrough method for instantiating a :class:`~vistir.cmdparse.Script`
    object which can be used to escape commands to output as a single string.
    """
    cmd = Script.parse(cmd)
    return cmd.cmdify()


def unnest(elem):
    """Flatten an arbitrarily nested iterable

    :param elem: An iterable to flatten
    :type elem: :class:`~collections.Iterable`

    >>> nested_iterable = (1234, (3456, 4398345, (234234)), (2396, (23895750, 9283798, 29384, (289375983275, 293759, 2347, (2098, 7987, 27599)))))
    >>> list(vistir.misc.unnest(nested_iterable))
    [1234, 3456, 4398345, 234234, 2396, 23895750, 9283798, 29384, 289375983275, 293759, 2347, 2098, 7987, 27599]
    """

    if _is_iterable(elem):
        for item in elem:
            if _is_iterable(item):
                for sub_item in unnest(item):
                    yield sub_item
            else:
                yield item
    else:
        raise ValueError("Expecting an iterable, got %r" % elem)


def _is_iterable(elem):
    if getattr(elem, "__iter__", False):
        return True
    return False


def dedup(iterable):
    """Deduplicate an iterable object like iter(set(iterable)) but
    order-reserved.
    """
    return iter(OrderedDict.fromkeys(iterable))


def run(cmd):
    """Use `subprocess.Popen` to get the output of a command and decode it.

    :param list cmd: A list representing the command you want to run.
    :returns: A 2-tuple of (output, error)
    """
    encoding = locale.getdefaultlocale()[1] or "utf-8"
    c = subprocess.Popen(
        cmd, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    out, err = c.communicate()
    return out.decode(encoding).strip(), err.decode(encoding).strip()


def load_path(python):
    """Load the :mod:`sys.path` from the given python executable's environment as json

    :param str python: Path to a valid python executable
    :return: A python representation of the `sys.path` value of the given python executable.
    :rtype: list

    >>> load_path("/home/user/.virtualenvs/requirementslib-5MhGuG3C/bin/python")
    ['', '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python37.zip', '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python3.7', '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python3.7/lib-dynload', '/home/user/.pyenv/versions/3.7.0/lib/python3.7', '/home/user/.virtualenvs/requirementslib-5MhGuG3C/lib/python3.7/site-packages', '/home/user/git/requirementslib/src']
    """

    python = Path(python).as_posix()
    out, err = run([python, "-c", "import json, sys; print(json.dumps(sys.path))"])
    if out:
        return json.loads(out)
    else:
        return []


def partialclass(cls, *args, **kwargs):
    """Returns a partially instantiated class

    :return: A partial class instance
    :rtype: cls

    >>> source = partialclass(Source, url="https://pypi.org/simple")
    >>> source
    <class '__main__.Source'>
    >>> source(name="pypi")
    >>> source.__dict__
    mappingproxy({'__module__': '__main__', '__dict__': <attribute '__dict__' of 'Source' objects>, '__weakref__': <attribute '__weakref__' of 'Source' objects>, '__doc__': None, '__init__': functools.partialmethod(<function Source.__init__ at 0x7f23af429bf8>, , url='https://pypi.org/simple')})
    >>> new_source = source(name="pypi")
    >>> new_source
    <__main__.Source object at 0x7f23af189b38>
    >>> new_source.__dict__
    {'url': 'https://pypi.org/simple', 'verify_ssl': True, 'name': 'pypi'}
    """

    name_attrs = [n for n in (getattr(cls, name, str(cls)) for name in ("__name__", "__qualname__")) if n is not None]
    name_attrs = name_attrs[0]
    type_ = type(
        name_attrs,
        (cls,),
        {
            "__init__": partialmethod(cls.__init__, *args, **kwargs),
        }
    )
    # Swiped from attrs.make_class
    try:
        type_.__module__ = sys._getframe(1).f_globals.get(
            "__name__", "__main__",
        )
    except (AttributeError, ValueError):
        pass
    return type_
