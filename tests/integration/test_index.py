import os
import shutil

from pipenv.utils import temp_environ

import pytest


@pytest.mark.index
def test_add_new_index(PipenvInstance, pypi):
    with temp_environ(), PipenvInstance(pypi=pypi) as p:
        mirror_url = "https://pypi.python.org/simple2"

        c = p.pipenv('index {0} pypi2'.format(mirror_url))

        assert c.return_code == 0

        assert p.pipfile['source'] == [{
            'url': "{0}/simple".format(pypi.url),
            'verify_ssl': True,
            'name': 'custom'
        }, {
            'url': 'https://pypi.python.org/simple2',
            'verify_ssl': True,
            'name': 'pypi2'
        }]


@pytest.mark.index
def test_add_new_index_without_name(PipenvInstance, pypi):
    with temp_environ(), PipenvInstance(pypi=pypi) as p:
        mirror_url = "https://pypi.python.org/simple2"

        c = p.pipenv('index {0}'.format(mirror_url))

        assert c.return_code == 0
        assert p.pipfile['source'] == [{
            'url': "{0}/simple".format(pypi.url),
            'verify_ssl': True,
            'name': 'custom'
        }, {
            'url': mirror_url,
            'verify_ssl': True,
        }]


@pytest.mark.index
def test_existing_index_name(PipenvInstance, pypi):
    with temp_environ(), PipenvInstance(pypi=pypi) as p:
        c = p.pipenv('index https://pypi.python.org/simple2 custom')

        assert c.return_code == 0

        assert p.pipfile['source'] == [{
            'url': "{0}/simple".format(pypi.url),
            'verify_ssl': True,
            'name': 'custom'
        }]


@pytest.mark.index
def test_existing_index_url(PipenvInstance, pypi):
    with temp_environ(), PipenvInstance(pypi=pypi) as p:
        mirror_url = "{0}/simple".format(pypi.url)
        c = p.pipenv('index {0} pypi3'.format(mirror_url))

        assert c.return_code == 0
        assert p.pipfile['source'] == [{
            'url': mirror_url,
            'verify_ssl': True,
            'name': 'custom'
        }]


@pytest.mark.index
def test_dry_run(PipenvInstance, pypi):
    with temp_environ(), PipenvInstance(pypi=pypi) as p:
        c = p.pipenv('index https://pypi.org/simple2 pypi2 --dry-run')

        assert c.return_code == 0
        assert p.pipfile['source'] == [{
            'url': "{0}/simple".format(pypi.url),
            'verify_ssl': True,
            'name': 'custom'
        }]
