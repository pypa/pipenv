# -*- coding: utf-8 -*-
import io
import os

from pipenv.project import Project

import pytest


@pytest.mark.run
@pytest.mark.dotenv
def test_env(PipenvInstance):
    with PipenvInstance(pipfile=False, chdir=True) as p:
        with io.open('.env', 'w', encoding='utf-8') as f:
            f.write(u'HELLO=WORLD\n')
            f.write(u'HI=世界\n')

        c = p.pipenv('run python -c "import os; print(os.environ[\'HELLO\'])"')
        assert c.return_code == 0
        assert 'WORLD' in c.out

        c = p.pipenv('run python -c "import os; print(os.environ[\'HI\'])"')
        assert c.return_code == 0
        # The output varies too much from platform to platform.
        # As long as it prints (return code 0) I guess it's fine.
        # Feel free to contribute a robust assertion if you feel like it.


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
