# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function
import io
import os
import tarfile

import pytest

from pipenv.patched import pipfile
from pipenv.project import Project
from pipenv.utils import temp_environ
from pipenv.vendor.vistir.path import is_in_path
from pipenv.vendor.delegator import run as delegator_run


@pytest.mark.project
@pytest.mark.sources
@pytest.mark.environ
def test_pipfile_envvar_expansion(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with temp_environ():
            with open(p.pipfile_path, 'w') as f:
                f.write("""
[[source]]
url = 'https://${TEST_HOST}/simple'
verify_ssl = false
name = "pypi"

[packages]
pytz = "*"
                """.strip())
            os.environ['TEST_HOST'] = 'localhost:5000'
            project = Project()
            assert project.sources[0]['url'] == 'https://localhost:5000/simple'
            assert 'localhost:5000' not in str(pipfile.load(p.pipfile_path))


@pytest.mark.project
@pytest.mark.sources
@pytest.mark.parametrize('lock_first', [True, False])
def test_get_source(PipenvInstance, lock_first):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "{0}"
verify_ssl = false
name = "testindex"

[[source]]
url = "https://pypi.org/simple"
verify_ssl = "true"
name = "pypi"

[packages]
pytz = "*"
six = {{version = "*", index = "pypi"}}

[dev-packages]
            """.format(os.environ['PIPENV_TEST_INDEX']).strip()
            f.write(contents)

        if lock_first:
            # force source to be cached
            c = p.pipenv('lock')
            assert c.return_code == 0
        project = Project()
        sources = [
            ['pypi', 'https://pypi.org/simple'],
            ['testindex', os.environ.get('PIPENV_TEST_INDEX')]
        ]
        for src in sources:
            name, url = src
            source = [s for s in project.pipfile_sources if s.get('name') == name]
            assert source
            source = source[0]
            assert source['name'] == name
            assert source['url'] == url
            assert sorted(source.items()) == sorted(project.get_source(name=name).items())
            assert sorted(source.items()) == sorted(project.get_source(url=url).items())
            assert sorted(source.items()) == sorted(project.find_source(name).items())
            assert sorted(source.items()) == sorted(project.find_source(url).items())


@pytest.mark.install
@pytest.mark.project
@pytest.mark.parametrize('newlines', [u'\n', u'\r\n'])
def test_maintain_file_line_endings(PipenvInstance, newlines):
    with PipenvInstance(chdir=True) as p:
        # Initial pipfile + lockfile generation
        c = p.pipenv('install pytz')
        assert c.return_code == 0

        # Rewrite each file with parameterized newlines
        for fn in [p.pipfile_path, p.lockfile_path]:
            with io.open(fn) as f:
                contents = f.read()
                written_newlines = f.newlines

            assert written_newlines == u'\n', '{0!r} != {1!r} for {2}'.format(
                written_newlines, u'\n', fn,
            )
            # message because of  https://github.com/pytest-dev/pytest/issues/3443
            with io.open(fn, 'w', newline=newlines) as f:
                f.write(contents)

        # Run pipenv install to programatically rewrite
        c = p.pipenv('install chardet')
        assert c.return_code == 0

        # Make sure we kept the right newlines
        for fn in [p.pipfile_path, p.lockfile_path]:
            with io.open(fn) as f:
                f.read()    # Consumes the content to detect newlines.
                actual_newlines = f.newlines
            assert actual_newlines == newlines, '{0!r} != {1!r} for {2}'.format(
                actual_newlines, newlines, fn,
            )
            # message because of  https://github.com/pytest-dev/pytest/issues/3443


@pytest.mark.project
@pytest.mark.sources
def test_many_indexes(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "{0}"
verify_ssl = false
name = "testindex"

[[source]]
url = "https://pypi.org/simple"
verify_ssl = "true"
name = "pypi"

[[source]]
url = "https://pypi.python.org/simple"
verify_ssl = "true"
name = "legacy"

[packages]
pytz = "*"
six = {{version = "*", index = "pypi"}}

[dev-packages]
            """.format(os.environ['PIPENV_TEST_INDEX']).strip()
            f.write(contents)
        c = p.pipenv('install')
        assert c.return_code == 0


@pytest.mark.install
@pytest.mark.project
def test_include_editable_packages(PipenvInstance, testsroot, pathlib_tmpdir):
    file_name = "tablib-0.12.1.tar.gz"
    package = pathlib_tmpdir.joinpath("tablib-0.12.1")
    source_path = os.path.abspath(os.path.join(testsroot, "pypi", "tablib", file_name))
    with PipenvInstance(chdir=True) as p:
        with tarfile.open(source_path, "r:gz") as tarinfo:
            tarinfo.extractall(path=str(pathlib_tmpdir))
        c = p.pipenv('install -e {0}'.format(package.as_posix()))
        assert c.return_code == 0
        project = Project()
        assert "tablib" in [
            package.project_name
            for package in project.environment.get_installed_packages()
        ]


@pytest.mark.project
@pytest.mark.virtualenv
def test_run_in_virtualenv_with_global_context(PipenvInstance, virtualenv):
    with PipenvInstance(chdir=True, venv_root=virtualenv.as_posix(), ignore_virtualenvs=False, venv_in_project=False) as p:
        c = delegator_run(
            "pipenv run pip freeze", cwd=os.path.abspath(p.path),
            env=os.environ.copy()
        )
        assert c.return_code == 0, (c.out, c.err)
        assert 'Creating a virtualenv' not in c.err, c.err
        project = Project()
        assert project.virtualenv_location == virtualenv.as_posix(), (
            project.virtualenv_location, virtualenv.as_posix()
        )
        c = delegator_run(
            "pipenv run pip install click", cwd=os.path.abspath(p.path),
            env=os.environ.copy()
        )
        assert c.return_code == 0, (c.out, c.err)
        assert "Courtesy Notice" in c.err, (c.out, c.err)
        c = delegator_run(
            "pipenv install six", cwd=os.path.abspath(p.path), env=os.environ.copy()
        )
        assert c.return_code == 0, (c.out, c.err)
        c = delegator_run(
            'pipenv run python -c "import click;print(click.__file__)"',
            cwd=os.path.abspath(p.path), env=os.environ.copy()
        )
        assert c.return_code == 0, (c.out, c.err)
        assert is_in_path(c.out.strip(), str(virtualenv)), (c.out.strip(), str(virtualenv))
        c = delegator_run(
            "pipenv clean --dry-run", cwd=os.path.abspath(p.path),
            env=os.environ.copy()
        )
        assert c.return_code == 0, (c.out, c.err)
        assert "click" in c.out, c.out


@pytest.mark.project
@pytest.mark.virtualenv
def test_run_in_virtualenv(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv('run pip freeze')
        assert c.return_code == 0
        assert 'Creating a virtualenv' in c.err
        project = Project()
        c = p.pipenv("run pip install click")
        assert c.return_code == 0
        c = p.pipenv("install six")
        assert c.return_code == 0
        c = p.pipenv('run python -c "import click;print(click.__file__)"')
        assert c.return_code == 0
        assert c.out.strip().startswith(str(project.virtualenv_location))
        c = p.pipenv("clean --dry-run")
        assert c.return_code == 0
        assert "click" in c.out
