import pytest

from pipenv.cmdparse import Script, ScriptEmptyError, ScriptParseError

# ---------------------------------------------------------------------------
# Single-command parse
# ---------------------------------------------------------------------------


@pytest.mark.run
@pytest.mark.script
def test_parse_string():
    script = Script.parse("python -c \"print('hello')\"")
    assert script.command == "python"
    assert script.args == ["-c", "print('hello')"]
    assert not script.is_sequence


@pytest.mark.run
@pytest.mark.script
def test_parse_error():
    with pytest.raises(ScriptEmptyError) as e:
        Script.parse("")
    assert str(e.value) == "[]"


@pytest.mark.run
def test_extend():
    script = Script("python", ["-c", "print('hello')"])
    script.extend(["--verbose"])
    assert script.command == "python"
    assert script.args == ["-c", "print('hello')", "--verbose"], script


# ---------------------------------------------------------------------------
# Sequence (TOML array) parse  — issue #2283
# ---------------------------------------------------------------------------


@pytest.mark.run
@pytest.mark.script
def test_parse_sequence_basic():
    """A TOML array of command strings produces a sequential script."""
    script = Script.parse(["python --version", "python --help"])
    assert script.is_sequence
    assert len(script._sequence) == 2
    assert script._sequence[0].command == "python"
    assert script._sequence[0].args == ["--version"]
    assert script._sequence[1].command == "python"
    assert script._sequence[1].args == ["--help"]


@pytest.mark.run
@pytest.mark.script
def test_parse_sequence_single_item():
    """A one-element TOML array is still a valid (trivial) sequence."""
    script = Script.parse(["pytest -x"])
    assert script.is_sequence
    assert len(script._sequence) == 1
    assert script._sequence[0].command == "pytest"
    assert script._sequence[0].args == ["-x"]


@pytest.mark.run
@pytest.mark.script
def test_parse_sequence_outer_mirrors_first():
    """The outer Script's .command/.args reflect the first step (for logging)."""
    script = Script.parse(["ruff check .", "ruff format --check ."])
    assert script.command == "ruff"
    assert script.args == ["check", "."]


@pytest.mark.run
@pytest.mark.script
def test_parse_sequence_empty_list_raises():
    with pytest.raises(ScriptEmptyError):
        Script.parse([])


@pytest.mark.run
@pytest.mark.script
def test_parse_sequence_blank_element_raises():
    with pytest.raises(ScriptEmptyError):
        Script.parse(["pytest", ""])


@pytest.mark.run
@pytest.mark.script
def test_parse_sequence_non_string_element_raises():
    with pytest.raises(ScriptParseError):
        Script.parse(["pytest", 42])


@pytest.mark.run
@pytest.mark.script
def test_extend_sequence_appends_to_last():
    """Extra CLI args are appended to the last command in the sequence."""
    script = Script.parse(["ruff check .", "pytest"])
    script.extend(["-v", "--tb=short"])
    last = script._sequence[-1]
    assert last.command == "pytest"
    assert last.args == ["-v", "--tb=short"]
    # First command must be untouched
    assert script._sequence[0].args == ["check", "."]


@pytest.mark.run
@pytest.mark.script
def test_extend_non_sequence_unchanged():
    """extend() on a plain script still appends to _parts as before."""
    script = Script.parse("pytest -x")
    script.extend(["tests/"])
    assert not script.is_sequence
    assert script.args == ["-x", "tests/"]


@pytest.mark.run
@pytest.mark.script
def test_cmdify():
    script = Script("python", ["-c", "print('hello world')"])
    cmd = script.cmdify()
    assert cmd == "python -c \"print('hello world')\"", script


@pytest.mark.run
@pytest.mark.script
def test_cmdify_complex():
    script = Script.parse(
        " ".join(
            [
                '"C:\\Program Files\\Python36\\python.exe" -c',
                """ "print(\'Double quote: \\\"\')" """.strip(),
            ]
        )
    )
    assert script.cmdify() == " ".join(
        [
            '"C:\\Program Files\\Python36\\python.exe"',
            "-c",
            """ "print(\'Double quote: \\\"\')" """.strip(),
        ]
    ), script


@pytest.mark.run
@pytest.mark.script
def test_cmdify_quote_if_paren_in_command():
    """Ensure ONLY the command is quoted if it contains parentheses."""
    script = Script.parse('"C:\\Python36(x86)\\python.exe" -c print(123)')
    assert script.cmdify() == '"C:\\Python36(x86)\\python.exe" -c print(123)', script


@pytest.mark.run
@pytest.mark.script
def test_cmdify_quote_if_carets():
    """Ensure arguments are quoted if they contain carets."""
    script = Script("foo^bar", ["baz^rex"])
    assert script.cmdify() == '"foo^bar" "baz^rex"', script


# ---------------------------------------------------------------------------
# Inline env var extraction — issue #6083
# ---------------------------------------------------------------------------


@pytest.mark.run
@pytest.mark.script
def test_no_inline_env_vars_returns_self():
    """Scripts without a leading KEY=value are returned unchanged."""
    script = Script.parse("python -c 'print(1)'")
    new_script, env = script.with_extracted_env_vars()
    assert new_script is script
    assert env == {}


@pytest.mark.run
@pytest.mark.script
def test_single_inline_env_var_no_spaces():
    """A single KEY=value prefix (no spaces in value) is extracted."""
    script = Script.parse("DISABLE_API=1 sphinx-build -b html")
    new_script, env = script.with_extracted_env_vars()
    assert env == {"DISABLE_API": "1"}
    assert new_script.command == "sphinx-build"
    assert new_script.args == ["-b", "html"]


@pytest.mark.run
@pytest.mark.script
def test_multiple_inline_env_vars():
    """Multiple leading KEY=value tokens are all extracted."""
    script = Script.parse("FOO=bar BAZ=qux python script.py")
    new_script, env = script.with_extracted_env_vars()
    assert env == {"FOO": "bar", "BAZ": "qux"}
    assert new_script.command == "python"
    assert new_script.args == ["script.py"]


@pytest.mark.run
@pytest.mark.script
def test_inline_env_var_value_with_spaces():
    """A value that contained spaces (after shlex quote-stripping) is extracted correctly.

    When a Pipfile [scripts] entry like ``FOO='hello world' python -c ...``
    is parsed by shlex, the quotes are stripped and the token becomes
    ``FOO=hello world``.  with_extracted_env_vars must still recognise this
    as an env var and set FOO to the full value including the space.
    """
    # Simulate what Script.parse does with  FOO='hello world' python -c '...'
    script = Script("FOO=hello world", ["python", "-c", "import os; print(os.getenv('FOO'))"])
    new_script, env = script.with_extracted_env_vars()
    assert env == {"FOO": "hello world"}
    assert new_script.command == "python"
    assert new_script.args == ["-c", "import os; print(os.getenv('FOO'))"]


@pytest.mark.run
@pytest.mark.script
def test_inline_env_var_only_no_command_is_not_extracted():
    """If all tokens are KEY=value with no command left, nothing is extracted."""
    script = Script("FOO=bar")  # only token — can't strip it
    new_script, env = script.with_extracted_env_vars()
    assert new_script is script
    assert env == {}


@pytest.mark.run
@pytest.mark.script
def test_inline_env_var_empty_value():
    """An empty value (KEY=) is a valid env var and is extracted."""
    script = Script.parse("MY_VAR= python script.py")
    new_script, env = script.with_extracted_env_vars()
    assert env == {"MY_VAR": ""}
    assert new_script.command == "python"


@pytest.mark.run
@pytest.mark.script
def test_inline_env_var_not_extracted_from_args():
    """KEY=value tokens that are *not* at the start are left as regular args."""
    script = Script.parse("python script.py FOO=bar")
    new_script, env = script.with_extracted_env_vars()
    assert new_script is script
    assert env == {}
    assert new_script.args == ["script.py", "FOO=bar"]
