import os
from pathlib import Path

import pytest


@pytest.mark.basic
@pytest.mark.install
def test_install_github_vcs(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install git+https://github.com/reagento/adaptix.git@2.16")
        assert not c.returncode
        assert "dataclass-factory" in p.pipfile["packages"]


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.parametrize("use_credentials", [True, False])
def test_install_github_vcs_with_credentials(pipenv_instance_pypi, use_credentials):
    with pipenv_instance_pypi() as p:
        # Set environment variables
        os.environ['GIT_REPO'] = 'github.com/reagento/adaptix.git'
        if use_credentials:
            os.environ['GIT_USERNAME'] = 'git'  # Use 'git' as a dummy username
            os.environ['GIT_PASSWORD'] = ''  # Empty password for public repos
            url = "git+https://${GIT_USERNAME}:${GIT_PASSWORD}@${GIT_REPO}@2.16"
        else:
            url = "git+https://${GIT_REPO}@2.16"
        if os.name == 'nt':
            c = p.pipenv(f"install {url} -v")
        else:
            c = p.pipenv(f"install '{url}' -v")
        assert c.returncode == 0, f"Install failed with error: {c.stderr}"

        assert "dataclass-factory" in p.pipfile["packages"]

        # Check if the URL in the lockfile still contains the environment variables
        lockfile_content = p.lockfile
        assert "${GIT_REPO}" in lockfile_content['default']['dataclass-factory']['git']
        if use_credentials:
            assert "${GIT_USERNAME}" in lockfile_content['default']['dataclass-factory']['git']
            assert "${GIT_PASSWORD}" in lockfile_content['default']['dataclass-factory']['git']

        # Verify that the package is installed and usable
        c = p.pipenv("run python -c \"import dataclass_factory\"")
        assert c.returncode == 0, f"Failed to import library: {c.stderr}"


@pytest.mark.vcs
@pytest.mark.urls
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_vcs_ref_by_commit_hash(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install -e git+https://github.com/benjaminp/six.git@5efb522b0647f7467248273ec1b893d06b984a59#egg=six")
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]
        assert (
            p.lockfile["default"]["six"]["ref"]
            == "5efb522b0647f7467248273ec1b893d06b984a59"
        )
        pipfile = Path(p.pipfile_path)
        new_content = pipfile.read_text().replace("5efb522b0647f7467248273ec1b893d06b984a59", "15e31431af97e5e64b80af0a3f598d382bcdd49a")
        pipfile.write_text(new_content)
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert (
            p.lockfile["default"]["six"]["ref"]
            == "15e31431af97e5e64b80af0a3f598d382bcdd49a"
        )
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]
