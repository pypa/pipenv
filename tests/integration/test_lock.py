# -*- coding: utf-8 -*-

import json
import os
import shutil
import sys

import pytest

from flaky import flaky
from vistir.compat import Path
from vistir.misc import to_text
from pipenv.utils import temp_environ
import delegator


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_handle_eggs(PipenvInstance):
    """Ensure locking works with packages providing egg formats.
    """
    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
RandomWords = "*"
            """)
        c = p.pipenv('lock --verbose')
        assert c.return_code == 0
        assert 'randomwords' in p.lockfile['default']
        assert p.lockfile['default']['randomwords']['version'] == '==0.2.1'


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_requirements_file(PipenvInstance):

    with PipenvInstance() as p:
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

        c = p.pipenv('lock -r')
        d = p.pipenv('lock -r -d')
        assert c.return_code == 0
        assert d.return_code == 0

        for req in req_list:
            assert req in c.out

        for req in dev_req_list:
            assert req in d.out


@pytest.mark.lock
@pytest.mark.keep_outdated
def test_lock_keep_outdated(PipenvInstance):

    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
requests = {version = "==2.14.0"}
PyTest = "==3.1.0"
            """.strip()
            f.write(contents)

        c = p.pipenv('lock')
        assert c.return_code == 0
        lock = p.lockfile
        assert 'requests' in lock['default']
        assert lock['default']['requests']['version'] == "==2.14.0"
        assert 'pytest' in lock['default']
        assert lock['default']['pytest']['version'] == "==3.1.0"

        with open(p.pipfile_path, 'w') as f:
            updated_contents = """
[packages]
requests = {version = "==2.18.4"}
PyTest = "*"
            """.strip()
            f.write(updated_contents)

        c = p.pipenv('lock --keep-outdated')
        assert c.return_code == 0
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
        p.pipenv("install")
        p._pipfile.add("six", "*")
        p.pipenv("lock --keep-outdated")
        assert "colorama" in p.lockfile["default"]
        assert p.lockfile["default"]["colorama"]["markers"] == "os_name == 'FakeOS'"


@pytest.mark.lock
@pytest.mark.keep_outdated
def test_keep_outdated_doesnt_upgrade_pipfile_pins(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p._pipfile.add("urllib3", "==1.21.1")
        c = p.pipenv("install")
        assert c.ok
        p._pipfile.add("requests", "==2.18.4")
        c = p.pipenv("lock --keep-outdated")
        assert c.ok
        assert "requests" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert p.lockfile["default"]["requests"]["version"] == "==2.18.4"
        assert p.lockfile["default"]["urllib3"]["version"] == "==1.21.1"


@pytest.mark.lock
def test_keep_outdated_keeps_markers_not_removed(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install six click")
        assert c.ok
        lockfile = Path(p.lockfile_path)
        lockfile_content = lockfile.read_text()
        lockfile_json = json.loads(lockfile_content)
        assert "six" in lockfile_json["default"]
        lockfile_json["default"]["six"]["markers"] = "python_version >= '2.7'"
        lockfile.write_text(to_text(json.dumps(lockfile_json)))
        c = p.pipenv("lock --keep-outdated")
        assert c.ok
        assert p.lockfile["default"]["six"].get("markers", "") == "python_version >= '2.7'"


@pytest.mark.lock
@pytest.mark.keep_outdated
def test_keep_outdated_doesnt_update_satisfied_constraints(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p._pipfile.add("requests", "==2.18.4")
        c = p.pipenv("install")
        assert c.ok
        p._pipfile.add("requests", "*")
        assert p.pipfile["packages"]["requests"] == "*"
        c = p.pipenv("lock --keep-outdated")
        assert c.ok
        assert "requests" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        # ensure this didn't update requests
        assert p.lockfile["default"]["requests"]["version"] == "==2.18.4"
        c = p.pipenv("lock")
        assert c.ok
        assert p.lockfile["default"]["requests"]["version"] != "==2.18.4"


@pytest.mark.lock
@pytest.mark.complex
@pytest.mark.needs_internet
def test_complex_lock_with_vcs_deps(local_tempdir, PipenvInstance, pip_src_dir):
    # This uses the real PyPI since we need Internet to access the Git
    # dependency anyway.
    with PipenvInstance() as p, local_tempdir:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
click = "==6.7"

[dev-packages]
requests = {git = "https://github.com/psf/requests.git"}
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0
        lock = p.lockfile
        assert 'requests' in lock['develop']
        assert 'click' in lock['default']

        c = p.pipenv('run pip install -e git+https://github.com/dateutil/dateutil#egg=python_dateutil')
        assert c.return_code == 0

        c = p.pipenv('lock')
        assert c.return_code == 0
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
        assert c.return_code == 0
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
        assert c.return_code == 0

        c = p.pipenv('install')
        assert c.return_code == 0


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
        assert c.return_code == 0
        assert "requests" in p.lockfile["default"]
        assert "pysocks" in p.lockfile["default"]
        assert "markers" not in p.lockfile["default"]['pysocks']

        c = p.pipenv('lock -r')
        assert c.return_code == 0
        assert "extra == 'socks'" not in c.out.strip()


@pytest.mark.lock
@pytest.mark.extras
@pytest.mark.complex
@pytest.mark.needs_internet
@pytest.mark.skip(reason='Needs numpy to be mocked')
def test_complex_lock_deep_extras(PipenvInstance):
    # records[pandas] requires tablib[pandas] which requires pandas.
    # This uses the real PyPI; Pandas has too many requirements to mock.

    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
records = {extras = ["pandas"], version = "==0.5.2"}
            """.strip()
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert 'tablib' in p.lockfile['default']
        assert 'pandas' in p.lockfile['default']


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
        assert c.return_code == 0


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
        c = p.pipenv('install')
        assert c.return_code == 0
        c = p.pipenv('lock -r')
        assert c.return_code == 0
        assert '-i https://pypi.org/simple' in c.out.strip()
        assert '--extra-index-url https://test.pypi.org/simple' in c.out.strip()


@pytest.mark.lock
@pytest.mark.index
@pytest.mark.install  # private indexes need to be uncached for resolution
@pytest.mark.requirements
@pytest.mark.needs_internet
def test_private_index_mirror_lock_requirements(PipenvInstance_NoPyPI):
    # Don't use the local fake pypi
    with temp_environ(), PipenvInstance_NoPyPI(chdir=True) as p:
        # Using pypi.python.org as pipenv-test-public-package is not
        # included in the local pypi mirror
        mirror_url = os.environ.pop('PIPENV_TEST_INDEX', "https://pypi.kennethreitz.org/simple")
        # os.environ.pop('PIPENV_TEST_INDEX', None)
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
fake-package = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv('install --pypi-mirror {0}'.format(mirror_url))
        assert c.return_code == 0
        c = p.pipenv('lock -r --pypi-mirror {0}'.format(mirror_url))
        assert c.return_code == 0
        assert '-i {0}'.format(mirror_url) in c.out.strip()
        assert '--extra-index-url https://test.pypi.org/simple' in c.out.strip()
        assert '--extra-index-url {}'.format(mirror_url) not in c.out.strip()


@pytest.mark.lock
@pytest.mark.install
@pytest.mark.skip_windows
@pytest.mark.needs_internet
def test_outdated_setuptools_with_pep517_legacy_build_meta_is_updated(PipenvInstance):
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
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv('run pip install "setuptools<=40.2"')
        assert c.return_code == 0
        c = p.pipenv("run python -c 'import setuptools; print(setuptools.__version__)'")
        assert c.return_code == 0
        assert c.out.strip() == "40.2.0"
        c = p.pipenv("install legacy-backend-package")
        assert c.return_code == 0
        assert "vistir" in p.lockfile["default"]


@pytest.mark.lock
@pytest.mark.install
@pytest.mark.skip_windows
@pytest.mark.needs_internet
def test_outdated_setuptools_with_pep517_cython_import_in_setuppy(PipenvInstance):
    """
    This test ensures we are using build isolation and a pep517 backend
    because the package in question declares 'cython' as a build dependency
    in ``pyproject.toml``, then imports it in ``setup.py``.  The pep517
    backend will have to install it first, so this will only pass if the
    resolver is buliding with a proper backend.
    """
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv('run pip install "setuptools<=40.2"')
        assert c.return_code == 0
        c = p.pipenv("run python -c 'import setuptools; print(setuptools.__version__)'")
        assert c.return_code == 0
        assert c.out.strip() == "40.2.0"
        c = p.pipenv("install cython-import-package")
        assert c.return_code == 0
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
            assert c.return_code == 0
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
        assert c.return_code == 0
        assert 'requests' in p.lockfile['default']


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_without_install(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/psf/requests.git", ref = "master", editable = true}
            """.strip())
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert 'requests' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'chardet' in p.lockfile['default']
        c = p.pipenv('install')
        assert c.return_code == 0


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_ref_in_git(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/psf/requests.git@883caaf", editable = true}
            """.strip())
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert p.lockfile['default']['requests']['git'] == 'https://github.com/psf/requests.git'
        assert p.lockfile['default']['requests']['ref'] == '883caaf145fbe93bd0d208a6b864de9146087312'
        c = p.pipenv('install')
        assert c.return_code == 0


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_ref(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/psf/requests.git", ref = "883caaf", editable = true}
            """.strip())
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert p.lockfile['default']['requests']['git'] == 'https://github.com/psf/requests.git'
        assert p.lockfile['default']['requests']['ref'] == '883caaf145fbe93bd0d208a6b864de9146087312'
        c = p.pipenv('install')
        assert c.return_code == 0


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.extras
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_extras_without_install(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/psf/requests.git", editable = true, extras = ["socks"]}
            """.strip())
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert 'requests' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'chardet' in p.lockfile['default']
        assert "socks" in p.lockfile["default"]["requests"]["extras"]
        c = p.pipenv('install')
        assert c.return_code == 0
        assert "requests" in p.lockfile["default"]
        # For backward compatibility we want to make sure not to include the 'version' key
        assert "version" not in p.lockfile["default"]["requests"]


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_markers_without_install(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/psf/requests.git", ref = "master", editable = true, markers = "python_version >= '2.6'"}
            """.strip())
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert 'requests' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'chardet' in p.lockfile['default']
        c = p.pipenv('install')
        assert c.return_code == 0


@pytest.mark.lock
@pytest.mark.skip(reason="This doesn't work for some reason.")
def test_lock_respecting_python_version(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
django = "*"
            """.strip())
        c = p.pipenv('install ')
        assert c.return_code == 0
        c = p.pipenv('run python --version')
        assert c.return_code == 0
        py_version = c.err.splitlines()[-1].strip().split()[-1]
        django_version = '==2.0.6' if py_version.startswith('3') else '==1.11.13'
        assert py_version == '2.7.14'
        assert p.lockfile['default']['django']['version'] == django_version


@pytest.mark.lock
@pytest.mark.install
def test_lockfile_corrupted(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.lockfile_path, 'w') as f:
            f.write('{corrupted}')
        c = p.pipenv('install')
        assert c.return_code == 0
        assert 'Pipfile.lock is corrupted' in c.err
        assert p.lockfile['_meta']


@pytest.mark.lock
@pytest.mark.install
def test_lockfile_with_empty_dict(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.lockfile_path, 'w') as f:
            f.write('{}')
        c = p.pipenv('install')
        assert c.return_code == 0
        assert 'Pipfile.lock is corrupted' in c.err
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
        assert c.return_code == 0
        c = p.pipenv('install')
        assert c.return_code == 0
        assert p.lockfile['_meta']['sources']


@pytest.mark.lock
@pytest.mark.install
def test_lock_no_warnings(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        os.environ["PYTHONWARNINGS"] = str("once")
        c = p.pipenv("install six")
        assert c.return_code == 0
        c = p.pipenv('run python -c "import warnings; warnings.warn(\\"This is a warning\\", DeprecationWarning); print(\\"hello\\")"')
        assert c.return_code == 0
        assert "Warning" in c.err
        assert "Warning" not in c.out
        assert "hello" in c.out


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
            assert c.return_code == 0, (c.err, ("\n".join(["{0}: {1}\n".format(k, v) for k, v in os.environ.items()])))
            c = p.pipenv("lock --clear")
            assert c.return_code == 0, c.err
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
            "editable": True, "git": "{0}".format(requests_uri),
            "ref": "v2.18.4"
        })
        p._pipfile.add("urllib3", "==1.21.1")
        c = p.pipenv("install")
        assert c.return_code == 0
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
        assert c.return_code == 0
        assert p.lockfile["default"]["six"]["index"] == "test"
        with open(p.pipfile_path, 'w') as f:
            f.write(contents.replace('name = "test"', 'name = "custom"'))
        c = p.pipenv("lock --clear")
        assert c.return_code == 0
        assert "index" in p.lockfile["default"]["six"]
        assert p.lockfile["default"]["six"]["index"] == "custom", Path(p.lockfile_path).read_text()


@pytest.mark.lock
def test_lock_nested_direct_url(PipenvInstance):
    """
    The dependency 'test_package' has a declared dependency on
    a PEP508 style VCS URL. This ensures that we capture the dependency
    here along with its own dependencies.
    """
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv("install test_package")
        assert c.return_code == 0
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
        c = p.pipenv("install")
        assert c.return_code == 0
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
        assert c.ok
        assert "six" in p.pipfile["packages"]
        assert p.pipfile["packages"]["six"] == "==1.11.*"
        assert "six" in p.lockfile["default"]
        assert "version" in p.lockfile["default"]["six"]
        assert p.lockfile["default"]["six"]["version"] == "==1.11.0"
