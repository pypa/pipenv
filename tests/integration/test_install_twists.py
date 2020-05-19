# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import os
import shutil
import sys

import pytest

from flaky import flaky

from pipenv._compat import Path
from pipenv.utils import mkdir_p, temp_environ
from pipenv.vendor import delegator


@pytest.mark.extras
@pytest.mark.install
@pytest.mark.local
def test_local_extras_install(PipenvInstance):
    """Ensure -e .[extras] installs.
    """
    with PipenvInstance(chdir=True) as p:
        setup_py = os.path.join(p.path, "setup.py")
        with open(setup_py, "w") as fh:
            contents = """
from setuptools import setup, find_packages
setup(
    name='testpipenv',
    version='0.1',
    description='Pipenv Test Package',
    author='Pipenv Test',
    author_email='test@pipenv.package',
    license='MIT',
    packages=find_packages(),
    install_requires=[],
    extras_require={'dev': ['six']},
    zip_safe=False
)
            """.strip()
            fh.write(contents)
        line = "-e .[dev]"
        with open(os.path.join(p.path, 'Pipfile'), 'w') as fh:
            fh.write("""
[packages]
testpipenv = {path = ".", editable = true, extras = ["dev"]}

[dev-packages]
            """.strip())
        # project.write_toml({"packages": pipfile, "dev-packages": {}})
        c = p.pipenv("install")
        assert c.return_code == 0
        assert "testpipenv" in p.lockfile["default"]
        assert p.lockfile["default"]["testpipenv"]["extras"] == ["dev"]
        assert "six" in p.lockfile["default"]
        c = p.pipenv("uninstall --all")
        assert c.return_code == 0
        print("Current directory: {0}".format(os.getcwd()), file=sys.stderr)
        c = p.pipenv("install {0}".format(line))
        assert c.return_code == 0
        assert "testpipenv" in p.pipfile["packages"]
        assert p.pipfile["packages"]["testpipenv"]["path"] == "."
        assert p.pipfile["packages"]["testpipenv"]["extras"] == ["dev"]
        assert "six" in p.lockfile["default"]


@pytest.mark.local
@pytest.mark.install
@pytest.mark.needs_internet
@flaky
class TestDirectDependencies(object):
    """Ensure dependency_links are parsed and installed.

    This is needed for private repo dependencies.
    """

    @staticmethod
    def helper_dependency_links_install_make_setup(pipenv_instance, deplink):
        setup_py = os.path.join(pipenv_instance.path, "setup.py")
        with open(setup_py, "w") as fh:
            contents = """
from setuptools import setup

setup(
    name='testdeplinks',
    version='0.1',
    packages=[],
    install_requires=[
        '{0}'
    ],
)
            """.strip().format(deplink)
            fh.write(contents)

    @staticmethod
    def helper_dependency_links_install_test(pipenv_instance, deplink):
        TestDirectDependencies.helper_dependency_links_install_make_setup(pipenv_instance, deplink)
        c = pipenv_instance.pipenv("install -v -e .")
        assert c.return_code == 0
        assert "test-private-dependency" in pipenv_instance.lockfile["default"]

    def test_https_dependency_links_install(self, PipenvInstance):
        """Ensure dependency_links are parsed and installed (needed for private repo dependencies).
        """
        with temp_environ(), PipenvInstance(chdir=True) as p:
            os.environ["PIP_NO_BUILD_ISOLATION"] = '1'
            TestDirectDependencies.helper_dependency_links_install_test(
                p,
                'test-private-dependency@ git+https://github.com/atzannes/test-private-dependency@v0.1'
            )

    @pytest.mark.needs_github_ssh
    def test_ssh_dependency_links_install(self, PipenvInstance):
        with temp_environ(), PipenvInstance(chdir=True) as p:
            os.environ['PIP_PROCESS_DEPENDENCY_LINKS'] = '1'
            os.environ["PIP_NO_BUILD_ISOLATION"] = '1'
            TestDirectDependencies.helper_dependency_links_install_test(
                p,
                'test-private-dependency@ git+ssh://git@github.com/atzannes/test-private-dependency@v0.1'
            )


@pytest.mark.e
@pytest.mark.local
@pytest.mark.install
@pytest.mark.skip(reason="this doesn't work on windows")
def test_e_dot(PipenvInstance, pip_src_dir):
    with PipenvInstance() as p:
        path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        c = p.pipenv("install -e '{0}' --dev".format(path))

        assert c.return_code == 0

        key = [k for k in p.pipfile["dev-packages"].keys()][0]
        assert "path" in p.pipfile["dev-packages"][key]
        assert "requests" in p.lockfile["develop"]

@pytest.mark.install
@pytest.mark.multiprocessing
@flaky
def test_multiprocess_bug_and_install(PipenvInstance):
    with temp_environ():
        os.environ["PIPENV_MAX_SUBPROCESS"] = "2"

        with PipenvInstance(chdir=True) as p:
            with open(p.pipfile_path, "w") as f:
                contents = """
[packages]
pytz = "*"
six = "*"
urllib3 = "*"
                """.strip()
                f.write(contents)

            c = p.pipenv("install")
            assert c.return_code == 0

            assert "pytz" in p.lockfile["default"]
            assert "six" in p.lockfile["default"]
            assert "urllib3" in p.lockfile["default"]

            c = p.pipenv('run python -c "import six; import pytz; import urllib3;"')
            assert c.return_code == 0


@pytest.mark.install
@pytest.mark.sequential
@flaky
def test_sequential_mode(PipenvInstance):

    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "*"
urllib3 = "*"
pytz = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv("install --sequential")
        assert c.return_code == 0

        assert "six" in p.lockfile["default"]
        assert "pytz" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]

        c = p.pipenv('run python -c "import six; import urllib3; import pytz;"')
        assert c.return_code == 0


@pytest.mark.run
@pytest.mark.install
def test_normalize_name_install(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
# Pre comment
[packages]
Requests = "==2.14.0"   # Inline comment
"""
            f.write(contents)

        c = p.pipenv("install")
        assert c.return_code == 0

        c = p.pipenv("install requests")
        assert c.return_code == 0
        assert "requests" not in p.pipfile["packages"]
        assert p.pipfile["packages"]["Requests"] == "==2.14.0"
        c = p.pipenv("install requests==2.18.4")
        assert c.return_code == 0
        assert p.pipfile["packages"]["Requests"] == "==2.18.4"
        c = p.pipenv("install python_DateUtil")
        assert c.return_code == 0
        assert "python-dateutil" in p.pipfile["packages"]
        with open(p.pipfile_path) as f:
            contents = f.read()
            assert "# Pre comment" in contents
            assert "# Inline comment" in contents


@flaky
@pytest.mark.eggs
@pytest.mark.files
@pytest.mark.local
@pytest.mark.resolver
def test_local_package(PipenvInstance, pip_src_dir, testsroot):
    """This test ensures that local packages (directories with a setup.py)
    installed in editable mode have their dependencies resolved as well"""
    file_name = "requests-2.19.1.tar.gz"
    package = "requests-2.19.1"
    # Not sure where travis/appveyor run tests from
    source_path = os.path.abspath(os.path.join(testsroot, "test_artifacts", file_name))
    with PipenvInstance(chdir=True) as p:
        # This tests for a bug when installing a zipfile in the current dir
        copy_to = os.path.join(p.path, file_name)
        shutil.copy(source_path, copy_to)
        import tarfile

        with tarfile.open(copy_to, "r:gz") as tgz:
            tgz.extractall(path=p.path)
        c = p.pipenv("install -e {0}".format(package))
        assert c.return_code == 0
        assert all(
            pkg in p.lockfile["default"]
            for pkg in ["urllib3", "idna", "certifi", "chardet"]
        )


@pytest.mark.files
@pytest.mark.local
@flaky
def test_local_zipfiles(PipenvInstance, testsroot):
    file_name = "requests-2.19.1.tar.gz"
    # Not sure where travis/appveyor run tests from
    source_path = os.path.abspath(os.path.join(testsroot, "test_artifacts", file_name))

    with PipenvInstance(chdir=True) as p:
        # This tests for a bug when installing a zipfile in the current dir
        shutil.copy(source_path, os.path.join(p.path, file_name))

        c = p.pipenv("install {}".format(file_name))
        assert c.return_code == 0
        key = [k for k in p.pipfile["packages"].keys()][0]
        dep = p.pipfile["packages"][key]

        assert "file" in dep or "path" in dep
        assert c.return_code == 0

        # This now gets resolved to its name correctly
        dep = p.lockfile["default"]["requests"]

        assert "file" in dep or "path" in dep


@pytest.mark.local
@pytest.mark.files
@flaky
def test_relative_paths(PipenvInstance, testsroot):
    file_name = "requests-2.19.1.tar.gz"
    source_path = os.path.abspath(os.path.join(testsroot, "test_artifacts", file_name))

    with PipenvInstance() as p:
        artifact_dir = "artifacts"
        artifact_path = os.path.join(p.path, artifact_dir)
        mkdir_p(artifact_path)
        shutil.copy(source_path, os.path.join(artifact_path, file_name))
        # Test installing a relative path in a subdirectory
        c = p.pipenv("install {}/{}".format(artifact_dir, file_name))
        assert c.return_code == 0
        key = next(k for k in p.pipfile["packages"].keys())
        dep = p.pipfile["packages"][key]

        assert "path" in dep
        assert Path(".", artifact_dir, file_name) == Path(dep["path"])
        assert c.return_code == 0


@pytest.mark.install
@pytest.mark.local
@pytest.mark.local_file
@flaky
def test_install_local_file_collision(PipenvInstance):
    with PipenvInstance() as p:
        target_package = "alembic"
        fake_file = os.path.join(p.path, target_package)
        with open(fake_file, "w") as f:
            f.write("")
        c = p.pipenv("install {}".format(target_package))
        assert c.return_code == 0
        assert target_package in p.pipfile["packages"]
        assert p.pipfile["packages"][target_package] == "*"
        assert target_package in p.lockfile["default"]


@pytest.mark.urls
@pytest.mark.install
def test_install_local_uri_special_character(PipenvInstance, testsroot):
    file_name = "six-1.11.0+mkl-py2.py3-none-any.whl"
    source_path = os.path.abspath(os.path.join(testsroot, "test_artifacts", file_name))
    with PipenvInstance() as p:
        artifact_dir = "artifacts"
        artifact_path = os.path.join(p.path, artifact_dir)
        mkdir_p(artifact_path)
        shutil.copy(source_path, os.path.join(artifact_path, file_name))
        with open(p.pipfile_path, "w") as f:
            contents = """
# Pre comment
[packages]
six = {{path = "./artifacts/{}"}}
            """.format(
                file_name
            )
            f.write(contents.strip())
        c = p.pipenv("install")
        assert c.return_code == 0
        assert "six" in p.lockfile["default"]


@pytest.mark.run
@pytest.mark.files
@pytest.mark.install
def test_multiple_editable_packages_should_not_race(PipenvInstance, testsroot):
    """Test for a race condition that can occur when installing multiple 'editable' packages at
    once, and which causes some of them to not be importable.

    This issue had been fixed for VCS packages already, but not local 'editable' packages.

    So this test locally installs packages from tarballs that have already been committed in
    the local `pypi` dir to avoid using VCS packages.
    """
    pkgs = ["requests", "flask", "six", "jinja2"]

    pipfile_string = """
[dev-packages]

[packages]
"""

    with PipenvInstance(chdir=True) as p:
        for pkg_name in pkgs:
            source_path = p._pipfile.get_fixture_path("git/{0}/".format(pkg_name)).as_posix()
            c = delegator.run("git clone {0} ./{1}".format(source_path, pkg_name))
            assert c.return_code == 0

            pipfile_string += '"{0}" = {{path = "./{0}", editable = true}}\n'.format(pkg_name)

        with open(p.pipfile_path, 'w') as f:
            f.write(pipfile_string.strip())

        c = p.pipenv('install')
        assert c.return_code == 0

        c = p.pipenv('run python -c "import requests, flask, six, jinja2"')
        assert c.return_code == 0, c.err


@pytest.mark.outdated
@pytest.mark.py3_only
def test_outdated_should_compare_postreleases_without_failing(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install ibm-db-sa-py3==0.3.0")
        assert c.return_code == 0
        c = p.pipenv("update --outdated")
        assert c.return_code == 0
        assert "Skipped Update" in c.err
        p._pipfile.update("ibm-db-sa-py3", "*")
        c = p.pipenv("update --outdated")
        assert c.return_code != 0
        assert "out-of-date" in c.out
