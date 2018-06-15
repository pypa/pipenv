import os
import shutil

from pipenv.utils import temp_environ

import pytest


@pytest.mark.index
def test_add_new_index(PipenvInstance):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        mirror_url = "https://pypi.python.org/simple2"

        c = p.pipenv('index {0} pypi2'.format(mirror_url))

        assert c.return_code == 0

        assert p.pipfile['source'] == [{
            'url': 'https://pypi.org/simple',
            'verify_ssl': True,
            'name': 'pypi'
        }, {
            'url': 'https://pypi.python.org/simple2',
            'verify_ssl': True,
            'name': 'pypi2'
        }]


@pytest.mark.index
def test_add_new_index_without_name(PipenvInstance):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        mirror_url = "https://pypi.python.org/simple2"

        c = p.pipenv('index {0}'.format(mirror_url))

        assert c.return_code == 0
        assert p.pipfile['source'] == [{
            'url': 'https://pypi.org/simple',
            'verify_ssl': True,
            'name': 'pypi'
        }, {
            'url': mirror_url,
            'verify_ssl': True,
        }]


@pytest.mark.index
def test_existing_index_name(PipenvInstance):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        c = p.pipenv('index https://pypi.python.org/simple2 pypi')

        assert c.return_code == 0

        assert p.pipfile['source'] == [{
            'url': 'https://pypi.org/simple',
            'verify_ssl': True,
            'name': 'pypi'
        }]


@pytest.mark.index
def test_existing_index_url(PipenvInstance):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        c = p.pipenv('index https://pypi.org/simple pypi3')

        assert c.return_code == 0
        assert p.pipfile['source'] == [{
            'url': 'https://pypi.org/simple',
            'verify_ssl': True,
            'name': 'pypi'
        }]


@pytest.mark.index
def test_dry_run(PipenvInstance):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        c = p.pipenv('index https://pypi.org/simple2 pypi2 --dry-run')

        assert c.return_code == 0
        assert p.pipfile['source'] == [{
            'url': 'https://pypi.org/simple',
            'verify_ssl': True,
            'name': 'pypi'
        }]
