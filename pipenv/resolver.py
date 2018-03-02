"""Pipenv Resolveer.

Usage:
  resolver.py <packages>... [--verbose] [--pre] [--clear]
  resolver.py (-h | --help)
  resolver.py --version

Options:
  -h --help     Show this screen.
  --version     Show version.
  --clear       Clear the cache.
  --verbose     Display debug information to stderr.
  --pre         Include pre-releases.
"""

import os
import sys
import json

for _dir in ('vendor', 'patched', '..'):
    dirpath = os.path.sep.join([os.path.dirname(__file__), _dir])
    sys.path.insert(0, dirpath)

import pipenv.project
import pipenv.core
from pipenv.utils import *

from docopt import docopt
args = docopt(__doc__)

is_verbose = args['--verbose']
do_pre = args['--pre']
do_clear = args['--clear']
packages = args['<packages>']

project = pipenv.core.project

os.environ['PIP_PYTHON_PATH'] = sys.executable

def which(*args, **kwargs):
    return sys.executable

def resolve(packages, pre=do_pre, sources=project.sources, verbose=is_verbose, clear=do_clear):
    return pipenv.utils.resolve_deps(packages, which, project=project, pre=pre, sources=sources, clear=clear, verbose=verbose)

if __name__ == '__main__':
    results = resolve(packages)
    print('XYZZY')
    if results:
        print(json.dumps(results))
    else:
        print(json.dumps([]))
