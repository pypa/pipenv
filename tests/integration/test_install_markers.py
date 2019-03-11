import os
import sys

import pytest

from flaky import flaky

from pipenv.patched import pipfile
from pipenv.project import Project
from pipenv.utils import temp_environ


@pytest.mark.markers
@flaky
def test_package_environment_markers(PipenvInstance, pypi):

    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
tablib = {version = "*", markers="os_name=='splashwear'"}
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0
        assert 'Ignoring' in c.out
        assert 'markers' in p.lockfile['default']['tablib']

        c = p.pipenv('run python -c "import tablib;"')
        assert c.return_code == 1

@pytest.mark.markers
@flaky
def test_platform_python_implementation_marker(PipenvInstance, pypi):
    """Markers should be converted during locking to help users who input this
    incorrectly.
    """
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
depends-on-marked-package = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0

        # depends-on-marked-package has an install_requires of
        # 'pytz; platform_python_implementation=="CPython"'
        # Verify that that marker shows up in our lockfile unaltered.
        assert 'pytz' in p.lockfile['default']
        assert p.lockfile['default']['pytz'].get('markers') == \
            "platform_python_implementation == 'CPython'"


@pytest.mark.run
@pytest.mark.alt
@pytest.mark.install
@flaky
def test_specific_package_environment_markers(PipenvInstance, pypi):

    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = {version = "*", os_name = "== 'splashwear'"}
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0

        assert 'Ignoring' in c.out
        assert 'markers' in p.lockfile['default']['requests']

        c = p.pipenv('run python -c "import requests;"')
        assert c.return_code == 1


@pytest.mark.markers
@flaky
def test_top_level_overrides_environment_markers(PipenvInstance, pypi):
    """Top-level environment markers should take precedence.
    """
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
apscheduler = "*"
funcsigs = {version = "*", os_name = "== 'splashwear'"}
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0

        assert p.lockfile['default']['funcsigs']['markers'] == "os_name == 'splashwear'"


@pytest.mark.markers
@pytest.mark.install
@flaky
def test_global_overrides_environment_markers(PipenvInstance, pypi):
    """Empty (unconditional) dependency should take precedence.
    If a dependency is specified without environment markers, it should
    override dependencies with environment markers. In this example,
    APScheduler requires funcsigs only on Python 2, but since funcsigs is
    also specified as an unconditional dep, its markers should be empty.
    """
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
apscheduler = "*"
funcsigs = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0

        assert p.lockfile['default']['funcsigs'].get('markers', '') == ''


@pytest.mark.lock
@pytest.mark.complex
@pytest.mark.py3_only
@pytest.mark.lte_py36
@flaky
def test_resolver_unique_markers(PipenvInstance, pypi):
    """vcrpy has a dependency on `yarl` which comes with a marker
    of 'python version in "3.4, 3.5, 3.6" - this marker duplicates itself:

    'yarl; python version in "3.4, 3.5, 3.6"; python version in "3.4, 3.5, 3.6"'

    This verifies that we clean that successfully.
    """
    with PipenvInstance(chdir=True, pypi=pypi) as p:
        c = p.pipenv('install vcrpy==1.11.0')
        assert c.return_code == 0
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert 'yarl' in p.lockfile['default']
        yarl = p.lockfile['default']['yarl']
        assert 'markers' in yarl
        # Two possible marker sets are ok here
        assert yarl['markers'] in ["python_version in '3.4, 3.5, 3.6'", "python_version >= '3.4.1'"]


@pytest.mark.project
@flaky
def test_environment_variable_value_does_not_change_hash(PipenvInstance, pypi):
    with PipenvInstance(chdir=True, pypi=pypi) as p:
        with temp_environ():
            with open(p.pipfile_path, 'w') as f:
                f.write("""
[[source]]
url = 'https://${PYPI_USERNAME}:${PYPI_PASSWORD}@pypi.org/simple'
verify_ssl = true
name = 'pypi'

[packages]
six = "*"
""")
            project = Project()

            os.environ['PYPI_USERNAME'] = 'whatever'
            os.environ['PYPI_PASSWORD'] = 'pass'
            assert project.get_lockfile_hash() is None

            c = p.pipenv('install')
            assert c.return_code == 0
            lock_hash = project.get_lockfile_hash()
            assert lock_hash is not None
            assert lock_hash == project.calculate_pipfile_hash()

            # sanity check on pytest
            assert 'PYPI_USERNAME' not in str(pipfile.load(p.pipfile_path))
            assert c.return_code == 0
            assert project.get_lockfile_hash() == project.calculate_pipfile_hash()

            os.environ['PYPI_PASSWORD'] = 'pass2'
            assert project.get_lockfile_hash() == project.calculate_pipfile_hash()

            with open(p.pipfile_path, 'a') as f:
                f.write('requests = "==2.14.0"\n')
            assert project.get_lockfile_hash() != project.calculate_pipfile_hash()
