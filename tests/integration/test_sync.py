import pytest

from pipenv.utils.shell import temp_environ


@pytest.mark.lock
@pytest.mark.sync
def test_sync_error_without_lockfile(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[packages]
            """.strip()
            )

        c = p.pipenv("sync")
        assert c.returncode != 0
        assert "Pipfile.lock not found!" in c.stderr


@pytest.mark.sync
@pytest.mark.lock
def test_mirror_lock_sync(pipenv_instance_private_pypi):
    with temp_environ(), pipenv_instance_private_pypi() as p:
        mirror_url = p.index_url
        assert "pypi.org" not in mirror_url
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[[source]]
name = "pypi"
url = "https://pypi.org/simple"
verify_ssl = true

[packages]
six = "==1.12.0"
            """.strip()
            )
        c = p.pipenv(f"lock --pypi-mirror {mirror_url}")
        assert c.returncode == 0
        c = p.pipenv(f"sync --pypi-mirror {mirror_url}")
        assert c.returncode == 0


@pytest.mark.sync
@pytest.mark.lock
def test_sync_should_not_lock(pipenv_instance_pypi):
    """Sync should not touch the lock file, even if Pipfile is changed."""
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[packages]
            """.strip()
            )

        # Perform initial lock.
        c = p.pipenv("lock")
        assert c.returncode == 0
        lockfile_content = p.lockfile
        assert lockfile_content

        # Make sure sync does not trigger lockfile update.
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[packages]
six = "*"
            """.strip()
            )
        c = p.pipenv("sync")
        assert c.returncode == 0
        assert lockfile_content == p.lockfile
