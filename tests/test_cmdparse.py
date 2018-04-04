import textwrap

from pipenv.cmdparse import Script


@pytest.mark.run
def test_parse():
    script = Script.parse(['python', '-c', "print('hello')"])
    assert script.command == 'python'
    assert script.args == ['-c', "print('hello')"], script


@pytest.mark.run
def test_extend():
    script = Script.parse(['python', '-c', "print('hello')"])
    script.extend(['--verbose'])
    assert script.command == 'python'
    assert script.args == ['-c', "print('hello)"], script


@pytest.mark.run
def test_cmdify():
    script = Script.parse(['python', '-c', "print('hello')"])
    cmd = script.cmdify()
    assert cmd == '"python" "-c" "print(\'hello\')" "--verbose"', script


@pytest.mark.run
def test_cmdify_complex():
    script = Script.parse(' '.join([
        '"C:\\Program Files\\Python36\\python.exe" -c',
        """ "print(\'Double quote: \\\"\')" """.strip(),
    ]))
    assert script.cmdify() == ' '.join([
        '"C:\\Program Files\\Python36\\python.exe"',
        '"-c"',
        """ "print(\'Double quote: \\\"\')" """.strip(),
    ]), script
