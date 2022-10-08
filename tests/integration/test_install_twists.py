import os
import shutil
import sys
from pathlib import Path

import pytest

from pipenv.utils.shell import mkdir_p, temp_environ


@pytest.mark.extras
@pytest.mark.install
@pytest.mark.local
def test_local_extras_install(pipenv_instance_pypi):
    """Ensure -e .[extras] installs.
    """
    with pipenv_instance_pypi(chdir=True) as p:
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
        assert c.returncode == 0
        assert "testpipenv" in p.lockfile["default"]
        assert p.lockfile["default"]["testpipenv"]["extras"] == ["dev"]
        assert "six" in p.lockfile["default"]
        c = p.pipenv("uninstall --all")
        assert c.returncode == 0
        print(f"Current directory: {os.getcwd()}", file=sys.stderr)
        c = p.pipenv(f"install {line}")
        assert c.returncode == 0
        assert "testpipenv" in p.pipfile["packages"]
        assert p.pipfile["packages"]["testpipenv"]["path"] == "."
        assert p.pipfile["packages"]["testpipenv"]["extras"] == ["dev"]
        assert "six" in p.lockfile["default"]


@pytest.mark.local
@pytest.mark.install
@pytest.mark.needs_internet
class TestDirectDependencies:
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
        assert c.returncode == 0
        assert "six" in pipenv_instance.lockfile["default"]

    def test_https_dependency_links_install(self, pipenv_instance_pypi):
        """Ensure dependency_links are parsed and installed (needed for private repo dependencies).
        """
        with temp_environ(), pipenv_instance_pypi(chdir=True) as p:
            os.environ["PIP_NO_BUILD_ISOLATION"] = '1'
            TestDirectDependencies.helper_dependency_links_install_test(
                p,
                'six@ git+https://github.com/benjaminp/six@1.11.0'
            )


@pytest.mark.run
@pytest.mark.install
def test_normalize_name_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
# Pre comment
[packages]
Requests = "==2.14.0"   # Inline comment
"""
            f.write(contents)

        assert p.pipfile["packages"]["Requests"] == "==2.14.0"
        c = p.pipenv("install requests==2.18.4")
        assert c.returncode == 0
        assert p.pipfile["packages"]["Requests"] == "==2.18.4"
        c = p.pipenv("install python_DateUtil")
        assert c.returncode == 0
        assert "python-dateutil" in p.pipfile["packages"]
        with open(p.pipfile_path) as f:
            contents = f.read()
            assert "# Pre comment" in contents
            assert "# Inline comment" in contents


@pytest.mark.eggs
@pytest.mark.files
@pytest.mark.local
@pytest.mark.resolver
@pytest.mark.skip  # extracting this package may be where its causing the pip_to_deps failures
def test_local_package(pipenv_instance_private_pypi, pip_src_dir, testsroot):
    """This test ensures that local packages (directories with a setup.py)
    installed in editable mode have their dependencies resolved as well"""
    file_name = "requests-2.19.1.tar.gz"
    package = "requests-2.19.1"
    # Not sure where travis/appveyor run tests from
    source_path = os.path.abspath(os.path.join(testsroot, "test_artifacts", file_name))
    with pipenv_instance_private_pypi(chdir=True) as p:
        # This tests for a bug when installing a zipfile in the current dir
        copy_to = os.path.join(p.path, file_name)
        shutil.copy(source_path, copy_to)
        import tarfile

        with tarfile.open(copy_to, "r:gz") as tgz:
            tgz.extractall(path=p.path)
        c = p.pipenv(f"install -e {package}")
        assert c.returncode == 0
        assert all(
            pkg in p.lockfile["default"]
            for pkg in ["urllib3", "idna", "certifi", "chardet"]
        )


@pytest.mark.files
@pytest.mark.local
def test_local_zip_file(pipenv_instance_private_pypi, testsroot):
    file_name = "requests-2.19.1.tar.gz"

    with pipenv_instance_private_pypi(chdir=True) as p:
        requests_path = p._pipfile.get_fixture_path(f"{file_name}").as_posix()

        # This tests for a bug when installing a zipfile
        c = p.pipenv(f"install {requests_path}")
        assert c.returncode == 0
        key = [k for k in p.pipfile["packages"].keys()][0]
        dep = p.pipfile["packages"][key]

        assert "file" in dep or "path" in dep
        assert c.returncode == 0

        # This now gets resolved to its name correctly
        dep = p.lockfile["default"]["requests"]

        assert "file" in dep or "path" in dep


@pytest.mark.urls
@pytest.mark.install
def test_install_local_uri_special_character(pipenv_instance_private_pypi, testsroot):
    file_name = "six-1.11.0+mkl-py2.py3-none-any.whl"
    source_path = os.path.abspath(os.path.join(testsroot, "test_artifacts", file_name))
    with pipenv_instance_private_pypi() as p:
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
        assert c.returncode == 0
        assert "six" in p.lockfile["default"]


@pytest.mark.run
@pytest.mark.files
@pytest.mark.install
def test_multiple_editable_packages_should_not_race(pipenv_instance_private_pypi, testsroot):
    """Test for a race condition that can occur when installing multiple 'editable' packages at
    once, and which causes some of them to not be importable.

    This issue had been fixed for VCS packages already, but not local 'editable' packages.

    So this test locally installs packages from tarballs that have already been committed in
    the local `pypi` dir to avoid using VCS packages.
    """
    pkgs = ["six", "jinja2"]

    pipfile_string = """
[dev-packages]

[packages]
"""

    with pipenv_instance_private_pypi(chdir=True) as p:
        for pkg_name in pkgs:
            source_path = p._pipfile.get_fixture_path(f"git/{pkg_name}/").as_posix()
            shutil.copytree(source_path, pkg_name)

            pipfile_string += '"{0}" = {{path = "./{0}", editable = true}}\n'.format(pkg_name)

        with open(p.pipfile_path, 'w') as f:
            f.write(pipfile_string.strip())

        c = p.pipenv('install')
        assert c.returncode == 0

        c = p.pipenv('run python -c "import jinja2, six"')
        assert c.returncode == 0, c.stderr


@pytest.mark.outdated
def test_outdated_should_compare_postreleases_without_failing(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi(chdir=True) as p:
        c = p.pipenv("install ibm-db-sa-py3==0.3.0")
        assert c.returncode == 0
        c = p.pipenv("update --outdated")
        assert c.returncode == 0
        assert "Skipped Update" in c.stderr
        p._pipfile.update("ibm-db-sa-py3", "*")
        c = p.pipenv("update --outdated")
        assert c.returncode != 0
        assert "out-of-date" in c.stdout


@pytest.mark.install
@pytest.mark.skip_lock
@pytest.mark.needs_internet
def test_install_skip_lock(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "{0}"
verify_ssl = true
name = "pypi"

[packages]
six = {1}
            """.format(os.environ['PIPENV_TEST_INDEX'], '{version = "*", index = "pypi"}').strip()
            f.write(contents)
        c = p.pipenv('install --skip-lock')
        assert c.returncode == 0
        c = p.pipenv('run python -c "import six"')
        assert c.returncode == 0
