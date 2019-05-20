# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import os

import pytest

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

        with temp_environ():
            os.environ['HELLO'] = 'WORLD'
            c = p.pipenv("run scriptwithenv")
            assert c.ok
            if os.name != "nt":  # This doesn't work on CI windows.
                assert c.out.strip() == "WORLD"
