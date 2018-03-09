import os
import crayons
import pipenv

from pprint import pprint
from .__version__ import __version__
from .core import project
from .pep508checker import lookup

def main():
    print('Pipenv version: {0!r}'.format(__version__))
    print('Pipenv location: {0!r}'.format(os.path.dirname(pipenv.__file__)))
    print()
    print('System environment variables:')
    print()
    print('   {0!r}'.format(list(os.environ.keys())))
    print()
    print()
    print()

    print(u'Pipenv–specific environment variables:')
    print()
    for key in os.environ:
        if key.startswith('PIPENV'):
            print(' - {0!r}: {1!r}'.format(key, os.environ[key]))

    print()
    print(u'Debug–specific environment variables:')
    print()
    for key in ('PATH', 'SHELL', 'EDITOR', 'LANG', 'PWD', 'VIRTUAL_ENV'):
        if key in os.environ:
            print('  - {0!r}: {1!r}'.format(key, os.environ[key]))

    print()
    print()
    print('---------------------------')
    print()

    if project.pipfile_exists:
        print(u'Contents of Pipfile ({0!r}):'.format(project.pipfile_location))
        print()
        print('```toml')
        with open(project.pipfile_location, 'r') as f:
            print(f.read())
        print('```')
        print()

    if project.lockfile_exists:
        print()
        print(u'Contents of Pipfile.lock ({0!r}):'.format(project.lockfile_location))
        print()
        print('```json')
        with open(project.lockfile_location, 'r') as f:
            print(f.read())
        print('```')

if __name__ == '__main__':
    main()
