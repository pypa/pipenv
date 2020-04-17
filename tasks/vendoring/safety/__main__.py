"""Allow safety to be executable through `python -m safety`."""
from __future__ import absolute_import

import os
import sys
import sysconfig

LIBPATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")


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



if __name__ == "__main__":
    insert_before_site_packages(LIBPATH)
    yaml_lib = 'yaml{0}'.format(sys.version_info[0])
    locals()[yaml_lib] = __import__(yaml_lib)
    sys.modules['yaml'] = sys.modules[yaml_lib]
    from safety.cli import cli
    cli(prog_name="safety")
