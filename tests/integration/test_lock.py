import pytest

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

        req_list = ("requests==2.14.0")

        dev_req_list = ("flask==0.12.2")

        c = p.pipenv('lock -r')
        d = p.pipenv('lock -r -d')
        assert c.return_code == 0
        assert d.return_code == 0

        for req in req_list:
            assert req in c.out

        for req in dev_req_list:
            assert req in d.out


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
url = "https://pypi.python.org/simple"
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
url = "https://pypi.python.org/simple"
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
        assert '-i https://pypi.python.org/simple' in c.out.strip()
        assert '--extra-index-url https://test.pypi.org/simple' in c.out.strip()
