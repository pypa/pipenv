import os
import sys
import json

os.environ['PIP_PYTHON_PATH'] = sys.executable

for _dir in ('vendor', 'patched', '..'):
    dirpath = os.path.sep.join([os.path.dirname(__file__), _dir])
    sys.path.insert(0, dirpath)

import pipenv.utils
import pipenv.core
from docopt import docopt


def which(*args, **kwargs):
    return sys.executable

def resolve(packages, pre, sources, verbose, clear):
    return pipenv.utils.resolve_deps(packages, which, project=project, pre=pre, sources=sources, clear=clear, verbose=verbose)

if __name__ == '__main__':

    is_verbose = '--verbose' in sys.argv
    do_pre = '--pre' in sys.argv
    do_clear = '--clear' in sys.argv
    if 'PIPENV_PACKAGES' in os.environ:
        packages = os.environ['PIPENV_PACKAGES'].strip().split('\n')
    else:
        packages = sys.argv[1:]

        for i, package in enumerate(packages):
            if package.startswith('--'):
                del packages[i]

    project = pipenv.core.project

    results = resolve(packages, pre=do_pre, sources=project.sources, verbose=is_verbose, clear=do_clear)


    print('RESULTS:')

    if results:
        print(json.dumps(results))
    else:
        print(json.dumps([]))
