import os
import mock

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from flaky import flaky

from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import temp_environ


@pytest.mark.setup
@pytest.mark.basic
@pytest.mark.install
def test_basic_setup(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with pipenv_instance_private_pypi(pipfile=False) as p:
            c = p.pipenv("install requests")
            assert c.returncode == 0

            assert "requests" in p.pipfile["packages"]
            assert "requests" in p.lockfile["default"]
            assert "chardet" in p.lockfile["default"]
            assert "idna" in p.lockfile["default"]
            assert "urllib3" in p.lockfile["default"]
            assert "certifi" in p.lockfile["default"]


@flaky
@pytest.mark.basic
@pytest.mark.install
def test_basic_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install requests")
        assert c.returncode == 0
        assert "requests" in p.pipfile["packages"]
        assert "requests" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]


@flaky
@pytest.mark.basic
@pytest.mark.install
def test_mirror_install(pipenv_instance_pypi):
    with temp_environ(), pipenv_instance_pypi(chdir=True) as p:
        mirror_url = "https://pypi.python.org/simple"
        assert "pypi.org" not in mirror_url
        # This should sufficiently demonstrate the mirror functionality
        # since pypi.org is the default when PIPENV_TEST_INDEX is unset.
        c = p.pipenv(f"install dataclasses-json --pypi-mirror {mirror_url}")
        assert c.returncode == 0
        # Ensure the --pypi-mirror parameter hasn't altered the Pipfile or Pipfile.lock sources
        assert len(p.pipfile["source"]) == 1
        assert len(p.lockfile["_meta"]["sources"]) == 1
        assert "https://pypi.org/simple" == p.pipfile["source"][0]["url"]
        assert "https://pypi.org/simple" == p.lockfile["_meta"]["sources"][0]["url"]

        assert "dataclasses-json" in p.pipfile["packages"]
        assert "dataclasses-json" in p.lockfile["default"]


@flaky
@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_bad_mirror_install(pipenv_instance_pypi):
    with temp_environ(), pipenv_instance_pypi(chdir=True) as p:
        # This demonstrates that the mirror parameter is being used
        os.environ.pop("PIPENV_TEST_INDEX", None)
        c = p.pipenv("install dataclasses-json --pypi-mirror https://pypi.example.org")
        assert c.returncode != 0


@flaky
@pytest.mark.dev
@pytest.mark.run
def test_basic_dev_install(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install dataclasses-json --dev")
        assert c.returncode == 0
        assert "dataclasses-json" in p.pipfile["dev-packages"]
        assert "dataclasses-json" in p.lockfile["develop"]

        c = p.pipenv("run python -c 'from dataclasses_json import dataclass_json'")
        assert c.returncode == 0


@flaky
@pytest.mark.dev
@pytest.mark.basic
@pytest.mark.install
def test_install_without_dev(pipenv_instance_private_pypi):
    """Ensure that running `pipenv install` doesn't install dev packages"""
    with pipenv_instance_private_pypi(chdir=True) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "*"

[dev-packages]
tablib = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert "tablib" in p.pipfile["dev-packages"]
        assert "six" in p.lockfile["default"]
        assert "tablib" in p.lockfile["develop"]
        c = p.pipenv('run python -c "import tablib"')
        assert c.returncode != 0
        c = p.pipenv('run python -c "import six"')
        assert c.returncode == 0


@flaky
@pytest.mark.basic
@pytest.mark.install
def test_install_without_dev_section(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert p.pipfile.get("dev-packages", {}) == {}
        assert "six" in p.lockfile["default"]
        assert p.lockfile["develop"] == {}
        c = p.pipenv('run python -c "import six"')
        assert c.returncode == 0


@flaky
@pytest.mark.lock
@pytest.mark.extras
@pytest.mark.install
def test_extras_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi(chdir=True) as p:
        c = p.pipenv("install requests[socks]")
        assert c.returncode == 0
        assert "requests" in p.pipfile["packages"]
        assert "extras" in p.pipfile["packages"]["requests"]

        assert "requests" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "pysocks" in p.lockfile["default"]


@flaky
@pytest.mark.pin
@pytest.mark.basic
@pytest.mark.install
def test_pinned_pipfile(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
dataclasses-json = "==0.5.7"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "dataclasses-json" in p.pipfile["packages"]
        assert "dataclasses-json" in p.lockfile["default"]


@flaky
@pytest.mark.basic
@pytest.mark.install
@pytest.mark.resolver
@pytest.mark.backup_resolver
def test_backup_resolver(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
"ibm-db-sa-py3" = "==0.3.1-1"
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0
        assert "ibm-db-sa-py3" in p.lockfile["default"]


@flaky
@pytest.mark.run
@pytest.mark.alt
def test_alternative_version_specifier(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
requests = {version = "*"}
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0

        assert "requests" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]

        c = p.pipenv('run python -c "import requests; import idna; import certifi;"')
        assert c.returncode == 0


@flaky
@pytest.mark.run
@pytest.mark.alt
def test_outline_table_specifier(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages.requests]
version = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0

        assert "requests" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]

        c = p.pipenv('run python -c "import requests; import idna; import certifi;"')
        assert c.returncode == 0


@pytest.mark.bad
@pytest.mark.basic
@pytest.mark.install
def test_bad_packages(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install NotAPackage")
        assert c.returncode > 0


@pytest.mark.lock
@pytest.mark.extras
@pytest.mark.install
@pytest.mark.requirements
def test_requirements_to_pipfile(pipenv_instance_private_pypi):

    with pipenv_instance_private_pypi(pipfile=False, chdir=True) as p:

        # Write a requirements file
        with open("requirements.txt", "w") as f:
            f.write(
                f"-i {os.environ['PIPENV_TEST_INDEX']}\n"
                "requests[socks]==2.19.1\n"
            )

        c = p.pipenv("install")
        assert c.returncode == 0
        os.unlink("requirements.txt")
        print(c.stdout)
        print(c.stderr)
        # assert stuff in pipfile
        assert "requests" in p.pipfile["packages"]
        assert "extras" in p.pipfile["packages"]["requests"]
        assert not any(
            source['url'] == 'https://private.pypi.org/simple'
            for source in p.pipfile['source']
        )
        # assert stuff in lockfile
        assert "requests" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "pysocks" in p.lockfile["default"]


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.requirements
def test_skip_requirements_when_pipfile(pipenv_instance_private_pypi):
    """Ensure requirements.txt is NOT imported when

    1. We do `pipenv install [package]`
    2. A Pipfile already exists when we run `pipenv install`.
    """
    with pipenv_instance_private_pypi(chdir=True) as p:
        with open("requirements.txt", "w") as f:
            f.write("requests==2.18.1\n")
        c = p.pipenv("install six")
        assert c.returncode == 0
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]
        assert "requests" not in p.pipfile["packages"]
        assert "requests" not in p.lockfile["default"]


@pytest.mark.cli
@pytest.mark.clean
def test_clean_on_empty_venv(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("clean")
        assert c.returncode == 0


@pytest.mark.basic
@pytest.mark.install
def test_install_does_not_extrapolate_environ(pipenv_instance_pypi):
    """Ensure environment variables are not expanded in lock file.
    """
    with temp_environ(), pipenv_instance_pypi(chdir=True) as p:
        os.environ["PYPI_URL"] = p.pypi

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
        assert c.returncode == 0
        assert p.pipfile["source"][0]["url"] == "${PYPI_URL}/simple"
        assert p.lockfile["_meta"]["sources"][0]["url"] == "${PYPI_URL}/simple"

        # Ensure package install does not extrapolate.
        c = p.pipenv("install six")
        assert c.returncode == 0
        assert p.pipfile["source"][0]["url"] == "${PYPI_URL}/simple"
        assert p.lockfile["_meta"]["sources"][0]["url"] == "${PYPI_URL}/simple"


@pytest.mark.basic
@pytest.mark.editable
@pytest.mark.badparameter
@pytest.mark.install
def test_editable_no_args(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install -e")
        assert c.returncode != 0
        assert "Error: Option '-e' requires an argument" in c.stderr


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.virtualenv
def test_install_venv_project_directory(pipenv_instance_pypi):
    """Test the project functionality during virtualenv creation.
    """
    with pipenv_instance_pypi(chdir=True) as p:
        with temp_environ(), TemporaryDirectory(
            prefix="pipenv-", suffix="temp_workon_home"
        ) as workon_home:
            os.environ["WORKON_HOME"] = workon_home

            c = p.pipenv("install six")
            assert c.returncode == 0

            venv_loc = None
            for line in c.stderr.splitlines():
                if line.startswith("Virtualenv location:"):
                    venv_loc = Path(line.split(":", 1)[-1].strip())
            assert venv_loc is not None
            assert venv_loc.joinpath(".project").exists()


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
def test_system_and_deploy_work(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi(chdir=True) as p:
        c = p.pipenv("install tablib")
        assert c.returncode == 0
        c = p.pipenv("--rm")
        assert c.returncode == 0
        c = subprocess_run(["virtualenv", ".venv"])
        assert c.returncode == 0
        c = p.pipenv("install --system --deploy")
        assert c.returncode == 0
        c = p.pipenv("--rm")
        assert c.returncode == 0
        Path(p.pipfile_path).write_text(
            """
[packages]
tablib = "*"
        """.strip()
        )
        c = p.pipenv("install --system")
        assert c.returncode == 0


@pytest.mark.basic
@pytest.mark.install
def test_install_creates_pipfile(pipenv_instance_pypi):
    with pipenv_instance_pypi(chdir=True) as p:
        if os.path.isfile(p.pipfile_path):
            os.unlink(p.pipfile_path)
        if "PIPENV_PIPFILE" in os.environ:
            del os.environ["PIPENV_PIPFILE"]
        assert not os.path.isfile(p.pipfile_path)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert os.path.isfile(p.pipfile_path)


@pytest.mark.basic
@pytest.mark.install
def test_install_non_exist_dep(pipenv_instance_pypi):
    with pipenv_instance_pypi(chdir=True) as p:
        c = p.pipenv("install dateutil")
        assert c.returncode
        assert "dateutil" not in p.pipfile["packages"]


@pytest.mark.basic
@pytest.mark.install
def test_install_package_with_dots(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi(chdir=True) as p:
        c = p.pipenv("install backports.html")
        assert c.returncode == 0
        assert "backports.html" in p.pipfile["packages"]


@pytest.mark.basic
@pytest.mark.install
def test_rewrite_outline_table(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
six = {version = "*"}

[packages.requests]
version = "*"
extras = ["socks"]
            """.strip()
            f.write(contents)
        c = p.pipenv("install flask")
        assert c.returncode == 0
        with open(p.pipfile_path) as f:
            contents = f.read()
        assert "[packages.requests]" not in contents
        assert 'six = {version = "*"}' in contents
        assert 'requests = {version = "*"' in contents
        assert 'flask = "*"' in contents


@flaky
@pytest.mark.dev
@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_with_unnamed_source(pipenv_instance_pypi):
    """Ensure that running `pipenv install` doesn't break with an unamed index"""
    with pipenv_instance_pypi(chdir=True) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://pypi.org/simple"
verify_ssl = true

[packages]
dataclasses-json = {version="*", index="pypi"}
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0


@pytest.mark.dev
@pytest.mark.install
def test_install_dev_use_default_constraints(pipenv_instance_private_pypi):
    # See https://github.com/pypa/pipenv/issues/4371
    # See https://github.com/pypa/pipenv/issues/2987
    with pipenv_instance_private_pypi(chdir=True) as p:

        c = p.pipenv("install requests==2.14.0")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert p.lockfile["default"]["requests"]["version"] == "==2.14.0"

        c = p.pipenv("install --dev requests")
        assert c.returncode == 0
        assert "requests" in p.lockfile["develop"]
        assert p.lockfile["develop"]["requests"]["version"] == "==2.14.0"

        # requests 2.14.0 doesn't require these packages
        assert "idna" not in p.lockfile["develop"]
        assert "certifi" not in p.lockfile["develop"]
        assert "urllib3" not in p.lockfile["develop"]
        assert "chardet" not in p.lockfile["develop"]

        c = p.pipenv("run python -c 'import urllib3'")
        assert c.returncode != 0


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_does_not_exclude_packaging(pipenv_instance_pypi):
    """Ensure that running `pipenv install` doesn't exclude packaging when its required. """
    with pipenv_instance_pypi(chdir=True) as p:
        c = p.pipenv("install dataclasses-json")
        assert c.returncode == 0
        c = p.pipenv("run python -c 'from dataclasses_json import DataClassJsonMixin'")
        assert c.returncode == 0


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_will_supply_extra_pip_args(pipenv_instance_pypi):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("""install dataclasses-json --extra-pip-args=""--use-feature=truststore --proxy=test""")
        assert c.returncode == 1
        assert "truststore feature" in c.stderr


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_tarball_is_actually_installed(pipenv_instance_pypi):
    """ Test case for Issue 5326"""
    with pipenv_instance_pypi(chdir=True) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
dataclasses-json = {file = "https://files.pythonhosted.org/packages/85/94/1b30216f84c48b9e0646833f6f2dd75f1169cc04dc45c48fe39e644c89d5/dataclasses-json-0.5.7.tar.gz"}
                    """.strip()
            f.write(contents)
        c = p.pipenv("lock")
        assert c.returncode == 0
        c = p.pipenv("sync")
        assert c.returncode == 0
        c = p.pipenv("run python -c 'from dataclasses_json import dataclass_json'")
        assert c.returncode == 0
