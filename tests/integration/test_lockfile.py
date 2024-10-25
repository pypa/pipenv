import json
from collections import defaultdict

import pytest

from pipenv.project import Project
from pipenv.utils import requirements


@pytest.fixture
def pypi_lockfile():
    lockfile = defaultdict(dict)
    lockfile["_meta"] = {
        "sources": [
            {
                "name": "pypi",
                "url": "https://pypi.org/simple",
                "verify_ssl": True,
            }
        ]
    }
    yield lockfile


def test_git_branch_contains_slashes(pipenv_instance_pypi, pypi_lockfile):
    pypi_lockfile["default"]["google-api-python-client"] = {
        "git": "https://github.com/thehesiod/google-api-python-client.git@thehesiod/batch-retries2",
        "markers": "python_version >= '3.7'",
        "ref": "03803c21fc13a345e978f32775b2f2fa23c8e706",
    }

    with pipenv_instance_pypi() as p:
        with open(p.lockfile_path, "w") as f:
            json.dump(pypi_lockfile, f)

        project = Project()
        lockfile = project.load_lockfile(expand_env_vars=False)
        deps = lockfile["default"]
        pip_installable_lines = requirements.requirements_from_lockfile(
            deps, include_hashes=False, include_markers=True
        )
        assert pip_installable_lines == [
            "google-api-python-client @ git+https://github.com/thehesiod/google-api-python-client.git@03803c21fc13a345e978f32775b2f2fa23c8e706"
        ]


def test_git_branch_contains_subdirectory_fragment(pipenv_instance_pypi, pypi_lockfile):
    pypi_lockfile["default"]["pep508_package"] = {
        "git": "https://github.com/techalchemy/test-project.git@master",
        "subdirectory": "parent_folder/pep508-package",
        "ref": "03803c21fc13a345e978f32775b2f2fa23c8e706",
    }

    with pipenv_instance_pypi() as p:
        with open(p.lockfile_path, "w") as f:
            json.dump(pypi_lockfile, f)

        project = Project()
        lockfile = project.load_lockfile(expand_env_vars=False)
        deps = lockfile["default"]
        pip_installable_lines = requirements.requirements_from_lockfile(
            deps, include_hashes=False, include_markers=True
        )
        assert pip_installable_lines == [
            "pep508_package @ git+https://github.com/techalchemy/test-project.git@03803c21fc13a345e978f32775b2f2fa23c8e706#subdirectory=parent_folder/pep508-package"
        ]
