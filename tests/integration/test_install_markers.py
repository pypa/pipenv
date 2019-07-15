# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import os
import sys

import pytest

from flaky import flaky

from pipenv.patched import pipfile
from pipenv.project import Project
from pipenv.utils import temp_environ


@flaky
@pytest.mark.markers
def test_package_environment_markers(PipenvInstance):

    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
fake_package = {version = "*", markers="os_name=='splashwear'"}
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0
        assert 'Ignoring' in c.out
        assert 'markers' in p.lockfile['default']['fake-package'], p.lockfile["default"]

        c = p.pipenv('run python -c "import fake_package;"')
        assert c.return_code == 1


@flaky
@pytest.mark.markers
def test_platform_python_implementation_marker(PipenvInstance):
    """Markers should be converted during locking to help users who input this
    incorrectly.
    """
    with PipenvInstance() as p:
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


@flaky
@pytest.mark.run
@pytest.mark.alt
@pytest.mark.install
def test_specific_package_environment_markers(PipenvInstance):

    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
fake-package = {version = "*", os_name = "== 'splashwear'"}
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0

        assert 'Ignoring' in c.out
        assert 'markers' in p.lockfile['default']['fake-package']

        c = p.pipenv('run python -c "import fake_package;"')
        assert c.return_code == 1


@flaky
@pytest.mark.markers
def test_top_level_overrides_environment_markers(PipenvInstance):
    """Top-level environment markers should take precedence.
    """
    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
apscheduler = "*"
funcsigs = {version = "*", os_name = "== 'splashwear'"}
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0
        assert "markers" in p.lockfile['default']['funcsigs'], p.lockfile['default']['funcsigs']
        assert p.lockfile['default']['funcsigs']['markers'] == "os_name == 'splashwear'", p.lockfile['default']['funcsigs']


@flaky
@pytest.mark.markers
@pytest.mark.install
def test_global_overrides_environment_markers(PipenvInstance):
    """Empty (unconditional) dependency should take precedence.
    If a dependency is specified without environment markers, it should
    override dependencies with environment markers. In this example,
    APScheduler requires funcsigs only on Python 2, but since funcsigs is
    also specified as an unconditional dep, its markers should be empty.
    """
    with PipenvInstance() as p:
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


@flaky
@pytest.mark.lock
@pytest.mark.complex
@pytest.mark.py3_only
@pytest.mark.lte_py36
def test_resolver_unique_markers(PipenvInstance):
    """vcrpy has a dependency on `yarl` which comes with a marker
    of 'python version in "3.4, 3.5, 3.6" - this marker duplicates itself:

    'yarl; python version in "3.4, 3.5, 3.6"; python version in "3.4, 3.5, 3.6"'

    This verifies that we clean that successfully.
    """
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv('install vcrpy==2.0.1')
        assert c.return_code == 0
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert 'yarl' in p.lockfile['default']
        yarl = p.lockfile['default']['yarl']
        assert 'markers' in yarl
        # Two possible marker sets are ok here
        assert yarl['markers'] in ["python_version in '3.4, 3.5, 3.6'", "python_version >= '3.4'"]


@flaky
@pytest.mark.project
def test_environment_variable_value_does_not_change_hash(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
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
