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


@pytest.mark.sync
def test_sync_dry_run(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv('install requests==2.14.0')
        assert c.return_code == 0

        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = "*"
            """.strip())

        c = p.pipenv('lock')
        assert c.return_code == 0
        c = p.pipenv('sync --dry-run')
        assert "Package 'requests' out–of–date" in c.out
        assert "Package 'chardet==3.0.4' is not installed." in c.out
