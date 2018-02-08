import os

from pip._vendor.packaging.version import parse as parse_version
from pipenv.utils import python_version, system_which

from .base import match_version


def iter_python_names(release):
    names = [
        'python',
        'python{0}'.format(*release)
    ]
    if len(release) > 1:
        names.extend([
            'python{0}{1}'.format(*release),
            'python{0}.{1}'.format(*release),
            'python{0}.{1}m'.format(*release),
        ])
    for name in reversed(names):
        for ext in os.environ.get('PATHEXT', '').split(';'):
            if ext:
                yield '{stem}.{ext}'.format(stem=name, ext=ext)
            else:
                yield name


def find_python(version):
    for exe_name in iter_python_names(version._key[1]):
        full_path = system_which(exe_name)
        exe_ver_s = python_version(full_path)
        if exe_ver_s and match_version(version, parse_version(exe_ver_s)):
            return full_path
