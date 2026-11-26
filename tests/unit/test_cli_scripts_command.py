"""``pipenv scripts`` must report malformed ``[scripts]`` entries, not crash.

``pipenv run <name>`` already turns a ``[scripts]`` entry that is neither a
string, a list of strings, nor an inline table into a one-line error via
``Script.parse()`` (``ScriptParseError`` / ``ScriptEmptyError``).  The
listing command read the raw TOML values instead, so the very same Pipfile
made ``pipenv scripts`` die with an unhandled ``TypeError``.
"""

import pytest

from pipenv.cli.command import cmd_scripts
from pipenv.vendor import tomlkit


def _state(pipfile_text):
    from unittest import mock

    project = mock.MagicMock()
    project.pipfile.exists = True
    project.pipfile.parsed = tomlkit.loads(pipfile_text)
    state = mock.MagicMock()
    state.project = project
    return state


@pytest.mark.cli
@pytest.mark.script
def test_string_entry_still_lists(capsys):
    cmd_scripts(None, _state('[scripts]\ntest = "pytest -x"\n'))
    assert "pytest -x" in capsys.readouterr().out


@pytest.mark.cli
@pytest.mark.script
@pytest.mark.parametrize("value", ["42", "true"])
def test_non_string_entry_reports_instead_of_raising(capsys, value):
    with pytest.raises(SystemExit) as excinfo:
        cmd_scripts(None, _state(f"[scripts]\nbad = {value}\n"))

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Can't list script 'bad'" in captured.err
    assert "Traceback" not in captured.err
