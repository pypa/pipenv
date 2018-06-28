import os
import shutil
from pipenv.project import Project
from pipenv._compat import Path

from pipenv.utils import mkdir_p, temp_environ

import pytest

from flaky import flaky


@pytest.mark.extras
@pytest.mark.install
@pytest.mark.local
@pytest.mark.parametrize('line, pipfile', [
    ['-e .[dev]', {'testpipenv': {'path': '.', 'editable': True, 'extras': ['dev']}}]
])
def test_local_extras_install(PipenvInstance, pypi, line, pipfile):
    """Ensure -e .[extras] installs.
    """
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        project = Project()
        setup_py = os.path.join(p.path, 'setup.py')
        with open(setup_py, 'w') as fh:
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
        project.write_toml({'packages': pipfile, 'dev-packages': {}})
        c = p.pipenv('install')
        assert c.return_code == 0
        assert 'testpipenv' in p.lockfile['default']
        assert p.lockfile['default']['testpipenv']['extras'] == ['dev']
        assert 'six' in p.lockfile['default']
        c = p.pipenv('--rm')
        assert c.return_code == 0
        project.write_toml({'packages': {}, 'dev-packages': {}})
        c = p.pipenv('install {0}'.format(line))
        assert c.return_code == 0
        assert 'testpipenv' in p.pipfile['packages']
        assert p.pipfile['packages']['testpipenv']['path'] == '.'
        assert p.pipfile['packages']['testpipenv']['extras'] == ['dev']
        assert 'six' in p.lockfile['default']


@pytest.mark.e
@pytest.mark.install
@pytest.mark.skip(reason="this doesn't work on windows")
def test_e_dot(PipenvInstance, pip_src_dir):
    with PipenvInstance() as p:
        path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        c = p.pipenv('install -e \'{0}\' --dev'.format(path))

        assert c.return_code == 0

        key = [k for k in p.pipfile['dev-packages'].keys()][0]
        assert 'path' in p.pipfile['dev-packages'][key]
        assert 'requests' in p.lockfile['develop']


@pytest.mark.install
@flaky
def test_multiprocess_bug_and_install(PipenvInstance, pypi):
    with temp_environ():
        os.environ['PIPENV_MAX_SUBPROCESS'] = '2'

        with PipenvInstance(pypi=pypi, chdir=True) as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
pytz = "*"
six = "*"
urllib3 = "*"
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0

            assert 'pytz' in p.lockfile['default']
            assert 'six' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']

            c = p.pipenv('run python -c "import six; import pytz; import urllib3;"')
            assert c.return_code == 0


@pytest.mark.sequential
@pytest.mark.install
@flaky
def test_sequential_mode(PipenvInstance, pypi):

    with PipenvInstance(pypi=pypi, chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[packages]
six = "*"
urllib3 = "*"
pytz = "*"
            """.strip()
            f.write(contents)

        c = p.pipenv('install --sequential')
        assert c.return_code == 0

        assert 'six' in p.lockfile['default']
        assert 'pytz' in p.lockfile['default']
        assert 'urllib3' in p.lockfile['default']

        c = p.pipenv('run python -c "import six; import urllib3; import pytz;"')
        assert c.return_code == 0


@pytest.mark.install
@pytest.mark.run
def test_normalize_name_install(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
# Pre comment
[packages]
Requests = "==2.14.0"   # Inline comment
"""
            f.write(contents)

        c = p.pipenv('install')
        assert c.return_code == 0

        c = p.pipenv('install requests')
        assert c.return_code == 0
        assert 'requests' not in p.pipfile['packages']
        assert p.pipfile['packages']['Requests'] == '==2.14.0'
        c = p.pipenv('install requests==2.18.4')
        assert c.return_code == 0
        assert p.pipfile['packages']['Requests'] == '==2.18.4'
        c = p.pipenv('install python_DateUtil')
        assert c.return_code == 0
        assert 'python-dateutil' in p.pipfile['packages']
        contents = open(p.pipfile_path).read()
        assert '# Pre comment' in contents
        assert '# Inline comment' in contents


@pytest.mark.files
@pytest.mark.resolver
@pytest.mark.eggs
@flaky
def test_local_package(PipenvInstance, pip_src_dir, pypi, testsroot):
    """This test ensures that local packages (directories with a setup.py)
    installed in editable mode have their dependencies resolved as well"""
    file_name = 'tablib-0.12.1.tar.gz'
    package = 'tablib-0.12.1'
    # Not sure where travis/appveyor run tests from
    source_path = os.path.abspath(os.path.join(testsroot, 'test_artifacts', file_name))
    with PipenvInstance(chdir=True, pypi=pypi) as p:
        # This tests for a bug when installing a zipfile in the current dir
        copy_to = os.path.join(p.path, file_name)
        shutil.copy(source_path, copy_to)
        import tarfile
        with tarfile.open(copy_to, 'r:gz') as tgz:
            tgz.extractall(path=p.path)
        c = p.pipenv('install -e {0}'.format(package))
        assert c.return_code == 0
        assert all(pkg in p.lockfile['default'] for pkg in ['xlrd', 'xlwt', 'pyyaml', 'odfpy'])


@pytest.mark.files
@flaky
def test_local_zipfiles(PipenvInstance, pypi, testsroot):
    file_name = 'tablib-0.12.1.tar.gz'
    # Not sure where travis/appveyor run tests from
    source_path = os.path.abspath(os.path.join(testsroot, 'test_artifacts', file_name))

    with PipenvInstance(chdir=True, pypi=pypi) as p:
        # This tests for a bug when installing a zipfile in the current dir
        shutil.copy(source_path, os.path.join(p.path, file_name))

        c = p.pipenv('install {}'.format(file_name))
        assert c.return_code == 0
        key = [k for k in p.pipfile['packages'].keys()][0]
        dep = p.pipfile['packages'][key]

        assert 'file' in dep or 'path' in dep
        assert c.return_code == 0

        key = [k for k in p.lockfile['default'].keys()][0]
        dep = p.lockfile['default'][key]

        assert 'file' in dep or 'path' in dep


@pytest.mark.files
@flaky
def test_relative_paths(PipenvInstance, pypi, testsroot):
    file_name = 'tablib-0.12.1.tar.gz'
    source_path = os.path.abspath(os.path.join(testsroot, 'test_artifacts', file_name))

    with PipenvInstance(pypi=pypi) as p:
        artifact_dir = 'artifacts'
        artifact_path = os.path.join(p.path, artifact_dir)
        mkdir_p(artifact_path)
        shutil.copy(source_path, os.path.join(artifact_path, file_name))
        # Test installing a relative path in a subdirectory
        c = p.pipenv('install {}/{}'.format(artifact_dir, file_name))
        assert c.return_code == 0
        key = next(k for k in p.pipfile['packages'].keys())
        dep = p.pipfile['packages'][key]

        assert 'path' in dep
        assert Path('.', artifact_dir, file_name) == Path(dep['path'])
        assert c.return_code == 0


@pytest.mark.install
@pytest.mark.local_file
@flaky
def test_install_local_file_collision(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi) as p:
        target_package = 'alembic'
        fake_file = os.path.join(p.path, target_package)
        with open(fake_file, 'w') as f:
            f.write('')
        c = p.pipenv('install {}'.format(target_package))
        assert c.return_code == 0
        assert target_package in p.pipfile['packages']
        assert p.pipfile['packages'][target_package] == '*'
        assert target_package in p.lockfile['default']


@pytest.mark.url
@pytest.mark.install
def test_install_local_uri_special_character(PipenvInstance, testsroot):
    file_name = 'six-1.11.0+mkl-py2.py3-none-any.whl'
    source_path = os.path.abspath(os.path.join(testsroot, 'test_artifacts', file_name))
    with PipenvInstance() as p:
        artifact_dir = 'artifacts'
        artifact_path = os.path.join(p.path, artifact_dir)
        mkdir_p(artifact_path)
        shutil.copy(source_path, os.path.join(artifact_path, file_name))
        with open(p.pipfile_path, 'w') as f:
            contents = """
# Pre comment
[packages]
six = {{path = "./artifacts/{}"}}   
            """.format(file_name)
            f.write(contents.strip())
        c = p.pipenv('install')
        assert c.return_code == 0
        assert 'six' in p.lockfile['default']
