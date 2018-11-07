import pytest

from pipenv.cmdparse import Script, ScriptEmptyError


@pytest.mark.run
@pytest.mark.script
def test_parse():
    script = Script.parse(['python', '-c', "print('hello')"])
    assert script.command == 'python'
    assert script.args == ['-c', "print('hello')"], script


@pytest.mark.run
@pytest.mark.script
def test_parse_error():
    with pytest.raises(ScriptEmptyError) as e:
        Script.parse('')
    assert str(e.value) == "[]"


@pytest.mark.run
def test_extend():
    script = Script('python', ['-c', "print('hello')"])
    script.extend(['--verbose'])
    assert script.command == 'python'
    assert script.args == ['-c', "print('hello')", "--verbose"], script


@pytest.mark.run
@pytest.mark.script
def test_cmdify():
    script = Script('python', ['-c', "print('hello world')"])
    cmd = script.cmdify()
    assert cmd == 'python -c "print(\'hello world\')"', script


@pytest.mark.run
@pytest.mark.script
def test_cmdify_complex():
    script = Script.parse(' '.join([
        '"C:\\Program Files\\Python36\\python.exe" -c',
        """ "print(\'Double quote: \\\"\')" """.strip(),
    ]))
    assert script.cmdify() == ' '.join([
        '"C:\\Program Files\\Python36\\python.exe"',
        '-c',
        """ "print(\'Double quote: \\\"\')" """.strip(),
    ]), script


@pytest.mark.run
@pytest.mark.script
def test_cmdify_quote_if_paren_in_command():
    """Ensure ONLY the command is quoted if it contains parentheses.
    """
    script = Script.parse(' '.join([
        '"C:\\Python36(x86)\\python.exe"',
        '-c',
        "print(123)",
    ]))
    assert script.cmdify() == ' '.join([
        '"C:\\Python36(x86)\\python.exe"',
        '-c',
        "print(123)",
    ]), script
