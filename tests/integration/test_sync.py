# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import json
import os

import pytest

from pipenv.utils import temp_environ


@pytest.mark.lock
@pytest.mark.sync
def test_sync_error_without_lockfile(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
            """.strip())

        c = p.pipenv('sync')
        assert c.return_code != 0
        assert 'Pipfile.lock not found!' in c.err


@pytest.mark.sync
@pytest.mark.lock
def test_mirror_lock_sync(PipenvInstance):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        mirror_url = os.environ.pop('PIPENV_TEST_INDEX', "https://pypi.kennethreitz.org/simple")
        assert 'pypi.org' not in mirror_url
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[[source]]
name = "pypi"
url = "https://pypi.org/simple"
verify_ssl = true

[packages]
six = "*"
            """.strip())
        c = p.pipenv('lock --pypi-mirror {0}'.format(mirror_url))
        assert c.return_code == 0
        c = p.pipenv('sync --pypi-mirror {0}'.format(mirror_url))
        assert c.return_code == 0


@pytest.mark.sync
@pytest.mark.lock
def test_sync_should_not_lock(PipenvInstance):
    """Sync should not touch the lock file, even if Pipfile is changed.
    """
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
            """.strip())

        # Perform initial lock.
        c = p.pipenv('lock')
        assert c.return_code == 0
        lockfile_content = p.lockfile
        assert lockfile_content

        # Make sure sync does not trigger lockfile update.
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
six = "*"
            """.strip())
        c = p.pipenv('sync')
        assert c.return_code == 0
        assert lockfile_content == p.lockfile


@pytest.mark.sync
@pytest.mark.lock
def test_sync_sequential_detect_errors(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = "*"
        """.strip()
            f.write(contents)

        c = p.pipenv('lock')
        assert c.return_code == 0

        # Force hash mismatch when installing `requests`
        lock = p.lockfile
        lock['default']['requests']['hashes'] = ['sha256:' + '0' * 64]
        with open(p.lockfile_path, 'w') as f:
            json.dump(lock, f)

        c = p.pipenv('sync --sequential')
        assert c.return_code != 0


@pytest.mark.sync
@pytest.mark.lock
def test_sync_sequential_verbose(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = "*"
        """.strip()
            f.write(contents)

        c = p.pipenv('lock')
        assert c.return_code == 0

        c = p.pipenv('sync --sequential --verbose')
        for package in p.lockfile['default']:
            assert 'Successfully installed {}'.format(package) in c.out
