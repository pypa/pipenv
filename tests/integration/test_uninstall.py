import os
import shutil

import pytest

from pipenv.utils.shell import temp_environ


@pytest.mark.uninstall
@pytest.mark.install
def test_uninstall_requests(pipenv_instance_private_pypi):
    # Uninstalling requests can fail even when uninstall Django below
    # succeeds, if requests was de-vendored.
    # See https://github.com/pypa/pipenv/issues/3644 for problems
    # caused by devendoring
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install requests")
        assert c.returncode == 0
        assert "requests" in p.pipfile["packages"]

        c = p.pipenv("run python -m requests.help")
        assert c.returncode == 0

        c = p.pipenv("uninstall requests")
        assert c.returncode == 0
        assert "requests" not in p.pipfile["dev-packages"]

        c = p.pipenv("run python -m requests.help")
        assert c.returncode > 0


@pytest.mark.uninstall
def test_uninstall_django(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install Django")
        assert c.returncode == 0
        assert "django" in p.pipfile["packages"]
        assert "django" in p.lockfile["default"]
        assert "pytz" in p.lockfile["default"]

        c = p.pipenv("run python -m django --version")
        assert c.returncode == 0

        c = p.pipenv("uninstall Django")
        assert c.returncode == 0
        assert "django" not in p.pipfile["dev-packages"]
        assert "django" not in p.lockfile["develop"]
        assert p.lockfile["develop"] == {}

        c = p.pipenv("run python -m django --version")
        assert c.returncode > 0


@pytest.mark.install
@pytest.mark.uninstall
def test_mirror_uninstall(pipenv_instance_private_pypi):
    with temp_environ(), pipenv_instance_private_pypi(chdir=True) as p:

        mirror_url = os.environ.pop(
            "PIPENV_TEST_INDEX", "https://pypi.python.org/simple"
        )
        assert "pypi.org" not in mirror_url

        c = p.pipenv(f"install Django --pypi-mirror {mirror_url}")
        assert c.returncode == 0
        assert "django" in p.pipfile["packages"]
        assert "django" in p.lockfile["default"]
        assert "pytz" in p.lockfile["default"]
        # Ensure the --pypi-mirror parameter hasn't altered the Pipfile or Pipfile.lock sources
        assert len(p.pipfile["source"]) == 1
        assert len(p.lockfile["_meta"]["sources"]) == 1
        assert "https://pypi.org/simple" == p.pipfile["source"][0]["url"]
        assert "https://pypi.org/simple" == p.lockfile["_meta"]["sources"][0]["url"]

        c = p.pipenv("run python -m django --version")
        assert c.returncode == 0

        c = p.pipenv(f"uninstall Django --pypi-mirror {mirror_url}")
        assert c.returncode == 0
        assert "django" not in p.pipfile["dev-packages"]
        assert "django" not in p.lockfile["develop"]
        assert p.lockfile["develop"] == {}
        # Ensure the --pypi-mirror parameter hasn't altered the Pipfile or Pipfile.lock sources
        assert len(p.pipfile["source"]) == 1
        assert len(p.lockfile["_meta"]["sources"]) == 1
        assert "https://pypi.org/simple" == p.pipfile["source"][0]["url"]
        assert "https://pypi.org/simple" == p.lockfile["_meta"]["sources"][0]["url"]

        c = p.pipenv("run python -m django --version")
        assert c.returncode > 0


@pytest.mark.files
@pytest.mark.install
@pytest.mark.uninstall
def test_uninstall_all_local_files(pipenv_instance_private_pypi, testsroot):
    file_name = "tablib-0.12.1.tar.gz"
    # Not sure where travis/appveyor run tests from
    source_path = os.path.abspath(os.path.join(testsroot, "pypi", "tablib", file_name))

    with pipenv_instance_private_pypi(chdir=True) as p:
        shutil.copy(source_path, os.path.join(p.path, file_name))
        os.mkdir(os.path.join(p.path, "tablib"))
        c = p.pipenv(f"install {file_name}")
        assert c.returncode == 0
        c = p.pipenv("uninstall --all")
        assert c.returncode == 0
        assert "tablib" in c.stdout
        # Uninstall --all is not supposed to remove things from the pipfile
        # Note that it didn't before, but that instead local filenames showed as hashes
        assert "tablib" in p.pipfile["packages"]


@pytest.mark.install
@pytest.mark.uninstall
def test_uninstall_all_dev(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install --dev Django==1.11.13 six")
        assert c.returncode == 0

        c = p.pipenv("install tablib")
        assert c.returncode == 0

        assert "tablib" in p.pipfile["packages"]
        assert "django" in p.pipfile["dev-packages"]
        assert "six" in p.pipfile["dev-packages"]
        assert "tablib" in p.lockfile["default"]
        assert "django" in p.lockfile["develop"]
        assert "six" in p.lockfile["develop"]

        c = p.pipenv('run python -c "import django"')
        assert c.returncode == 0

        c = p.pipenv("uninstall --all-dev")
        assert c.returncode == 0
        assert p.pipfile["dev-packages"] == {}
        assert "django" not in p.lockfile["develop"]
        assert "six" not in p.lockfile["develop"]
        assert "tablib" in p.pipfile["packages"]
        assert "tablib" in p.lockfile["default"]

        c = p.pipenv('run python -c "import django"')
        assert c.returncode > 0

        c = p.pipenv('run python -c "import tablib"')
        assert c.returncode == 0


@pytest.mark.uninstall
def test_normalize_name_uninstall(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
# Pre comment
[packages]
Requests = "*"
python_DateUtil = "*"
"""
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0

        c = p.pipenv("uninstall python_dateutil")
        assert "Requests" in p.pipfile["packages"]
        assert "python_DateUtil" not in p.pipfile["packages"]
        with open(p.pipfile_path) as f:
            contents = f.read()
            assert "# Pre comment" in contents


@pytest.mark.install
@pytest.mark.uninstall
def test_uninstall_all_dev_with_shared_dependencies(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install pytest==4.6.11")
        assert c.returncode == 0

        c = p.pipenv("install --dev six")
        assert c.returncode == 0

        c = p.pipenv("uninstall --all-dev")
        assert c.returncode == 0

        assert "six" in p.lockfile["develop"]


@pytest.mark.uninstall
def test_uninstall_missing_parameters(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install dataclasses-json")
        assert c.returncode == 0

        c = p.pipenv("uninstall")
        assert c.returncode != 0
        assert "No package provided!" in c.stderr
