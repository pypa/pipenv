import os

import pytest


@pytest.mark.basic
@pytest.mark.install
def test_install_github_vcs(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install git+https://github.com/reagento/adaptix.git@2.16")
        assert not c.returncode
        assert "dataclass-factory" in p.pipfile["packages"]


import os
import pytest


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

        # Use single quotes to prevent shell expansion
        c = p.pipenv(f"install '{url}'")
        assert c.returncode == 0, f"Install failed with error: {c.stderr}"

        assert "dataclass-factory" in p.pipfile["packages"]

        # Check if the URL in the lockfile still contains the environment variables
        lockfile_content = p.lockfile
        assert "${GIT_REPO}" in lockfile_content['default']['dataclass-factory']['git']
        if use_credentials:
            assert "${GIT_USERNAME}" in lockfile_content['default']['dataclass-factory']['git']
            assert "${GIT_PASSWORD}" in lockfile_content['default']['dataclass-factory']['git']

        # Verify that the package is installed and usable
        c = p.pipenv("run python -c 'import dataclass-factory; print(dataclass-factory.__version__)'")
        assert c.returncode == 0, f"Version check failed with error: {c.stderr}"
        assert "2.16" in c.stdout
