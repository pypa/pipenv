import os
import sys

import pytest

from pipenv.project import Project
from pipenv.utils.shell import temp_environ


@pytest.mark.markers
def test_package_environment_markers(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "{}"
verify_ssl = false
name = "pypi"

[packages]
dataclass-factory = {}

[dev-packages]
            """.format(
                p.index_url,
                '{version = "*", os_name = "== \'splashwear\'", index="pypi"}',
            ).strip()
            f.write(contents)

        c = p.pipenv("install -v")
        assert c.returncode == 0
        assert "markers" in p.lockfile["default"]["dataclass-factory"], p.lockfile["default"]
        assert (
            p.lockfile["default"]["dataclass-factory"]["markers"] == "python_version >= '3.6' and os_name == 'splashwear'"
        ), p.lockfile["default"]["dataclass-factory"]["markers"]
        c = p.pipenv('run python -c "import dataclass_factory;"')
        assert c.returncode == 1  # dataclass-factory is not installed due to the marker


@pytest.mark.flaky(reruns=3)
@pytest.mark.markers
def test_platform_python_implementation_marker(pipenv_instance_private_pypi):
    """Markers should be converted during locking to help users who input this
    incorrectly.
    """
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install depends-on-marked-package")
        assert c.returncode == 0

        # depends-on-marked-package has an install_requires of
        # 'pytz; platform_python_implementation=="CPython"'
        # Verify that that marker shows up in our lockfile unaltered.
        assert "pytz" in p.lockfile["default"]
        assert (
            p.lockfile["default"]["pytz"].get("markers")
            == "platform_python_implementation == 'CPython'"
        )


@pytest.mark.flaky(reruns=3)
@pytest.mark.alt
@pytest.mark.markers
@pytest.mark.install
def test_specific_package_environment_markers(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = {version = "*", os_name = "== 'splashwear'"}
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0
        assert "markers" in p.lockfile["default"]["six"]

        c = p.pipenv('run python -c "import six;"')
        assert c.returncode == 1


@pytest.mark.flaky(reruns=3)
@pytest.mark.markers
def test_top_level_overrides_environment_markers(pipenv_instance_pypi):
    """Top-level environment markers should take precedence."""
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
apscheduler = "*"
funcsigs = {version = "*", os_name = "== 'splashwear'"}
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0
        assert "markers" in p.lockfile["default"]["funcsigs"], p.lockfile["default"][
            "funcsigs"
        ]
        assert (
            p.lockfile["default"]["funcsigs"]["markers"] == "os_name == 'splashwear'"
        ), p.lockfile["default"]["funcsigs"]


@pytest.mark.flaky(reruns=3)
@pytest.mark.markers
@pytest.mark.install
def test_global_overrides_environment_markers(pipenv_instance_private_pypi):
    """Empty (unconditional) dependency should take precedence.
    If a dependency is specified without environment markers, it should
    override dependencies with environment markers. In this example,
    APScheduler requires funcsigs only on Python 2, but since funcsigs is
    also specified as an unconditional dep, its markers should be empty.
    """
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = false
name = "testindex"

[packages]
apscheduler = "*"
funcsigs = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0

        assert p.lockfile["default"]["funcsigs"].get("markers", "") == ""


@pytest.mark.flaky(reruns=3)
@pytest.mark.markers
@pytest.mark.complex
@pytest.mark.skipif(
    sys.version_info[:2] == (3, 8), reason="Test package that gets installed is different on 3.8"
)
def test_resolver_unique_markers(pipenv_instance_pypi):
    """Test that markers are properly cleaned and not duplicated when resolving
    dependencies. Use vcrpy as an example package that pulls in dependencies
    with Python version markers.

    This test verifies that even if a package ends up with duplicate markers like:
    'yarl; python_version >= "3.9"; python_version >= "3.9"'

    The resolver will clean and deduplicate them appropriately.
    """
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install vcrpy==2.0.1")
        assert c.returncode == 0
        assert "yarl" in p.lockfile["default"]
        yarl = p.lockfile["default"]["yarl"]
        assert "markers" in yarl
        # Check for a valid Python version marker
        # yarl >=1.16.0 (Oct 2024) requires Python >=3.9
        assert yarl["markers"] == "python_version >= '3.9'"


@pytest.mark.markers
@pytest.mark.install
@pytest.mark.needs_internet
@pytest.mark.skipif(
    os.name == "nt",
    reason="This dependency is not available on Windows",
)
def test_install_package_with_invalid_python_version_specifier(pipenv_instance_pypi):
    """Test that installing a package with an invalid Python version specifier
    doesn't raise a KeyError. This test verifies the fix for issue #6370.
    """
    with pipenv_instance_pypi() as p:
        # typedb-driver 3.0.5 has an invalid Python version specifier that was causing a KeyError
        c = p.pipenv("install typedb-driver==3.0.5")
        assert c.returncode == 0
        assert "typedb-driver" in p.pipfile["packages"]
        assert "typedb-driver" in p.lockfile["default"]


@pytest.mark.flaky(reruns=3)
@pytest.mark.project
@pytest.mark.needs_internet
def test_environment_variable_value_does_not_change_hash(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p, temp_environ():
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[[source]]
url = 'https://${PYPI_USERNAME}:${PYPI_PASSWORD}@pypi.org/simple'
verify_ssl = true
name = 'pypi'

[packages]
six = "*"
"""
            )
        project = Project()

        os.environ["PYPI_USERNAME"] = "whatever"
        os.environ["PYPI_PASSWORD"] = "pass"
        assert project.get_lockfile_hash() is None

        c = p.pipenv("install")
        assert c.returncode == 0
        lock_hash = project.get_lockfile_hash()
        assert lock_hash is not None
        assert lock_hash == project.calculate_pipfile_hash()

        assert c.returncode == 0
        assert project.get_lockfile_hash() == project.calculate_pipfile_hash()

        os.environ["PYPI_PASSWORD"] = "pass2"
        assert project.get_lockfile_hash() == project.calculate_pipfile_hash()

        with open(p.pipfile_path, "a") as f:
            f.write('requests = "==2.14.0"\n')
        assert project.get_lockfile_hash() != project.calculate_pipfile_hash()
