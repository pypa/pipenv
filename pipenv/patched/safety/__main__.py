"""Allow safety to be executable through `python -m safety`."""
from __future__ import absolute_import

import os
import sys
import sysconfig


PATCHED_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPENV_DIR = os.path.dirname(PATCHED_DIR)
VENDORED_DIR = os.path.join("PIPENV_DIR", "vendor")


def get_site_packages():
    prefixes = {sys.prefix, sysconfig.get_config_var('prefix')}
    try:
        prefixes.add(sys.real_prefix)
    except AttributeError:
        pass
    form = sysconfig.get_path('purelib', expand=False)
    py_version_short = '{0[0]}.{0[1]}'.format(sys.version_info)
    return {
        form.format(base=prefix, py_version_short=py_version_short)
        for prefix in prefixes
    }


def insert_before_site_packages(*paths):
    site_packages = get_site_packages()
    index = None
    for i, path in enumerate(sys.path):
        if path in site_packages:
            index = i
            break
    if index is None:
        sys.path += list(paths)
    else:
        sys.path = sys.path[:index] + list(paths) + sys.path[index:]


def insert_pipenv_dirs():
    insert_before_site_packages(os.path.dirname(PIPENV_DIR), PATCHED_DIR, VENDORED_DIR)


if __name__ == "__main__":  # pragma: no cover
    insert_pipenv_dirs()
    from pipenv.patched.safety.cli import cli
    cli(prog_name="safety")
