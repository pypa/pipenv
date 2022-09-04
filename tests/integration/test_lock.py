import json
import os
import sys
from pathlib import Path

import pytest

import pytest_pypi.app
from flaky import flaky
from pipenv.vendor.vistir.misc import to_text
from pipenv.utils.shell import temp_environ


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_handle_eggs(PipenvInstance_NoPyPI):
    """Ensure locking works with packages providing egg formats.
    """
    with PipenvInstance_NoPyPI() as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
RandomWords = "*"
            """)
        c = p.pipenv('lock --verbose')
        assert c.returncode == 0
        assert 'randomwords' in p.lockfile['default']
        assert p.lockfile['default']['randomwords']['version'] == '==0.2.1'


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_requirements_file(PipenvInstance_NoPyPI):

    with PipenvInstance_NoPyPI() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = "==2.14.0"
[dev-packages]
flask = "==0.12.2"
            """.strip()
            f.write(contents)

        req_list = ("requests==2.14.0",)

        dev_req_list = ("flask==0.12.2",)

        c = p.pipenv('lock')
        assert c.returncode == 0

        default = p.pipenv('requirements')
        assert default.returncode == 0
        dev = p.pipenv('requirements --dev-only')

        for req in req_list:
            assert req in default.stdout

        for req in dev_req_list:
            assert req in dev.stdout


@pytest.mark.lock
def test_lock_includes_hashes_for_all_platforms(PipenvInstance_NoPyPI):
    """ Locking should include hashes for *all* platforms, not just the
    platform we're running lock on. """

    releases = pytest_pypi.app.packages['yarl'].releases
    def get_hash(release_name):
        # Convert a specific filename to a hash like what would show up in a Pipfile.lock.
        # For example:
        # 'yarl-1.3.0-cp35-cp35m-manylinux1_x86_64.whl' -> 'sha256:3890ab952d508523ef4881457c4099056546593fa05e93da84c7250516e632eb'
        return f"sha256:{releases[release_name].hash}"

    with PipenvInstance_NoPyPI() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
yarl = "==1.3.0"
            """.strip()
            f.write(contents)

        c = p.pipenv('lock')
        assert c.returncode == 0

        lock = p.lockfile
        assert 'yarl' in lock['default']
        assert set(lock['default']['yarl']['hashes']) == {
            get_hash('yarl-1.3.0-cp35-cp35m-manylinux1_x86_64.whl'),
            get_hash('yarl-1.3.0-cp35-cp35m-win_amd64.whl'),
            get_hash('yarl-1.3.0-cp36-cp36m-manylinux1_x86_64.whl'),
            get_hash('yarl-1.3.0-cp36-cp36m-win_amd64.whl'),
            get_hash('yarl-1.3.0-cp37-cp37m-win_amd64.whl'),
            get_hash('yarl-1.3.0.tar.gz'),
        }


@pytest.mark.lock
@pytest.mark.keep_outdated
def test_lock_keep_outdated(PipenvInstance):

    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = {version = "==2.14.0"}
pytest = "==3.1.0"
            """.strip()
            f.write(contents)

        c = p.pipenv('lock')
        assert c.returncode == 0
        lock = p.lockfile
        assert 'requests' in lock['default']
        assert lock['default']['requests']['version'] == "==2.14.0"
        assert 'pytest' in lock['default']
        assert lock['default']['pytest']['version'] == "==3.1.0"

        with open(p.pipfile_path, 'w') as f:
            updated_contents = """
[packages]
requests = {version = "==2.18.4"}
pytest = "*"
            """.strip()
            f.write(updated_contents)

        c = p.pipenv('lock --keep-outdated')
        assert c.returncode == 0
        lock = p.lockfile
        assert 'requests' in lock['default']
        assert lock['default']['requests']['version'] == "==2.18.4"
        assert 'pytest' in lock['default']
        assert lock['default']['pytest']['version'] == "==3.1.0"


@pytest.mark.lock
@pytest.mark.keep_outdated
def test_keep_outdated_doesnt_remove_lockfile_entries(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p._pipfile.add("requests", "==2.18.4")
        p._pipfile.add("colorama", {"version": "*", "markers": "os_name=='FakeOS'"})
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "doesn't match your environment, its dependencies won't be resolved." in c.stderr
        p._pipfile.add("six", "*")
        p.pipenv("lock --keep-outdated")
        assert "colorama" in p.lockfile["default"]
        assert p.lockfile["default"]["colorama"]["markers"] == "os_name == 'FakeOS'"


@pytest.mark.lock
def test_resolve_skip_unmatched_requirements(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p._pipfile.add("missing-package", {"markers": "os_name=='FakeOS'"})
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert (
            "Could not find a version of missing-package; "
            "os_name == 'FakeOS' that matches your environment"
        ) in c.stderr


@pytest.mark.lock
@pytest.mark.keep_outdated
def test_keep_outdated_doesnt_upgrade_pipfile_pins(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p._pipfile.add("urllib3", "==1.21.1")
        c = p.pipenv("install")
        assert c.returncode == 0
        p._pipfile.add("requests", "==2.18.4")
        c = p.pipenv("lock --keep-outdated")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert p.lockfile["default"]["requests"]["version"] == "==2.18.4"
        assert p.lockfile["default"]["urllib3"]["version"] == "==1.21.1"


@pytest.mark.lock
def test_keep_outdated_keeps_markers_not_removed(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install six click")
        assert c.returncode == 0
        lockfile = Path(p.lockfile_path)
        lockfile_content = lockfile.read_text()
        lockfile_json = json.loads(lockfile_content)
        assert "six" in lockfile_json["default"]
        lockfile_json["default"]["six"]["markers"] = "python_version >= '2.7'"
        lockfile.write_text(to_text(json.dumps(lockfile_json)))
        c = p.pipenv("lock --keep-outdated")
        assert c.returncode == 0
        assert p.lockfile["default"]["six"].get("markers", "") == "python_version >= '2.7'"


@pytest.mark.lock
@pytest.mark.keep_outdated
def test_keep_outdated_doesnt_update_satisfied_constraints(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p._pipfile.add("requests", "==2.18.4")
        c = p.pipenv("install")
        assert c.returncode == 0
        p._pipfile.add("requests", "*")
        assert p.pipfile["packages"]["requests"] == "*"
        c = p.pipenv("lock --keep-outdated")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        # ensure this didn't update requests
        assert p.lockfile["default"]["requests"]["version"] == "==2.18.4"
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert p.lockfile["default"]["requests"]["version"] != "==2.18.4"


@pytest.mark.lock
@pytest.mark.complex
@pytest.mark.needs_internet
def test_complex_lock_with_vcs_deps(local_tempdir, PipenvInstance, pip_src_dir):
    # This uses the real PyPI since we need Internet to access the Git
    # dependency anyway.
    with PipenvInstance() as p, local_tempdir:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        dateutil_uri = p._pipfile.get_fixture_path("git/dateutil").as_uri()
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
click = "==6.7"

[dev-packages]
requests = {git = "%s"}
            """.strip() % requests_uri
            f.write(contents)

        c = p.pipenv('install')
        assert c.returncode == 0
        lock = p.lockfile
        assert 'requests' in lock['develop']
        assert 'click' in lock['default']

        c = p.pipenv(f'run pip install -e git+{dateutil_uri}#egg=python_dateutil')
        assert c.returncode == 0

        c = p.pipenv('lock')
        assert c.returncode == 0
        lock = p.lockfile
        assert 'requests' in lock['develop']
        assert 'click' in lock['default']
        assert 'python_dateutil' not in lock['default']
        assert 'python_dateutil' not in lock['develop']


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_with_prereleases(PipenvInstance):

    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
sqlalchemy = "==1.2.0b3"

[pipenv]
allow_prereleases = true
            """.strip()
            f.write(contents)

        c = p.pipenv('lock')
        assert c.returncode == 0
        assert p.lockfile['default']['sqlalchemy']['version'] == '==1.2.0b3'


@pytest.mark.lock
@pytest.mark.maya
@pytest.mark.complex
@pytest.mark.needs_internet
@flaky
def test_complex_deps_lock_and_install_properly(PipenvInstance, pip_src_dir):
    # This uses the real PyPI because Maya has too many dependencies...
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
maya = "*"
            """.strip()
            f.write(contents)

            c = p.pipenv('lock --verbose')
            assert c.returncode == 0

            c = p.pipenv('install')
            assert c.returncode == 0


@pytest.mark.lock
@pytest.mark.extras
def test_lock_extras_without_install(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = {version = "*", extras = ["socks"]}
            """.strip()
            f.write(contents)

        c = p.pipenv('lock')
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert "pysocks" in p.lockfile["default"]
        assert "markers" not in p.lockfile["default"]['pysocks']

        c = p.pipenv('lock')
        assert c.returncode == 0
        c = p.pipenv('requirements')
        assert c.returncode == 0
        assert "extra == 'socks'" not in c.stdout.strip()


@pytest.mark.index
@pytest.mark.install  # private indexes need to be uncached for resolution
@pytest.mark.skip_lock
@pytest.mark.needs_internet
def test_private_index_skip_lock(PipenvInstance_NoPyPI):
    with PipenvInstance_NoPyPI() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://test.pypi.org/simple"
verify_ssl = true
name = "testpypi"

[packages]
pipenv-test-private-package = {version = "*", index = "testpypi"}
requests = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv('install --skip-lock')
        assert c.returncode == 0


@pytest.mark.lock
@pytest.mark.index
@pytest.mark.install  # private indexes need to be uncached for resolution
@pytest.mark.requirements
@pytest.mark.needs_internet
def test_private_index_lock_requirements(PipenvInstance_NoPyPI):
    # Don't use the local fake pypi
    with PipenvInstance_NoPyPI() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://test.pypi.org/simple"
verify_ssl = true
name = "testpypi"

[packages]
pipenv-test-private-package = {version = "*", index = "testpypi"}
requests = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv('lock')
        assert c.returncode == 0


@pytest.mark.lock
@pytest.mark.index
@pytest.mark.install  # private indexes need to be uncached for resolution
@pytest.mark.requirements
@pytest.mark.needs_internet
def test_private_index_lock_requirements(PipenvInstance):
    # Don't use the local fake pypi
    with temp_environ(), PipenvInstance(chdir=True) as p:
        # Using pypi.python.org as pipenv-test-public-package is not
        # included in the local pypi mirror
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://test.pypi.org/simple"
verify_ssl = true
name = "testpypi"

[packages]
six = {version = "*", index = "testpypi"}
pipenv-test-public-package = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv(f'install -v')
        assert c.returncode == 0


@pytest.mark.lock
@pytest.mark.install
@pytest.mark.skip_windows
@pytest.mark.skipif(sys.version_info >= (3, 9), reason="old setuptools doesn't work")
def test_outdated_setuptools_with_pep517_legacy_build_meta_is_updated(PipenvInstance_NoPyPI):
    """
    This test ensures we are using build isolation and a pep517 backend
    because the package in question includes ``pyproject.toml`` but lacks
    a ``build-backend`` declaration. In this case, ``pip`` defaults to using
    ``setuptools.build_meta:__legacy__`` as a builder, but without ``pep517``
    enabled and with ``setuptools==40.2.0`` installed, this build backend was
    not yet available. ``setuptools<40.8`` will not be aware of this backend.

    If pip is able to build in isolation with a pep517 backend, this will not
    matter and the test will still pass as pip will by default install a more
    recent version of ``setuptools``.
    """
    with PipenvInstance_NoPyPI(chdir=True) as p:
        c = p.pipenv('run pip install "setuptools<=40.2"')
        assert c.returncode == 0
        c = p.pipenv("run python -c 'import setuptools; print(setuptools.__version__)'")
        assert c.returncode == 0
        assert c.stdout.strip() == "40.2.0"
        c = p.pipenv("install legacy-backend-package")
        assert c.returncode == 0
        assert "vistir" in p.lockfile["default"]


@pytest.mark.lock
@pytest.mark.install
@pytest.mark.skip_windows
@pytest.mark.skipif(sys.version_info >= (3, 9), reason="old setuptools doesn't work")
def test_outdated_setuptools_with_pep517_cython_import_in_setuppy(PipenvInstance_NoPyPI):
    """
    This test ensures we are using build isolation and a pep517 backend
    because the package in question declares 'cython' as a build dependency
    in ``pyproject.toml``, then imports it in ``setup.py``.  The pep517
    backend will have to install it first, so this will only pass if the
    resolver is buliding with a proper backend.
    """
    with PipenvInstance_NoPyPI(chdir=True) as p:
        c = p.pipenv('run pip install "setuptools<=40.2"')
        assert c.returncode == 0
        c = p.pipenv("run python -c 'import setuptools; print(setuptools.__version__)'")
        assert c.returncode == 0
        assert c.stdout.strip() == "40.2.0"
        c = p.pipenv("install cython-import-package")
        assert c.returncode == 0
        assert "vistir" in p.lockfile["default"]


@pytest.mark.index
@pytest.mark.install
def test_lock_updated_source(PipenvInstance):

    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "{url}/${{MY_ENV_VAR}}"

[packages]
requests = "==2.14.0"
            """.strip().format(url=p.pypi)
            f.write(contents)

        with temp_environ():
            os.environ['MY_ENV_VAR'] = 'simple'
            c = p.pipenv('lock')
            assert c.returncode == 0
            assert 'requests' in p.lockfile['default']

        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "{url}/simple"

[packages]
requests = "==2.14.0"
            """.strip().format(url=p.pypi)
            f.write(contents)

        c = p.pipenv('lock')
        assert c.returncode == 0
        assert 'requests' in p.lockfile['default']


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_without_install(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "%s", editable = true}
            """.strip() % requests_uri)
        c = p.pipenv('lock')
        assert c.returncode == 0
        assert 'requests' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'certifi' in p.lockfile['default']
        c = p.pipenv('install')
        assert c.returncode == 0


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_ref_in_git(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "%s@883caaf", editable = true}
            """.strip() % requests_uri)
        c = p.pipenv('lock')
        assert c.returncode == 0
        assert p.lockfile['default']['requests']['git'] == requests_uri
        assert p.lockfile['default']['requests']['ref'] == '883caaf145fbe93bd0d208a6b864de9146087312'
        c = p.pipenv('install')
        assert c.returncode == 0


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.extras
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_extras_without_install(PipenvInstance_NoPyPI):
    with PipenvInstance_NoPyPI(chdir=True) as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "%s", editable = true, extras = ["socks"]}
            """.strip() % requests_uri)
        c = p.pipenv('lock')
        assert c.returncode == 0
        assert 'requests' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'certifi' in p.lockfile['default']
        assert "socks" in p.lockfile["default"]["requests"]["extras"]
        c = p.pipenv('install')
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        # For backward compatibility we want to make sure not to include the 'version' key
        assert "version" not in p.lockfile["default"]["requests"]


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_markers_without_install(PipenvInstance_NoPyPI):
    with PipenvInstance_NoPyPI(chdir=True) as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "%s", editable = true, markers = "python_version >= '2.6'"}
            """.strip() % requests_uri)
        c = p.pipenv('lock')
        assert c.returncode == 0
        assert 'requests' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'certifi' in p.lockfile['default']
        c = p.pipenv('install')
        assert c.returncode == 0


@pytest.mark.lock
@pytest.mark.install
def test_lockfile_corrupted(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.lockfile_path, 'w') as f:
            f.write('{corrupted}')
        c = p.pipenv('install')
        assert c.returncode == 0
        assert 'Pipfile.lock is corrupted' in c.stderr
        assert p.lockfile['_meta']


@pytest.mark.lock
@pytest.mark.install
def test_lockfile_with_empty_dict(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.lockfile_path, 'w') as f:
            f.write('{}')
        c = p.pipenv('install')
        assert c.returncode == 0
        assert 'Pipfile.lock is corrupted' in c.stderr
        assert p.lockfile['_meta']


@pytest.mark.lock
@pytest.mark.install
@pytest.mark.skip_lock
def test_lock_with_incomplete_source(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[[source]]
url = "{}"

[packages]
requests = "*"
            """.format(p.index_url))
        c = p.pipenv('install --skip-lock')
        assert c.returncode == 0
        c = p.pipenv('install')
        assert c.returncode == 0
        assert p.lockfile['_meta']['sources']


@pytest.mark.lock
@pytest.mark.install
def test_lock_no_warnings(PipenvInstance, recwarn):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install six")
        assert c.returncode == 0
        assert len(recwarn) == 0


@pytest.mark.lock
@pytest.mark.install
@pytest.mark.skipif(sys.version_info >= (3, 5), reason="scandir doesn't get installed on python 3.5+")
def test_lock_missing_cache_entries_gets_all_hashes(PipenvInstance, tmpdir):
    """
    Test locking pathlib2 on python2.7 which needs `scandir`, but fails to resolve when
    using a fresh dependency cache.
    """

    with temp_environ():
        os.environ["PIPENV_CACHE_DIR"] = str(tmpdir.strpath)
        with PipenvInstance(chdir=True) as p:
            p._pipfile.add("pathlib2", "*")
            assert "pathlib2" in p.pipfile["packages"]
            c = p.pipenv("install")
            assert c.returncode == 0, (c.stderr, ("\n".join([f"{k}: {v}\n" for k, v in os.environ.items()])))
            c = p.pipenv("lock --clear")
            assert c.returncode == 0, c.stderr
            assert "pathlib2" in p.lockfile["default"]
            assert "scandir" in p.lockfile["default"]
            assert isinstance(p.lockfile["default"]["scandir"]["hashes"], list)
            assert len(p.lockfile["default"]["scandir"]["hashes"]) > 1


@pytest.mark.vcs
@pytest.mark.lock
def test_vcs_lock_respects_top_level_pins(PipenvInstance):
    """Test that locking VCS dependencies respects top level packages pinned in Pipfiles"""

    with PipenvInstance(chdir=True) as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        p._pipfile.add("requests", {
            "editable": True, "git": f"{requests_uri}",
            "ref": "v2.18.4"
        })
        p._pipfile.add("urllib3", "==1.21.1")
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert "git" in p.lockfile["default"]["requests"]
        assert "urllib3" in p.lockfile["default"]
        assert p.lockfile["default"]["urllib3"]["version"] == "==1.21.1"


@pytest.mark.lock
def test_lock_after_update_source_name(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        contents = """
[[source]]
url = "{}"
verify_ssl = true
name = "test"

[packages]
six = "*"
        """.format(p.index_url).strip()
        with open(p.pipfile_path, 'w') as f:
            f.write(contents)
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert p.lockfile["default"]["six"]["index"] == "test"
        with open(p.pipfile_path, 'w') as f:
            f.write(contents.replace('name = "test"', 'name = "custom"'))
        c = p.pipenv("lock --clear")
        assert c.returncode == 0
        assert "index" in p.lockfile["default"]["six"]
        assert p.lockfile["default"]["six"]["index"] == "custom", Path(p.lockfile_path).read_text()


@pytest.mark.lock
def test_lock_nested_direct_url(PipenvInstance_NoPyPI):
    """
    The dependency 'test_package' has a declared dependency on
    a PEP508 style VCS URL. This ensures that we capture the dependency
    here along with its own dependencies.
    """
    with PipenvInstance_NoPyPI() as p:
        c = p.pipenv("install -v test_package")
        assert c.returncode == 0
        assert "vistir" in p.lockfile["default"]
        assert "colorama" in p.lockfile["default"]
        assert "six" in p.lockfile["default"]


@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_nested_vcs_direct_url(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p._pipfile.add("pep508_package", {
            "git": "https://github.com/techalchemy/test-project.git",
            "editable": True,  "ref": "master",
            "subdirectory": "parent_folder/pep508-package"
        })
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "git" in p.lockfile["default"]["pep508-package"]
        assert "sibling-package" in p.lockfile["default"]
        assert "git" in p.lockfile["default"]["sibling-package"]
        assert "subdirectory" in p.lockfile["default"]["sibling-package"]
        assert "version" not in p.lockfile["default"]["sibling-package"]


@pytest.mark.lock
@pytest.mark.install
def test_lock_package_with_wildcard_version(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install 'six==1.11.*'")
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert p.pipfile["packages"]["six"] == "==1.11.*"
        assert "six" in p.lockfile["default"]
        assert "version" in p.lockfile["default"]["six"]
        assert p.lockfile["default"]["six"]["version"] == "==1.11.0"


@pytest.mark.lock
@pytest.mark.install
def test_default_lock_overwrite_dev_lock(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install 'click==6.7'")
        assert c.returncode == 0
        c = p.pipenv("install -d flask")
        assert c.returncode == 0
        assert p.lockfile["default"]["click"]["version"] == "==6.7"
        assert p.lockfile["develop"]["click"]["version"] == "==6.7"


@flaky
@pytest.mark.lock
@pytest.mark.install
@pytest.mark.needs_internet
def test_pipenv_respects_package_index_restrictions(PipenvInstance_NoPyPI):
    with PipenvInstance_NoPyPI() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "{url}/simple"
verify_ssl = true
name = "local"

[packages]
requests = {requirement}
                """.strip().format(url=p.pypi, requirement='{version="*", index="local"}')
            f.write(contents)

        c = p.pipenv('lock')
        assert c.returncode == 0
        assert 'requests' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'certifi' in p.lockfile['default']
        assert 'urllib3' in p.lockfile['default']
        assert 'chardet' in p.lockfile['default']
        # this is the newest version we have in our private pypi (but pypi.org has 2.27.1 at present)
        expected_result = {'hashes': ['sha256:63b52e3c866428a224f97cab011de738c36aec0185aa91cfacd418b5d58911d1',
                                      'sha256:ec22d826a36ed72a7358ff3fe56cbd4ba69dd7a6718ffd450ff0e9df7a47ce6a'],
                           'index': 'local', 'version': '==2.19.1'}
        assert p.lockfile['default']['requests'] == expected_result


@pytest.mark.dev
@pytest.mark.lock
@pytest.mark.install
def test_dev_lock_use_default_packages_as_constraint(PipenvInstance):
    # See https://github.com/pypa/pipenv/issues/4371
    # See https://github.com/pypa/pipenv/issues/2987
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = "<=2.14.0"

[dev-packages]
requests = "*"
                """.strip()
            f.write(contents)

        c = p.pipenv("lock --dev")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert p.lockfile["default"]["requests"]["version"] == "==2.14.0"
        assert "requests" in p.lockfile["develop"]
        assert p.lockfile["develop"]["requests"]["version"] == "==2.14.0"

        # requests 2.14.0 doesn't require these packages
        assert "idna" not in p.lockfile["develop"]
        assert "certifi" not in p.lockfile["develop"]
        assert "urllib3" not in p.lockfile["develop"]
        assert "chardet" not in p.lockfile["develop"]

        c = p.pipenv("install --dev")
        c = p.pipenv("run python -c 'import urllib3'")
        assert c.returncode != 0
