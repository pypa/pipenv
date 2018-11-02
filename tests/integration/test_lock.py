import pytest
import os

from pipenv.utils import temp_environ

from flaky import flaky


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_handle_eggs(PipenvInstance, pypi):
    """Ensure locking works with packages provoding egg formats.
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
def test_lock_requirements_file(PipenvInstance, pypi):

    with PipenvInstance(pypi=pypi) as p:
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
def test_lock_keep_outdated(PipenvInstance, pypi):

    with PipenvInstance(pypi=pypi) as p:
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
@pytest.mark.complex
@pytest.mark.needs_internet
def test_complex_lock_with_vcs_deps(PipenvInstance, pip_src_dir):
    # This uses the real PyPI since we need Internet to access the Git
    # dependency anyway.
    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
click = "==6.7"

[dev-packages]
requests = {git = "https://github.com/requests/requests.git"}
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
def test_lock_with_prereleases(PipenvInstance, pypi):

    with PipenvInstance(pypi=pypi) as p:
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
@pytest.mark.complex
@pytest.mark.maya
@pytest.mark.needs_internet
@flaky
def test_complex_deps_lock_and_install_properly(PipenvInstance, pip_src_dir, pypi):
    # This uses the real PyPI because Maya has too many dependencies...
    with PipenvInstance(chdir=True, pypi=pypi) as p:
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


@pytest.mark.extras
@pytest.mark.lock
def test_lock_extras_without_install(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
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


@pytest.mark.extras
@pytest.mark.lock
@pytest.mark.complex
@pytest.mark.skip(reason='Needs numpy to be mocked')
@pytest.mark.needs_internet
def test_complex_lock_deep_extras(PipenvInstance, pypi):
    # records[pandas] requires tablib[pandas] which requires pandas.
    # This uses the real PyPI; Pandas has too many requirements to mock.

    with PipenvInstance(pypi=pypi) as p:
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


@pytest.mark.skip_lock
@pytest.mark.index
@pytest.mark.needs_internet
@pytest.mark.install  # private indexes need to be uncached for resolution
def test_private_index_skip_lock(PipenvInstance):
    with PipenvInstance() as p:
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


@pytest.mark.requirements
@pytest.mark.lock
@pytest.mark.index
@pytest.mark.install  # private indexes need to be uncached for resolution
@pytest.mark.needs_internet
def test_private_index_lock_requirements(PipenvInstance):
    # Don't use the local fake pypi
    with PipenvInstance() as p:
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


@pytest.mark.requirements
@pytest.mark.lock
@pytest.mark.index
@pytest.mark.install  # private indexes need to be uncached for resolution
@pytest.mark.needs_internet
def test_private_index_mirror_lock_requirements(PipenvInstance):
    # Don't use the local fake pypi
    with temp_environ(), PipenvInstance(chdir=True) as p:
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
requests = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv('install --pypi-mirror {0}'.format(mirror_url))
        assert c.return_code == 0
        c = p.pipenv('lock -r --pypi-mirror {0}'.format(mirror_url))
        assert c.return_code == 0
        assert '-i https://pypi.org/simple' in c.out.strip()
        assert '--extra-index-url https://test.pypi.org/simple' in c.out.strip()
        # Mirror url should not have replaced source URLs
        assert '-i {0}'.format(mirror_url) not in c.out.strip()
        assert '--extra-index-url {}'.format(mirror_url) not in c.out.strip()


@pytest.mark.install
@pytest.mark.index
def test_lock_updated_source(PipenvInstance, pypi):

    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "{url}/${{MY_ENV_VAR}}"

[packages]
requests = "==2.14.0"
            """.strip().format(url=pypi.url)
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
            """.strip().format(url=pypi.url)
            f.write(contents)

        c = p.pipenv('lock')
        assert c.return_code == 0
        assert 'requests' in p.lockfile['default']


@pytest.mark.lock
@pytest.mark.vcs
@pytest.mark.needs_internet
def test_lock_editable_vcs_without_install(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/requests/requests.git", ref = "master", editable = true}
            """.strip())
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert 'requests' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'chardet' in p.lockfile['default']
        c = p.pipenv('install')
        assert c.return_code == 0


@pytest.mark.lock
@pytest.mark.vcs
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_ref_in_git(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/requests/requests.git@883caaf", editable = true}
            """.strip())
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert p.lockfile['default']['requests']['git'] == 'https://github.com/requests/requests.git'
        assert p.lockfile['default']['requests']['ref'] == '883caaf145fbe93bd0d208a6b864de9146087312'
        c = p.pipenv('install')
        assert c.return_code == 0


@pytest.mark.lock
@pytest.mark.vcs
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_ref(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/requests/requests.git", ref = "883caaf", editable = true}
            """.strip())
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert p.lockfile['default']['requests']['git'] == 'https://github.com/requests/requests.git'
        assert p.lockfile['default']['requests']['ref'] == '883caaf145fbe93bd0d208a6b864de9146087312'
        c = p.pipenv('install')
        assert c.return_code == 0


@pytest.mark.extras
@pytest.mark.lock
@pytest.mark.vcs
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_extras_without_install(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/requests/requests.git", editable = true, extras = ["socks"]}
            """.strip())
        c = p.pipenv('lock')
        assert c.return_code == 0
        assert 'requests' in p.lockfile['default']
        assert 'idna' in p.lockfile['default']
        assert 'chardet' in p.lockfile['default']
        assert "socks" in p.lockfile["default"]["requests"]["extras"]
        c = p.pipenv('install')
        assert c.return_code == 0


@pytest.mark.lock
@pytest.mark.vcs
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_markers_without_install(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write("""
[packages]
requests = {git = "https://github.com/requests/requests.git", ref = "master", editable = true, markers = "python_version >= '2.6'"}
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
def test_lock_respecting_python_version(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
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
