import os

from pipenv.utils import temp_environ
from pipenv._compat import TemporaryDirectory, Path
from pipenv.vendor import delegator
from pipenv.project import Project

import pytest

from flaky import flaky


@pytest.mark.install
@pytest.mark.setup
@pytest.mark.skip(reason="this doesn't work on travis")
def test_basic_setup(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        with PipenvInstance(pipfile=False) as p:
            c = p.pipenv("install requests")
            assert c.return_code == 0

            assert "requests" in p.pipfile["packages"]
            assert "requests" in p.lockfile["default"]
            assert "chardet" in p.lockfile["default"]
            assert "idna" in p.lockfile["default"]
            assert "urllib3" in p.lockfile["default"]
            assert "certifi" in p.lockfile["default"]


@pytest.mark.install
@flaky
def test_basic_install(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv("install requests")
        assert c.return_code == 0
        assert "requests" in p.pipfile["packages"]
        assert "requests" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]


@pytest.mark.install
@flaky
def test_mirror_install(PipenvInstance, pypi):
    with temp_environ(), PipenvInstance(chdir=True, pypi=pypi) as p:
        mirror_url = os.environ.pop(
            "PIPENV_TEST_INDEX", "https://pypi.python.org/simple"
        )
        assert "pypi.org" not in mirror_url
        # This should sufficiently demonstrate the mirror functionality
        # since pypi.org is the default when PIPENV_TEST_INDEX is unset.
        c = p.pipenv("install requests --pypi-mirror {0}".format(mirror_url))
        assert c.return_code == 0
        # Ensure the --pypi-mirror parameter hasn't altered the Pipfile or Pipfile.lock sources
        assert len(p.pipfile["source"]) == 1
        assert len(p.lockfile["_meta"]["sources"]) == 1
        assert "https://pypi.org/simple" == p.pipfile["source"][0]["url"]
        assert "https://pypi.org/simple" == p.lockfile["_meta"]["sources"][0]["url"]

        assert "requests" in p.pipfile["packages"]
        assert "requests" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]


@pytest.mark.install
@pytest.mark.needs_internet
@flaky
def test_bad_mirror_install(PipenvInstance, pypi):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        # This demonstrates that the mirror parameter is being used
        os.environ.pop("PIPENV_TEST_INDEX", None)
        c = p.pipenv("install requests --pypi-mirror https://pypi.example.org")
        assert c.return_code != 0


@pytest.mark.complex
@pytest.mark.lock
@pytest.mark.skip(reason="Does not work unless you can explicitly install into py2")
def test_complex_lock(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv("install apscheduler")
        assert c.return_code == 0
        assert "apscheduler" in p.pipfile["packages"]
        assert "funcsigs" in p.lockfile[u"default"]
        assert "futures" in p.lockfile[u"default"]


@pytest.mark.dev
@pytest.mark.run
@flaky
def test_basic_dev_install(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv("install requests --dev")
        assert c.return_code == 0
        assert "requests" in p.pipfile["dev-packages"]
        assert "requests" in p.lockfile["develop"]
        assert "chardet" in p.lockfile["develop"]
        assert "idna" in p.lockfile["develop"]
        assert "urllib3" in p.lockfile["develop"]
        assert "certifi" in p.lockfile["develop"]

        c = p.pipenv("run python -m requests.help")
        assert c.return_code == 0


@pytest.mark.dev
@pytest.mark.install
@flaky
def test_install_without_dev(PipenvInstance, pypi):
    """Ensure that running `pipenv install` doesn't install dev packages"""
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "*"

[dev-packages]
pytz = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.return_code == 0
        assert "six" in p.pipfile["packages"]
        assert "pytz" in p.pipfile["dev-packages"]
        assert "six" in p.lockfile["default"]
        assert "pytz" in p.lockfile["develop"]
        c = p.pipenv('run python -c "import pytz"')
        assert c.return_code != 0
        c = p.pipenv('run python -c "import six"')
        assert c.return_code == 0


@pytest.mark.install
@flaky
def test_install_without_dev_section(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.return_code == 0
        assert "six" in p.pipfile["packages"]
        assert p.pipfile.get("dev-packages", {}) == {}
        assert "six" in p.lockfile["default"]
        assert p.lockfile["develop"] == {}
        c = p.pipenv('run python -c "import six"')
        assert c.return_code == 0


@pytest.mark.extras
@pytest.mark.install
@flaky
def test_extras_install(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        c = p.pipenv("install requests[socks]")
        assert c.return_code == 0
        assert "requests" in p.pipfile["packages"]
        assert "extras" in p.pipfile["packages"]["requests"]

        assert "requests" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "pysocks" in p.lockfile["default"]


@pytest.mark.install
@pytest.mark.pin
@flaky
def test_windows_pinned_pipfile(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
requests = "==2.19.1"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.return_code == 0
        assert "requests" in p.pipfile["packages"]
        assert "requests" in p.lockfile["default"]


@pytest.mark.install
@pytest.mark.resolver
@pytest.mark.backup_resolver
@flaky
def test_backup_resolver(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
"ibm-db-sa-py3" = "==0.3.1-1"
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.return_code == 0
        assert "ibm-db-sa-py3" in p.lockfile["default"]


@pytest.mark.run
@pytest.mark.alt
@flaky
def test_alternative_version_specifier(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
requests = {version = "*"}
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.return_code == 0

        assert "requests" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]

        c = p.pipenv('run python -c "import requests; import idna; import certifi;"')
        assert c.return_code == 0


@pytest.mark.run
@pytest.mark.alt
@flaky
def test_outline_table_specifier(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages.requests]
version = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.return_code == 0

        assert "requests" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]

        c = p.pipenv('run python -c "import requests; import idna; import certifi;"')
        assert c.return_code == 0


@pytest.mark.bad
@pytest.mark.install
def test_bad_packages(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv("install NotAPackage")
        assert c.return_code > 0


@pytest.mark.extras
@pytest.mark.install
@pytest.mark.requirements
@pytest.mark.skip(reason="Not mocking this.")
def test_requirements_to_pipfile(PipenvInstance, pypi):

    with PipenvInstance(pipfile=False, chdir=True, pypi=pypi) as p:

        # Write a requirements file
        with open("requirements.txt", "w") as f:
            f.write("requests[socks]==2.18.1\n")

        c = p.pipenv("install")
        assert c.return_code == 0
        print(c.out)
        print(c.err)
        print(delegator.run("ls -l").out)

        # assert stuff in pipfile
        assert "requests" in p.pipfile["packages"]
        assert "extras" in p.pipfile["packages"]["requests"]

        # assert stuff in lockfile
        assert "requests" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "pysocks" in p.lockfile["default"]


@pytest.mark.install
@pytest.mark.requirements
def test_skip_requirements_when_pipfile(PipenvInstance, pypi):
    """Ensure requirements.txt is NOT imported when

    1. We do `pipenv install [package]`
    2. A Pipfile already exists when we run `pipenv install`.
    """
    with PipenvInstance(chdir=True, pypi=pypi) as p:
        with open("requirements.txt", "w") as f:
            f.write("requests==2.18.1\n")
        c = p.pipenv("install six")
        assert c.return_code == 0
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "*"
tablib = "<0.12"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert "tablib" in p.pipfile["packages"]
        assert "tablib" in p.lockfile["default"]
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]
        assert "requests" not in p.pipfile["packages"]
        assert "requests" not in p.lockfile["default"]


@pytest.mark.cli
@pytest.mark.clean
def test_clean_on_empty_venv(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv("clean")
        assert c.return_code == 0


@pytest.mark.install
def test_install_does_not_extrapolate_environ(PipenvInstance, pypi):
    """Ensure environment variables are not expanded in lock file.
    """
    with temp_environ(), PipenvInstance(pypi=pypi, chdir=True) as p:
        os.environ["PYPI_URL"] = pypi.url

        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[[source]]
url = '${PYPI_URL}/simple'
verify_ssl = true
name = 'mockpi'
            """
            )

        # Ensure simple install does not extrapolate.
        c = p.pipenv("install")
        assert c.return_code == 0
        assert p.pipfile["source"][0]["url"] == "${PYPI_URL}/simple"
        assert p.lockfile["_meta"]["sources"][0]["url"] == "${PYPI_URL}/simple"

        # Ensure package install does not extrapolate.
        c = p.pipenv("install six")
        assert c.return_code == 0
        assert p.pipfile["source"][0]["url"] == "${PYPI_URL}/simple"
        assert p.lockfile["_meta"]["sources"][0]["url"] == "${PYPI_URL}/simple"


@pytest.mark.editable
@pytest.mark.badparameter
@pytest.mark.install
def test_editable_no_args(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv("install -e")
        assert c.return_code != 0
        assert "Error: -e option requires an argument" in c.err


@pytest.mark.install
@pytest.mark.virtualenv
def test_install_venv_project_directory(PipenvInstance, pypi):
    """Test the project functionality during virtualenv creation.
    """
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        with temp_environ(), TemporaryDirectory(
            prefix="pipenv-", suffix="temp_workon_home"
        ) as workon_home:
            os.environ["WORKON_HOME"] = workon_home.name
            if "PIPENV_VENV_IN_PROJECT" in os.environ:
                del os.environ["PIPENV_VENV_IN_PROJECT"]

            c = p.pipenv("install six")
            assert c.return_code == 0

            venv_loc = None
            for line in c.err.splitlines():
                if line.startswith("Virtualenv location:"):
                    venv_loc = Path(line.split(":", 1)[-1].strip())
            assert venv_loc is not None
            assert venv_loc.joinpath(".project").exists()


@pytest.mark.deploy
@pytest.mark.system
def test_system_and_deploy_work(PipenvInstance, pypi):
    with PipenvInstance(chdir=True, pypi=pypi) as p:
        c = p.pipenv("install six requests")
        assert c.return_code == 0
        c = p.pipenv("--rm")
        assert c.return_code == 0
        c = delegator.run("virtualenv .venv")
        assert c.return_code == 0
        c = p.pipenv("install --system --deploy")
        assert c.return_code == 0
        c = p.pipenv("--rm")
        assert c.return_code == 0
        Path(p.pipfile_path).write_text(
            u"""
[packages]
requests
        """.strip()
        )
        c = p.pipenv("install --system")
        assert c.return_code == 0
