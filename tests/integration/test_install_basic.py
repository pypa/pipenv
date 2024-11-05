import json
import os
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import temp_environ


@pytest.mark.basic
@pytest.mark.install
def test_basic_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install six -v")
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]


@pytest.mark.basic
@pytest.mark.install
def test_mirror_install(pipenv_instance_pypi):
    with temp_environ(), pipenv_instance_pypi() as p:
        mirror_url = "https://pypi.python.org/simple"
        assert "pypi.org" not in mirror_url
        # This should sufficiently demonstrate the mirror functionality
        c = p.pipenv(f"install dataclasses-json --pypi-mirror {mirror_url}")
        assert c.returncode == 0
        # Ensure the --pypi-mirror parameter hasn't altered the Pipfile or Pipfile.lock sources
        assert len(p.pipfile["source"]) == 1
        assert len(p.lockfile["_meta"]["sources"]) == 1
        assert p.pipfile["source"][0]["url"] == "https://pypi.org/simple"
        assert p.lockfile["_meta"]["sources"][0]["url"] == "https://pypi.org/simple"

        assert "dataclasses-json" in p.pipfile["packages"]
        assert "dataclasses-json" in p.lockfile["default"]


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_bad_mirror_install(pipenv_instance_pypi):
    with temp_environ(), pipenv_instance_pypi() as p:
        # This demonstrates that the mirror parameter is being used
        c = p.pipenv("install dataclasses-json --pypi-mirror https://pypi.example.org")
        assert c.returncode != 0


@pytest.mark.dev
@pytest.mark.run
def test_basic_dev_install(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install dataclasses-json --dev")
        assert c.returncode == 0
        assert "dataclasses-json" in p.pipfile["dev-packages"]
        assert "dataclasses-json" in p.lockfile["develop"]

        c = p.pipenv("""run python -c "from dataclasses_json import dataclass_json" """)
        assert c.returncode == 0


@pytest.mark.dev
@pytest.mark.basic
@pytest.mark.install
def test_install_without_dev(pipenv_instance_private_pypi):
    """Ensure that running `pipenv install` doesn't install dev packages"""
    with pipenv_instance_private_pypi() as p:
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


@pytest.mark.basic
@pytest.mark.install
def test_install_with_version_req_default_operator(pipenv_instance_private_pypi):
    """Ensure that running `pipenv install` work when spec is package = "X.Y.Z"."""
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "1.12.0"
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]


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


@pytest.mark.lock
@pytest.mark.extras
@pytest.mark.install
def test_extras_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install requests[socks]")
        assert c.returncode == 0
        assert "requests" in p.pipfile["packages"]
        assert "extras" in p.pipfile["packages"]["requests"]

        assert "requests" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "pysocks" in p.lockfile["default"]


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


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.resolver
@pytest.mark.backup_resolver
@pytest.mark.skipif(
    sys.version_info >= (3, 12), reason="Package does not work with Python 3.12"
)
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


@pytest.mark.run
@pytest.mark.alt
def test_alternative_version_specifier(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = {version = "*"}
            """.strip()
            f.write(contents)

        c = p.pipenv("install -v")
        assert c.returncode == 0

        assert "six" in p.lockfile["default"]

        c = p.pipenv('run python -c "import six;"')
        assert c.returncode == 0


@pytest.mark.run
@pytest.mark.alt
def test_outline_table_specifier(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages.six]
version = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0

        assert "six" in p.lockfile["default"]

        c = p.pipenv('run python -c "import six;"')
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
    with pipenv_instance_private_pypi(pipfile=False) as p:
        # Write a requirements file
        with open("requirements.txt", "w") as f:
            f.write(f"-i {p.index_url}\nrequests[socks]==2.19.1\n")

        c = p.pipenv("install")
        assert c.returncode == 0
        os.unlink("requirements.txt")
        print(c.stdout)
        print(c.stderr)
        # assert stuff in pipfile
        assert "requests" in p.pipfile["packages"]
        assert "extras" in p.pipfile["packages"]["requests"]
        assert not any(
            source["url"] == "https://private.pypi.org/simple"
            for source in p.pipfile["source"]
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
    with pipenv_instance_private_pypi() as p:
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
def test_install_does_not_extrapolate_environ(pipenv_instance_private_pypi):
    """Ensure environment variables are not expanded in lock file."""
    with temp_environ(), pipenv_instance_private_pypi() as p:
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
        c = p.pipenv("install -v")
        assert c.returncode == 0
        assert p.pipfile["source"][0]["url"] == "${PYPI_URL}/simple"
        assert p.lockfile["_meta"]["sources"][0]["url"] == "${PYPI_URL}/simple"

        # Ensure package install does not extrapolate.
        c = p.pipenv("install six -v")
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
    """Test the project functionality during virtualenv creation."""
    with pipenv_instance_pypi() as p, temp_environ(), TemporaryDirectory(
        prefix="pipenv-", suffix="temp_workon_home"
    ) as workon_home:
        os.environ["WORKON_HOME"] = workon_home

        c = p.pipenv("install six")
        assert c.returncode == 0

        venv_loc_patt = r"Virtualenv location:(.*?)(?=Pipfile\.lock)"
        match = re.search(venv_loc_patt, c.stderr, re.DOTALL)

        assert match

        # Extract the matched text
        venv_loc = match.group(1).strip()

        venv_loc = Path(venv_loc)
        assert venv_loc.joinpath(".project").exists()


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
def test_system_and_deploy_work(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install urllib3")
        assert c.returncode == 0
        c = p.pipenv("--rm")
        assert c.returncode == 0
        c = subprocess_run(["virtualenv", ".venv"])
        assert c.returncode == 0
        c = p.pipenv("install --system --deploy")
        assert c.returncode == 0



@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
def test_system_works(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install urllib3")
        assert c.returncode == 0
        c = p.pipenv("--rm")
        assert c.returncode == 0
        c = subprocess_run(["virtualenv", ".venv"])
        assert c.returncode == 0
        c = p.pipenv("install --system")
        assert c.returncode == 0


@pytest.mark.basic
@pytest.mark.install
def test_install_creates_pipfile(pipenv_instance_pypi):
    with pipenv_instance_pypi(pipfile=False) as p:
        assert not os.path.isfile(p.pipfile_path)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert os.path.isfile(p.pipfile_path)
        python_version = str(sys.version_info.major) + "." + str(sys.version_info.minor)
        assert p.pipfile["requires"] == {"python_version": python_version}


@pytest.mark.basic
@pytest.mark.install
def test_create_pipfile_requires_python_full_version(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi(pipfile=False) as p:
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        python_full_version = f"{python_version}.{sys.version_info.micro}"
        c = p.pipenv(f"--python {python_full_version}")
        assert c.returncode == 0
        assert p.pipfile["requires"] == {
            "python_full_version": python_full_version,
            "python_version": python_version,
        }


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.virtualenv
def test_install_with_pipfile_including_exact_python_version(pipenv_instance_pypi):
    valid_version = f"{sys.version_info.major}.{sys.version_info.minor}"

    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            f.write(
                f"""
[[source]]
url = "https://test.pypi.org/simple"
verify_ssl = true
name = "testpypi"

[packages]
pytz = "*"

[requires]
python_version = "{valid_version}"
"""
            )

        c = p.pipenv("install")
        assert c.returncode == 0
        assert os.path.isfile(p.pipfile_path)
        assert p.pipfile["requires"]["python_version"] == valid_version

        c = p.pipenv("--rm")
        assert c.returncode == 0


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.virtualenv
def test_install_with_pipfile_including_invalid_python_version(pipenv_instance_pypi):
    invalid_versions = [
        f">={sys.version_info.major}.{sys.version_info.minor}",
        f"<={sys.version_info.major}.{sys.version_info.minor}",
        f">{sys.version_info.major}.{sys.version_info.minor}",
        f"<{sys.version_info.major}.{sys.version_info.minor}",
    ]

    with pipenv_instance_pypi() as p:
        for version in invalid_versions:
            with open(p.pipfile_path, "w") as f:
                f.write(
                    f"""
[[source]]
url = "https://test.pypi.org/simple"
verify_ssl = true
name = "testpypi"

[packages]
pytz = "*"

[requires]
python_version = "{version}"
"""
                )
            c = p.pipenv("install")
            assert c.returncode != 0


@pytest.mark.basic
@pytest.mark.install
def test_install_non_exist_dep(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install dateutil")
        assert c.returncode
        assert "dateutil" not in p.pipfile["packages"]


@pytest.mark.basic
@pytest.mark.install
def test_install_package_with_dots(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install backports.html")
        assert c.returncode == 0
        assert "backports.html" in p.pipfile["packages"]


@pytest.mark.basic
@pytest.mark.install
def test_rewrite_outline_table(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "{}"
verify_ssl = false
name = "testindex"

[packages]
six = {}

[packages.requests]
version = "*"
extras = ["socks"]
            """.format(
                p.index_url, '{version = "*"}'
            ).strip()
            f.write(contents)
        c = p.pipenv("install colorama")
        assert c.returncode == 0
        with open(p.pipfile_path) as f:
            contents = f.read()
        assert "[packages.requests]" not in contents
        assert 'six = {version = "*"}' in contents
        assert 'requests = {version = "*"' in contents
        assert 'colorama = "*"' in contents


@pytest.mark.basic
@pytest.mark.install
def test_rewrite_outline_table_ooo(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "{}"
verify_ssl = false
name = "testindex"

[packages]
six = {}

# Out-of-order
[pipenv]
allow_prereleases = false

[packages.requests]
version = "*"
extras = ["socks"]
            """.format(
                p.index_url, '{version = "*"}'
            ).strip()
            f.write(contents)
        c = p.pipenv("install colorama")
        assert c.returncode == 0
        with open(p.pipfile_path) as f:
            contents = f.read()
        assert "[packages.requests]" not in contents
        assert 'six = {version = "*"}' in contents
        assert 'requests = {version = "*"' in contents
        assert 'colorama = "*"' in contents


@pytest.mark.dev
@pytest.mark.install
def test_install_dev_use_default_constraints(pipenv_instance_private_pypi):
    # See https://github.com/pypa/pipenv/issues/4371
    # See https://github.com/pypa/pipenv/issues/2987
    with pipenv_instance_private_pypi() as p:
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
    """Ensure that running `pipenv install` doesn't exclude packaging when its required."""
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install dataclasses-json")
        assert c.returncode == 0
        c = p.pipenv(
            """run python -c "from dataclasses_json import DataClassJsonMixin" """
        )
        assert c.returncode == 0


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
@pytest.mark.skip(
    reason="pip 23.3 now vendors in truststore and so test assumptions invalid "
)
def test_install_will_supply_extra_pip_args(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv(
            """install -v dataclasses-json --extra-pip-args="--use-feature=truststore --proxy=test" """
        )
        assert c.returncode == 1
        assert "truststore feature" in c.stdout


@pytest.mark.basic
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_tarball_is_actually_installed(pipenv_instance_pypi):
    """Test case for Issue 5326"""
    with pipenv_instance_pypi() as p:
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
        c = p.pipenv("""run python -c "from dataclasses_json import dataclass_json" """)
        assert c.returncode == 0


@pytest.mark.basic
@pytest.mark.install
def test_category_sorted_alphabetically_with_directive(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[pipenv]
sort_pipfile = true

[packages]
atomicwrites = "*"
colorama = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv("install build")
        assert c.returncode == 0
        assert "build" in p.pipfile["packages"]
        assert list(p.pipfile["packages"].keys()) == ["atomicwrites", "build", "colorama"]


@pytest.mark.basic
@pytest.mark.install
def test_sorting_handles_str_values_and_dict_values(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[pipenv]
sort_pipfile = true

[packages]
zipp = {version = "*"}
parse = "*"
colorama = "*"
atomicwrites = {version = "*"}
            """.strip()
            f.write(contents)
        c = p.pipenv("install build")
        assert c.returncode == 0
        assert "build" in p.pipfile["packages"]
        assert list(p.pipfile["packages"].keys()) == [
            "atomicwrites",
            "build",
            "colorama",
            "parse",
            "zipp",
        ]


@pytest.mark.basic
@pytest.mark.install
def test_category_not_sorted_without_directive(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
atomicwrites = "*"
colorama = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv("install build")
        assert c.returncode == 0
        assert "build" in p.pipfile["packages"]
        assert list(p.pipfile["packages"].keys()) == [
            "atomicwrites",
            "colorama",
            "build",
        ]


@pytest.mark.basic
@pytest.mark.install
def test_category_sorted_with_directive_when_insalling_with_extras(
    pipenv_instance_private_pypi,
):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w+") as f:
            contents = """
[pipenv]
sort_pipfile = true

[packages]
atomicwrites = "*"
six = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv("install requests[socks]")
        assert c.returncode == 0
        assert "requests" in p.pipfile["packages"]
        assert "extras" in p.pipfile["packages"]["requests"]
        assert list(p.pipfile["packages"].keys()) == [
            "atomicwrites",
            "requests",
            "six",
        ]


@pytest.mark.basic
@pytest.mark.install
def test_install_respects_lockfile_versions(pipenv_instance_pypi):
    """Ensure that `pipenv install` respects versions from existing lockfile."""
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
sh = "*"
            """.strip()
            f.write(contents)

        with open(p.lockfile_path, "w") as f:
            contents = """
{
    "_meta": {
        "hash": {
            "sha256": "f9adf532d46f4787b6afe331abe415d5698ef7523cd6225605328b61f361d427"
        },
        "pipfile-spec": 6,
        "requires": {},
        "sources": [
            {
                "name": "pypi",
                "url": "https://pypi.org/simple",
                "verify_ssl": true
            }
        ]
    },
    "default": {
        "sh": {
            "hashes": [
                "sha256:39aa9af22f6558a0c5d132881cf43e34828ca03e4ae11114852ca6a55c7c1d8e",
                "sha256:75e86a836f47de095d4531718fe8489e6f7446c75ddfa5596f632727b919ffae"
            ],
            "index": "pypi",
            "version": "==1.14.1"
        }
    },
    "develop": {}
}
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0

        # Verify that the locked version is installed, not the latest
        c = p.pipenv("graph --json")
        assert c.returncode == 0

        graph_data = json.loads(c.stdout)
        for entry in graph_data:
            if entry["package"]["package_name"] == "sh":
                assert entry["package"]["installed_version"] == "1.14.1"
                break
        else:
            pytest.fail("sh package not found in graph output")
