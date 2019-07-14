# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import os
import shutil

import pytest

from pipenv.utils import temp_environ


@pytest.mark.run
@pytest.mark.uninstall
@pytest.mark.install
def test_uninstall_requests(PipenvInstance):
    # Uninstalling requests can fail even when uninstall Django below
    # succeeds, if requests was de-vendored.
    # See https://github.com/pypa/pipenv/issues/3644 for problems
    # caused by devendoring
    with PipenvInstance() as p:
        c = p.pipenv("install requests")
        assert c.return_code == 0
        assert "requests" in p.pipfile["packages"]

        c = p.pipenv("run python -m requests.help")
        assert c.return_code == 0

        c = p.pipenv("uninstall requests")
        assert c.return_code == 0
        assert "requests" not in p.pipfile["dev-packages"]

        c = p.pipenv("run python -m requests.help")
        assert c.return_code > 0


def test_uninstall_django(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv("install Django==1.11.13")
        assert c.return_code == 0
        assert "django" in p.pipfile["packages"]
        assert "django" in p.lockfile["default"]
        assert "pytz" in p.lockfile["default"]

        c = p.pipenv("run python -m django --version")
        assert c.return_code == 0

        c = p.pipenv("uninstall Django")
        assert c.return_code == 0
        assert "django" not in p.pipfile["dev-packages"]
        assert "django" not in p.lockfile["develop"]
        assert p.lockfile["develop"] == {}

        c = p.pipenv("run python -m django --version")
        assert c.return_code > 0


@pytest.mark.run
@pytest.mark.uninstall
@pytest.mark.install
def test_mirror_uninstall(PipenvInstance):
    with temp_environ(), PipenvInstance(chdir=True) as p:

        mirror_url = os.environ.pop(
            "PIPENV_TEST_INDEX", "https://pypi.python.org/simple"
        )
        assert "pypi.org" not in mirror_url

        c = p.pipenv("install Django==1.11.13 --pypi-mirror {0}".format(mirror_url))
        assert c.return_code == 0
        assert "django" in p.pipfile["packages"]
        assert "django" in p.lockfile["default"]
        assert "pytz" in p.lockfile["default"]
        # Ensure the --pypi-mirror parameter hasn't altered the Pipfile or Pipfile.lock sources
        assert len(p.pipfile["source"]) == 1
        assert len(p.lockfile["_meta"]["sources"]) == 1
        assert "https://pypi.org/simple" == p.pipfile["source"][0]["url"]
        assert "https://pypi.org/simple" == p.lockfile["_meta"]["sources"][0]["url"]

        c = p.pipenv("run python -m django --version")
        assert c.return_code == 0

        c = p.pipenv("uninstall Django --pypi-mirror {0}".format(mirror_url))
        assert c.return_code == 0
        assert "django" not in p.pipfile["dev-packages"]
        assert "django" not in p.lockfile["develop"]
        assert p.lockfile["develop"] == {}
        # Ensure the --pypi-mirror parameter hasn't altered the Pipfile or Pipfile.lock sources
        assert len(p.pipfile["source"]) == 1
        assert len(p.lockfile["_meta"]["sources"]) == 1
        assert "https://pypi.org/simple" == p.pipfile["source"][0]["url"]
        assert "https://pypi.org/simple" == p.lockfile["_meta"]["sources"][0]["url"]

        c = p.pipenv("run python -m django --version")
        assert c.return_code > 0


@pytest.mark.files
@pytest.mark.uninstall
@pytest.mark.install
def test_uninstall_all_local_files(PipenvInstance, testsroot):
    file_name = "tablib-0.12.1.tar.gz"
    # Not sure where travis/appveyor run tests from
    source_path = os.path.abspath(os.path.join(testsroot, "pypi", "tablib", file_name))

    with PipenvInstance(chdir=True) as p:
        shutil.copy(source_path, os.path.join(p.path, file_name))
        os.mkdir(os.path.join(p.path, "tablib"))
        c = p.pipenv("install {}".format(file_name))
        assert c.return_code == 0
        c = p.pipenv("uninstall --all")
        assert c.return_code == 0
        assert "tablib" in c.out
        # Uninstall --all is not supposed to remove things from the pipfile
        # Note that it didn't before, but that instead local filenames showed as hashes
        assert "tablib" in p.pipfile["packages"]


@pytest.mark.run
@pytest.mark.uninstall
@pytest.mark.install
def test_uninstall_all_dev(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv("install --dev Django==1.11.13 six")
        assert c.return_code == 0

        c = p.pipenv("install tablib")
        assert c.return_code == 0

        assert "tablib" in p.pipfile["packages"]
        assert "django" in p.pipfile["dev-packages"]
        assert "six" in p.pipfile["dev-packages"]
        assert "tablib" in p.lockfile["default"]
        assert "django" in p.lockfile["develop"]
        assert "six" in p.lockfile["develop"]

        c = p.pipenv('run python -c "import django"')
        assert c.return_code == 0

        c = p.pipenv("uninstall --all-dev")
        assert c.return_code == 0
        assert p.pipfile["dev-packages"] == {}
        assert "django" not in p.lockfile["develop"]
        assert "six" not in p.lockfile["develop"]
        assert "tablib" in p.pipfile["packages"]
        assert "tablib" in p.lockfile["default"]

        c = p.pipenv('run python -c "import django"')
        assert c.return_code > 0

        c = p.pipenv('run python -c "import tablib"')
        assert c.return_code == 0


@pytest.mark.uninstall
@pytest.mark.run
def test_normalize_name_uninstall(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
# Pre comment
[packages]
Requests = "*"
python_DateUtil = "*"   # Inline comment
"""
            f.write(contents)

        c = p.pipenv("install")
        assert c.return_code == 0

        c = p.pipenv("uninstall python_dateutil")
        assert "Requests" in p.pipfile["packages"]
        assert "python_DateUtil" not in p.pipfile["packages"]
        with open(p.pipfile_path) as f:
            contents = f.read()
            assert "# Pre comment" in contents
            assert "# Inline comment" in contents
