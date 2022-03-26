import os

import pytest

from pipenv.project import Project
from pipenv.utils import subprocess_run, temp_environ


@pytest.mark.run
@pytest.mark.dotenv
def test_env(PipenvInstance):
    with PipenvInstance(pipfile=False, chdir=True) as p:
        with open(os.path.join(p.path, ".env"), "w") as f:
            f.write("HELLO=WORLD")
        c = subprocess_run(['pipenv', 'run', 'python', '-c', "import os; print(os.environ['HELLO'])"], env=p.env)
        assert c.returncode == 0
        assert 'WORLD' in c.stdout


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
            if os.name == "nt":
                f.write('scriptwithenv = "echo %HELLO%"\n')
            else:
                f.write('scriptwithenv = "echo $HELLO"\n')
        c = p.pipenv('install')
        assert c.returncode == 0
        c = p.pipenv('run printfoo')
        assert c.returncode == 0
        assert c.stdout.strip() == 'foo'
        assert not c.stderr.strip()

        c = p.pipenv('run notfoundscript')
        assert c.returncode != 0
        assert c.stdout == ''
        if os.name != 'nt':     # TODO: Implement this message for Windows.
            assert 'not found' in c.stderr

        project = Project()

        script = project.build_script('multicommand')
        assert script.command == 'bash'
        assert script.args == ['-c', 'cd docs && make html']

        script = project.build_script('appendscript', ['a', 'b'])
        assert script.command == 'cmd'
        assert script.args == ['arg1', 'a', 'b']

        with temp_environ():
            os.environ['HELLO'] = 'WORLD'
            c = p.pipenv("run scriptwithenv")
            assert c.returncode == 0
            if os.name != "nt":  # This doesn't work on CI windows.
                assert c.stdout.strip() == "WORLD"


@pytest.mark.run
@pytest.mark.skip_windows
def test_run_with_usr_env_shebang(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p.pipenv('install')
        script_path = os.path.join(p.path, "test_script")
        with open(script_path, "w") as f:
            f.write(
                "#!/usr/bin/env python\n"
                "import sys, os\n\n"
                "print(sys.prefix)\n"
                "print(os.getenv('VIRTUAL_ENV'))\n"
            )
        os.chmod(script_path, 0o700)
        c = p.pipenv("run ./test_script")
        assert c.returncode == 0
        project = Project()
        lines = [line.strip() for line in c.stdout.splitlines()]
        assert all(line == project.virtualenv_location for line in lines)


@pytest.mark.run
@pytest.mark.parametrize('quiet', [True, False])
def test_scripts_resolve_dot_env_vars(quiet, PipenvInstance):
    with PipenvInstance() as p:
        with open(".env", "w") as f:
            contents = """
HELLO=WORLD
            """.strip()
            f.write(contents)

        with open(p.pipfile_path, "w") as f:
            contents = """
[scripts]
hello = "echo $HELLO"
            """.strip()
            f.write(contents)
        if quiet:
            c = p.pipenv('run --quiet hello')
        else:
            c = p.pipenv('run hello')
        assert c.returncode == 0
        assert 'WORLD\n' == c.stdout


@pytest.mark.run
@pytest.mark.parametrize('quiet', [True, False])
def test_pipenv_run_pip_freeze_has_expected_output(quiet, PipenvInstance):
    with PipenvInstance() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
    [packages]
    requests = "==2.14.0"
                """.strip()
            f.write(contents)
        c = p.pipenv('install')
        assert c.returncode == 0

        if quiet:
            c = p.pipenv('run --quiet pip freeze')
        else:
            c = p.pipenv('run pip freeze')
        assert c.returncode == 0
        assert 'requests==2.14.0\n' == c.stdout
