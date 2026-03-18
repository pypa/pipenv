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
