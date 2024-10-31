import os
import shutil
import sys

import pytest

from pipenv.utils.shell import temp_environ
from pipenv.vendor.packaging import version


@pytest.mark.extras
@pytest.mark.install
@pytest.mark.local
def test_local_path_issue_6016(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
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
        # project.write_toml({"packages": pipfile, "dev-packages": {}})
        c = p.pipenv("install .")
        assert c.returncode == 0
        assert "testpipenv" in p.lockfile["default"]


@pytest.mark.extras
@pytest.mark.install
@pytest.mark.local
def test_local_extras_install(pipenv_instance_pypi):
    """Ensure -e .[extras] installs."""
    with pipenv_instance_pypi() as p:
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
        with open(os.path.join(p.path, "Pipfile"), "w") as fh:
            fh.write(
                """
[packages]
testpipenv = {path = ".", editable = true, extras = ["dev"]}

[dev-packages]
            """.strip()
            )
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
        assert p.pipfile["packages"]["testpipenv"]["file"] == "."
        assert p.pipfile["packages"]["testpipenv"]["extras"] == ["dev"]
        assert "six" in p.lockfile["default"]


@pytest.mark.extras
@pytest.mark.install
@pytest.mark.local
def test_local_extras_install_alternate(pipenv_instance_pypi):
    """Ensure local package with extras installs correctly using pyproject.toml."""
    with pipenv_instance_pypi() as p:
        # Create pyproject.toml
        pyproject_toml = os.path.join(p.path, "pyproject.toml")
        with open(pyproject_toml, "w") as fh:
            contents = """
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "testpipenv"
version = "0.1"
description = "Pipenv Test Package"
authors = [{name = "Pipenv Test", email = "test@pipenv.package"}]
requires-python = ">=3.8"

[project.optional-dependencies]
dev = ["six"]
            """.strip()
            fh.write(contents)

        # Create basic package structure
        pkg_dir = os.path.join(p.path, "testpipenv")
        os.makedirs(pkg_dir)
        with open(os.path.join(pkg_dir, "__init__.py"), "w") as fh:
            fh.write("")

        # Test with both Pipfile syntax and direct install
        for install_method in ["pipfile", "direct"]:
            if install_method == "pipfile":
                with open(os.path.join(p.path, "Pipfile"), "w") as fh:
                    fh.write("""
[packages]
testpipenv = {path = ".", editable = true, extras = ["dev"]}

[dev-packages]
                    """.strip())
                c = p.pipenv("install")
            else:
                p.lockfile_path.unlink()
                c = p.pipenv("install -e .[dev]")

            assert c.returncode == 0
            assert "testpipenv" in p.lockfile["default"]
            assert p.lockfile["default"]["testpipenv"]["extras"] == ["dev"]
            assert "six" in p.lockfile["default"]

            if install_method == "pipfile":
                assert p.pipfile["packages"]["testpipenv"]["extras"] == ["dev"]

            c = p.pipenv("uninstall --all")
            assert c.returncode == 0

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
            contents = f"""
from setuptools import setup

setup(
    name='testdeplinks',
    version='0.1',
    packages=[],
    install_requires=[
        '{deplink}'
    ],
)
            """.strip()
            fh.write(contents)

    @staticmethod
    def helper_dependency_links_install_test(pipenv_instance, deplink):
        TestDirectDependencies.helper_dependency_links_install_make_setup(
            pipenv_instance, deplink
        )
        c = pipenv_instance.pipenv("install -v -e .")
        assert c.returncode == 0
        assert "six" in pipenv_instance.lockfile["default"]

    @pytest.mark.skip(
        reason="This test modifies os.environment which has side effects on other tests"
    )
    def test_https_dependency_links_install(self, pipenv_instance_pypi):
        """Ensure dependency_links are parsed and installed (needed for private repo dependencies)."""
        with temp_environ(), pipenv_instance_pypi() as p:
            os.environ["PIP_NO_BUILD_ISOLATION"] = "1"
            TestDirectDependencies.helper_dependency_links_install_test(
                p, "six@ git+https://github.com/benjaminp/six@1.11.0"
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
        assert "Requests" not in p.pipfile["packages"]
        assert "requests" in p.pipfile["packages"]
        assert p.pipfile["packages"]["requests"] == "==2.18.4"
        c = p.pipenv("install python_DateUtil")
        assert c.returncode == 0
        assert "python-dateutil" in p.pipfile["packages"]
        with open(p.pipfile_path) as f:
            contents = f.read()
            assert "# Pre comment" in contents


@pytest.mark.eggs
@pytest.mark.files
@pytest.mark.local
@pytest.mark.resolver
@pytest.mark.skip  # extracting this package may be where its causing the pip_to_deps failures
def test_local_package(pipenv_instance_private_pypi, testsroot):
    """This test ensures that local packages (directories with a setup.py)
    installed in editable mode have their dependencies resolved as well"""
    file_name = "requests-2.19.1.tar.gz"
    package = "requests-2.19.1"
    # Not sure where travis/appveyor run tests from
    source_path = os.path.abspath(os.path.join(testsroot, "test_artifacts", file_name))
    with pipenv_instance_private_pypi() as p:
        # This tests for a bug when installing a zipfile in the current dir
        copy_to = os.path.join(p.path, file_name)
        shutil.copy(source_path, copy_to)
        import tarfile

        with tarfile.open(copy_to, "r:gz") as tgz:

            def is_within_directory(directory, target):
                abs_directory = os.path.abspath(directory)
                abs_target = os.path.abspath(target)

                prefix = os.path.commonprefix([abs_directory, abs_target])

                return prefix == abs_directory

            def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
                for member in tar.getmembers():
                    member_path = os.path.join(path, member.name)
                    if not is_within_directory(path, member_path):
                        raise Exception("Attempted Path Traversal in Tar File")

                tar.extractall(path, members, numeric_owner)

            safe_extract(tgz, path=p.path)
        c = p.pipenv(f"install -e {package}")
        assert c.returncode == 0
        assert all(
            pkg in p.lockfile["default"]
            for pkg in ["urllib3", "idna", "certifi", "chardet"]
        )


@pytest.mark.files
@pytest.mark.local
def test_local_tar_gz_file(pipenv_instance_private_pypi, testsroot):
    file_name = "requests-2.19.1.tar.gz"

    with pipenv_instance_private_pypi() as p:
        requests_path = p._pipfile.get_fixture_path(f"{file_name}")

        # This tests for a bug when installing a zipfile
        c = p.pipenv(f"install {requests_path}")
        assert c.returncode == 0
        key = list(p.pipfile["packages"])[0]
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
        os.makedirs(artifact_path, exist_ok=True)
        shutil.copy(source_path, os.path.join(artifact_path, file_name))
        with open(p.pipfile_path, "w") as f:
            contents = f"""
# Pre comment
[packages]
six = {{path = "./artifacts/{file_name}"}}
            """
            f.write(contents.strip())
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "six" in p.lockfile["default"]


@pytest.mark.run
@pytest.mark.files
@pytest.mark.install
def test_multiple_editable_packages_should_not_race(
    pipenv_instance_private_pypi, testsroot
):
    """Test for a race condition that can occur when installing multiple 'editable' packages at
    once, and which causes some of them to not be importable.

    This issue had been fixed for VCS packages already, but not local 'editable' packages.

    So this test locally installs packages from tarballs that have already been committed in
    the local `pypi` dir to avoid using VCS packages.
    """
    pkgs = ["six", "jinja2"]

    with pipenv_instance_private_pypi() as p:
        pipfile_string = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = false
name = "testindex"

[dev-packages]

[packages]
        """

        for pkg_name in pkgs:
            source_path = p._pipfile.get_fixture_path(f"git/{pkg_name}/")
            shutil.copytree(source_path, pkg_name)

            pipfile_string += (
                f'"{pkg_name}" = {{path = "./{pkg_name}", editable = true}}\n'
            )

        with open(p.pipfile_path, "w") as f:
            f.write(pipfile_string.strip())

        c = p.pipenv("install")
        assert c.returncode == 0

        c = p.pipenv('run python -c "import jinja2, six"')
        assert c.returncode == 0, c.stderr


@pytest.mark.skipif(
    os.name == "nt" and sys.version_info[:2] == (3, 8),
    reason="Seems to work on 3.8 but not via the CI",
)
@pytest.mark.outdated
def test_outdated_should_compare_postreleases_without_failing(
    pipenv_instance_private_pypi,
):
    with pipenv_instance_private_pypi() as p:
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
@pytest.mark.needs_internet
def test_install_remote_wheel_file_with_extras(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv(
            "install -v fastapi[standard]@https://files.pythonhosted.org/packages/c9/14/bbe7776356ef01f830f8085ca3ac2aea59c73727b6ffaa757abeb7d2900b/fastapi-0.115.2-py3-none-any.whl"
        )
        assert c.returncode == 0
        assert "httpx" in p.lockfile["default"]
        assert "jinja2" in p.lockfile["default"]
        assert "uvicorn" in p.lockfile["default"]


@pytest.mark.install
@pytest.mark.skip_lock
@pytest.mark.needs_internet
def test_install_skip_lock(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "{}"
verify_ssl = true
name = "pypi"
[packages]
six = {}
            """.format(
                p.index_url, '{version = "*", index = "pypi"}'
            ).strip()
            f.write(contents)
        c = p.pipenv("install --skip-lock")
        assert c.returncode == 0
        c = p.pipenv('run python -c "import six"')
        assert c.returncode == 0


@pytest.mark.install
@pytest.mark.skip_lock
def test_skip_lock_installs_correct_version(pipenv_instance_pypi):
    """Ensure --skip-lock installs the exact version specified in Pipfile."""
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
gunicorn = "==20.0.2"
            """.strip()
            f.write(contents)

        # Install with --skip-lock
        c = p.pipenv("install --skip-lock")
        assert c.returncode == 0

        # Verify installed version matches Pipfile specification
        c = p.pipenv("run pip freeze")
        assert c.returncode == 0

        # Find gunicorn in pip freeze output
        packages = [line.strip() for line in c.stdout.split("\n")]
        gunicorn_line = next(line for line in packages if line.startswith("gunicorn"))

        assert gunicorn_line == "gunicorn==20.0.2"


@pytest.mark.install
@pytest.mark.skip_lock
def test_skip_lock_respects_markers(pipenv_instance_pypi):
    """Ensure --skip-lock correctly handles packages with markers."""
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
# Use python version markers since they're platform-independent
simplejson = {version = "==3.17.2", markers = "python_version < '4'"}
urllib3 = {version = "==1.26.6", markers = "python_version < '2'"}
            """.strip()
            f.write(contents)

        # Install with --skip-lock
        c = p.pipenv("install --skip-lock")
        assert c.returncode == 0

        # Verify installed versions match markers
        c = p.pipenv("run pip freeze")
        assert c.returncode == 0
        packages = [line.strip() for line in c.stdout.split("\n")]

        # simplejson should be installed (python_version < '4' is always True for Python 3.x)
        simplejson_line = next((line for line in packages if line.startswith("simplejson")), None)
        assert simplejson_line == "simplejson==3.17.2"

        # urllib3 should not be installed (python_version < '2' is always False for Python 3.x)
        urllib3_line = next((line for line in packages if line.startswith("urllib3")), None)
        assert urllib3_line is None


@pytest.mark.install
def test_no_duplicate_source_on_install(pipenv_instance_private_pypi):
    """Ensure that running pipenv install with an index URL doesn't create duplicate [[source]] sections."""
    with pipenv_instance_private_pypi() as p:
        # Create initial Pipfile with a source
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
            """.strip()
            f.write(contents)

        # Install a package with a custom index
        c = p.pipenv(f"install six --index {p.index_url}")
        assert c.returncode == 0

        # Read the Pipfile content
        with open(p.pipfile_path) as f:
            pipfile_content = f.read()

        # Count occurrences of [[source]] in the Pipfile
        source_count = pipfile_content.count("[[source]]")

        # Assertions
        assert source_count == 2, "Expected exactly two [[source]] sections"
        assert "six" in p.pipfile["packages"]
        assert p.pipfile["packages"]["six"].get("index") is not None

        # Install another package with the same custom index
        c = p.pipenv(f"install requests --index {p.index_url}")
        assert c.returncode == 0

        # Read the updated Pipfile content
        with open(p.pipfile_path) as f:
            updated_pipfile_content = f.read()

        # Count occurrences of [[source]] in the updated Pipfile
        updated_source_count = updated_pipfile_content.count("[[source]]")

        # Verify no additional source sections were added
        assert updated_source_count == source_count, "No new [[source]] sections should be added"
        assert "requests" in p.pipfile["packages"]
        assert p.pipfile["packages"]["requests"].get("index") is not None


@pytest.mark.basic
@pytest.mark.install
def test_install_dev_with_skip_lock(pipenv_instance_pypi):
    """Test aws-cdk-lib installation and version verification."""
    with pipenv_instance_pypi() as p:
        # Create the Pipfile with specified contents
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
aws-cdk-lib = "==2.164.1"

[dev-packages]
pytest = "*"
            """.strip()
            f.write(contents)

        # Install dependencies with --skip-lock
        c = p.pipenv("install --dev --skip-lock")
        assert c.returncode == 0

        # Check pip freeze output
        c = p.pipenv("run pip freeze")
        assert c.returncode == 0
        freeze_output = c.stdout.strip()

        # Find aws-cdk-lib in pip freeze output and verify version
        for line in freeze_output.split('\n'):
            if line.startswith('aws-cdk-lib=='):
                installed_version = line.split('==')[1]
                assert version.parse(installed_version) == version.parse("2.164.1"), \
                    f"aws-cdk-lib version {installed_version} is to be expected 2.164.1"
                break
        else:
            # This will execute if we don't find aws-cdk-lib in the output
            raise AssertionError("aws-cdk-lib not found in pip freeze output")

