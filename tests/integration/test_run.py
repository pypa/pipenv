import os

import pytest

from pipenv._compat import TemporaryDirectory
from pipenv.project import Project
from pipenv.utils import temp_environ


@pytest.mark.run
@pytest.mark.dotenv
def test_env(PipenvInstance):
    with PipenvInstance(pipfile=False, chdir=True) as p:
        with open('.env', 'w') as f:
            f.write('HELLO=WORLD')

        c = p.pipenv('run python -c "import os; print(os.environ[\'HELLO\'])"')
        assert c.return_code == 0
        assert 'WORLD' in c.out


@pytest.mark.run
@pytest.mark.dotenv
def test_doesnt_load_dot_env_if_disabled(PipenvInstance):
    with PipenvInstance() as p:
        with temp_environ(), TemporaryDirectory(prefix='pipenv-', suffix='') as tempdir:
            dotenv_path = os.path.join(tempdir.name, 'test.env')
            key, val = 'SOME_KEY', 'some_value'
            with open(dotenv_path, 'w') as f:
                f.write('{}={}'.format(key, val))

            os.environ['PIPENV_DOTENV_LOCATION'] = dotenv_path

            with open(p.pipfile_path, "w") as f:
                contents = """
[pipenv]
dont_load_env = true
                """.strip()
                f.write(contents)

            c = p.pipenv('run python -c "import os; print(os.getenv(\'SOME_KEY\'))"')
            assert c.return_code == 0
            assert 'None' in c.out

            with open(p.pipfile_path, "w") as f:
                contents = """
[pipenv]
dont_load_env = false
                """.strip()
                f.write(contents)

            c = p.pipenv('run python -c "import os; print(os.getenv(\'SOME_KEY\'))"')
            assert c.return_code == 0
            assert 'some_value' in c.out


@pytest.mark.run
@pytest.mark.dotenv
def test_doesnt_override_env_if_disabled(PipenvInstance):
    with PipenvInstance() as p:
        with temp_environ(), TemporaryDirectory(prefix='pipenv-', suffix='') as tempdir:
            dotenv_path = os.path.join(tempdir.name, 'test.env')
            key, val = 'SOME_KEY', 'some_value'
            with open(dotenv_path, 'w') as f:
                f.write('{}={}'.format(key, val))

            os.environ['PIPENV_DOTENV_LOCATION'] = dotenv_path
            os.environ['SOME_KEY'] = 'orig_value'

            with open(p.pipfile_path, "w") as f:
                contents = """
[pipenv]
dont_override_env = true
                """.strip()
                f.write(contents)

            c = p.pipenv('run python -c "import os; print(os.getenv(\'SOME_KEY\'))"')
            assert c.return_code == 0
            assert 'orig_value' in c.out

            with open(p.pipfile_path, "w") as f:
                contents = """
[pipenv]
dont_override_env = false
                """.strip()
                f.write(contents)

            c = p.pipenv('run python -c "import os; print(os.getenv(\'SOME_KEY\'))"')
            assert c.return_code == 0
            assert 'some_value' in c.out


@pytest.mark.run
def test_scripts(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with open(p.pipfile_path, 'w') as f:
            f.write(r"""
[scripts]
printfoo = "python -c \"print('foo')\""
notfoundscript = "randomthingtotally"
appendscript = "cmd arg1"
multicommand = "bash -c \"cd docs && make html\""
            """)
        c = p.pipenv('install')
        assert c.return_code == 0

        c = p.pipenv('run printfoo')
        assert c.return_code == 0
        assert c.out == 'foo\n'
        assert c.err == ''

        c = p.pipenv('run notfoundscript')
        assert c.return_code == 1
        assert c.out == ''
        if os.name != 'nt':     # TODO: Implement this message for Windows.
            assert 'Error' in c.err
            assert 'randomthingtotally (from notfoundscript)' in c.err

        project = Project()

        script = project.build_script('multicommand')
        assert script.command == 'bash'
        assert script.args == ['-c', 'cd docs && make html']

        script = project.build_script('appendscript', ['a', 'b'])
        assert script.command == 'cmd'
        assert script.args == ['arg1', 'a', 'b']
