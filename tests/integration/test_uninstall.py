import sys

import pytest

from pipenv.utils.shell import temp_environ

from .conftest import DEFAULT_PRIVATE_PYPI_SERVER


@pytest.mark.uninstall
@pytest.mark.install
def test_uninstall_requests(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install requests")
        assert c.returncode == 0
        assert "requests" in p.pipfile["packages"]

        c = p.pipenv("uninstall requests")
        assert c.returncode == 0
        assert "requests" not in p.pipfile["packages"]
        assert "requests" not in p.lockfile["default"]


@pytest.mark.uninstall
@pytest.mark.skipif(
    sys.version_info >= (3, 12), reason="Package does not work with Python 3.12"
)
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
@pytest.mark.skipif(
    sys.version_info >= (3, 12), reason="Package does not work with Python 3.12"
)
def test_mirror_uninstall(pipenv_instance_pypi):
    with temp_environ(), pipenv_instance_pypi() as p:
        mirror_url = DEFAULT_PRIVATE_PYPI_SERVER
        assert "pypi.org" not in mirror_url

        c = p.pipenv(f"install Django --pypi-mirror {mirror_url}")
        assert c.returncode == 0
        assert "django" in p.pipfile["packages"]
        assert "django" in p.lockfile["default"]
        assert "pytz" in p.lockfile["default"]
        # Ensure the --pypi-mirror parameter hasn't altered the Pipfile or Pipfile.lock sources
        assert len(p.pipfile["source"]) == 1
        assert len(p.lockfile["_meta"]["sources"]) == 1
        assert p.pipfile["source"][0]["url"] == "https://pypi.org/simple"
        assert p.lockfile["_meta"]["sources"][0]["url"] == "https://pypi.org/simple"

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
        assert p.pipfile["source"][0]["url"] == "https://pypi.org/simple"
        assert p.lockfile["_meta"]["sources"][0]["url"] == "https://pypi.org/simple"

        c = p.pipenv("run python -m django --version")
        assert c.returncode > 0


@pytest.mark.files
@pytest.mark.install
@pytest.mark.uninstall
def test_uninstall_all_local_files(pipenv_instance_private_pypi, testsroot):
    with pipenv_instance_private_pypi() as p:
        file_uri = p._pipfile.get_fixture_path(
            "tablib/tablib-0.12.1.tar.gz", fixtures="pypi"
        ).as_uri()
        c = p.pipenv(f"install {file_uri}")
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
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
name = "pypi"
url = "{p.index_url}"
verify_ssl = true

[packages]
tablib = "*"

[dev-packages]
jinja2 = "==2.11.1"
six = "==1.12.0"
        """
            f.write(contents)

        c = p.pipenv("install -v --dev")
        assert c.returncode == 0

        assert "tablib" in p.pipfile["packages"]
        assert "jinja2" in p.pipfile["dev-packages"]
        assert "six" in p.pipfile["dev-packages"]
        assert "tablib" in p.lockfile["default"]
        assert "jinja2" in p.lockfile["develop"]
        assert "six" in p.lockfile["develop"]
        assert c.returncode == 0

        c = p.pipenv("uninstall -v --all-dev")
        assert c.returncode == 0
        assert p.pipfile["dev-packages"] == {}
        assert "jinja2" not in p.lockfile["develop"]
        assert "six" not in p.lockfile["develop"]
        assert "tablib" in p.pipfile["packages"]
        assert "tablib" in p.lockfile["default"]

        c = p.pipenv('run python -c "import jinja2"')
        assert c.returncode > 0

        c = p.pipenv('run python -c "import tablib"')
        assert c.returncode == 0


@pytest.mark.install
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
        with open(p.pipfile_path, "w") as f:
            contents = """
        [packages]
        pytest = "==4.6.11"

        [dev-packages]
        six = "*"
        """
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0

        c = p.pipenv("uninstall --all-dev")
        assert c.returncode == 0

        assert "six" in p.lockfile["default"]


@pytest.mark.install
@pytest.mark.uninstall
def test_uninstall_missing_parameters(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install six")
        assert c.returncode == 0

        c = p.pipenv("uninstall")
        assert c.returncode != 0
        assert "No package provided!" in c.stderr


@pytest.mark.categories
@pytest.mark.install
@pytest.mark.uninstall
def test_uninstall_category_with_shared_requirement(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
        [packages]
        six = "*"

        [prereq]
        six = "*"
        """
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0

        c = p.pipenv("uninstall six --categories default")
        assert c.returncode == 0

        assert "six" in p.lockfile["prereq"]
        assert "six" not in p.lockfile["default"]


@pytest.mark.categories
@pytest.mark.install
@pytest.mark.uninstall
def test_uninstall_multiple_categories(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
        [after]
        six = "==1.12.0"

        [prereq]
        six = "==1.12.0"
        """
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0

        c = p.pipenv('uninstall six --categories="prereq after"')
        assert c.returncode == 0

        assert "six" not in p.lockfile.get("prereq", {})
        assert "six" not in p.lockfile["default"]


@pytest.mark.install
@pytest.mark.uninstall
def test_category_sorted_alphabetically_with_directive(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[pipenv]
sort_pipfile = true

[packages]
parse = "*"
colorama = "*"
build = "*"
atomicwrites = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0

        c = p.pipenv("uninstall build")
        assert c.returncode == 0
        assert "build" not in p.pipfile["packages"]
        assert list(p.pipfile["packages"].keys()) == ["atomicwrites", "colorama", "parse"]


@pytest.mark.install
@pytest.mark.uninstall
def test_sorting_handles_str_values_and_dict_values(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[pipenv]
sort_pipfile = true

[packages]
zipp = "*"
parse = {version = "*"}
colorama = "*"
build = "*"
atomicwrites = {version = "*"}
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0

        c = p.pipenv("uninstall build")
        assert c.returncode == 0
        assert "build" not in p.pipfile["packages"]
        assert list(p.pipfile["packages"].keys()) == [
            "atomicwrites",
            "colorama",
            "parse",
            "zipp",
        ]


@pytest.mark.install
@pytest.mark.uninstall
def test_category_not_sorted_without_directive(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
parse = "*"
colorama = "*"
build = "*"
atomicwrites = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0

        c = p.pipenv("uninstall build")
        assert c.returncode == 0
        assert "build" not in p.pipfile["packages"]
        assert list(p.pipfile["packages"].keys()) == [
            "parse",
            "colorama",
            "atomicwrites",
        ]


@pytest.mark.uninstall
def test_uninstall_without_venv(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
colorama = "*"
atomicwrites = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0

        c = p.pipenv("uninstall --all")
        assert c.returncode == 0
        # uninstall --all shold not remove packages from Pipfile
        assert list(p.pipfile["packages"].keys()) == ["colorama", "atomicwrites"]
