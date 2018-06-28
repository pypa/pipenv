import os

from pipenv.utils import temp_environ

import pytest


@pytest.mark.sync
def test_sync_error_without_lockfile(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
            """.strip())

        c = p.pipenv('sync')
        assert c.return_code != 0
        assert 'Pipfile.lock is missing!' in c.err


@pytest.mark.sync
@pytest.mark.lock
def test_mirror_lock_sync(PipenvInstance, pypi):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        mirror_url = os.environ.pop('PIPENV_TEST_INDEX', "https://pypi.kennethreitz.org/simple")
        assert 'pypi.org' not in mirror_url
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
six = "*"
            """.strip())
        c = p.pipenv('lock --pypi-mirror {0}'.format(mirror_url))
        assert c.return_code == 0
        c = p.pipenv('sync --pypi-mirror {0}'.format(mirror_url))
        assert c.return_code == 0


@pytest.mark.sync
@pytest.mark.lock
def test_sync_should_not_lock(PipenvInstance, pypi):
    """Sync should not touch the lock file, even if Pipfile is changed.
    """
    with PipenvInstance(pypi=pypi) as p:
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
