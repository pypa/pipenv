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
def test_basic_setup(PipenvInstance):
    with PipenvInstance() as p:
        with PipenvInstance(pipfile=False) as p:
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
def test_basic_install(PipenvInstance):
    with PipenvInstance() as p:
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
def test_mirror_install(PipenvInstance):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        mirror_url = os.environ.pop(
            "PIPENV_TEST_INDEX", "https://pypi.python.org/simple"
        )
        assert "pypi.org" not in mirror_url
        # This should sufficiently demonstrate the mirror functionality
        # since pypi.org is the default when PIPENV_TEST_INDEX is unset.
        c = p.pipenv(f"install requests --pypi-mirror {mirror_url}")
        assert c.returncode == 0
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


@flaky
@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_bad_mirror_install(PipenvInstance):
    with temp_environ(), PipenvInstance(chdir=True) as p:
        # This demonstrates that the mirror parameter is being used
        os.environ.pop("PIPENV_TEST_INDEX", None)
        c = p.pipenv("install requests --pypi-mirror https://pypi.example.org")
        assert c.returncode != 0


@flaky
@pytest.mark.dev
@pytest.mark.run
def test_basic_dev_install(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv("install requests --dev")
        assert c.returncode == 0
        assert "requests" in p.pipfile["dev-packages"]
        assert "requests" in p.lockfile["develop"]
        assert "chardet" in p.lockfile["develop"]
        assert "idna" in p.lockfile["develop"]
        assert "urllib3" in p.lockfile["develop"]
        assert "certifi" in p.lockfile["develop"]

        c = p.pipenv("run python -m requests.help")
        assert c.returncode == 0


@flaky
@pytest.mark.dev
@pytest.mark.basic
@pytest.mark.install
def test_install_without_dev(PipenvInstance):
    """Ensure that running `pipenv install` doesn't install dev packages"""
    with PipenvInstance(chdir=True) as p:
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
def test_install_without_dev_section(PipenvInstance):
    with PipenvInstance() as p:
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
def test_extras_install(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
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
def test_windows_pinned_pipfile(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
requests = "==2.19.1"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "requests" in p.pipfile["packages"]
        assert "requests" in p.lockfile["default"]


@flaky
@pytest.mark.basic
@pytest.mark.install
@pytest.mark.resolver
@pytest.mark.backup_resolver
def test_backup_resolver(PipenvInstance):
    with PipenvInstance() as p:
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
def test_alternative_version_specifier(PipenvInstance):
    with PipenvInstance() as p:
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
def test_outline_table_specifier(PipenvInstance):
    with PipenvInstance() as p:
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
def test_bad_packages(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv("install NotAPackage")
        assert c.returncode > 0


@pytest.mark.lock
@pytest.mark.extras
@pytest.mark.install
@pytest.mark.requirements
def test_requirements_to_pipfile(PipenvInstance, pypi):

    with PipenvInstance(pipfile=False, chdir=True) as p:

        # Write a requirements file
        with open("requirements.txt", "w") as f:
            f.write(
                f"-i {pypi.url}\n"
                "# -i https://private.pypi.org/simple\n"
                "requests[socks]==2.19.1\n"
            )

        c = p.pipenv("install")
        assert c.returncode == 0
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
def test_skip_requirements_when_pipfile(PipenvInstance):
    """Ensure requirements.txt is NOT imported when

    1. We do `pipenv install [package]`
    2. A Pipfile already exists when we run `pipenv install`.
    """
    with PipenvInstance(chdir=True) as p:
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
def test_clean_on_empty_venv(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv("clean")
        assert c.returncode == 0


@pytest.mark.basic
@pytest.mark.install
def test_install_does_not_extrapolate_environ(PipenvInstance):
    """Ensure environment variables are not expanded in lock file.
    """
    with temp_environ(), PipenvInstance(chdir=True) as p:
        # os.environ["PYPI_URL"] = pypi.url
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
def test_editable_no_args(PipenvInstance):
    with PipenvInstance() as p:
        c = p.pipenv("install -e")
        assert c.returncode != 0
        assert "Error: Option '-e' requires an argument" in c.stderr


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.virtualenv
def test_install_venv_project_directory(PipenvInstance):
    """Test the project functionality during virtualenv creation.
    """
    with PipenvInstance(chdir=True) as p:
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
def test_system_and_deploy_work(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
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
def test_install_creates_pipfile(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
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
def test_install_non_exist_dep(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install dateutil")
        assert c.returncode
        assert "dateutil" not in p.pipfile["packages"]


@pytest.mark.basic
@pytest.mark.install
def test_install_package_with_dots(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install backports.html")
        assert c.returncode == 0
        assert "backports.html" in p.pipfile["packages"]


@pytest.mark.basic
@pytest.mark.install
def test_rewrite_outline_table(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
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
def test_install_with_unnamed_source(PipenvInstance):
    """Ensure that running `pipenv install` doesn't break with an unamed index"""
    with PipenvInstance(chdir=True) as p:
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
requests = {version="*", index="pypi"}
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0

@pytest.mark.dev
@pytest.mark.install
def test_install_dev_use_default_constraints(PipenvInstance):
    # See https://github.com/pypa/pipenv/issues/4371
    # See https://github.com/pypa/pipenv/issues/2987
    with PipenvInstance(chdir=True) as p:

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
def test_install_does_not_exclude_packaging(PipenvInstance):
    """Ensure that running `pipenv install` doesn't exclude packaging when its required. """
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install dataclasses-json")
        assert c.returncode == 0
        c = p.pipenv("run python -c 'from dataclasses_json import DataClassJsonMixin'")
        assert c.returncode == 0


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_will_supply_extra_pip_args(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("""install requests --extra-pip-args=""--use-feature=truststore --proxy=test""")
        assert c.returncode == 1
        assert "truststore feature" in c.stderr


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_tarball_is_actually_installed(PipenvInstance):
    """ Test case for Issue 5326"""
    with PipenvInstance(chdir=True) as p:
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
