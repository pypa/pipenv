"""``pipenv graph`` draws its tree with characters that stdout can encode."""

import io
import sys
from unittest import mock

import pytest

from pipenv.routines.graph import do_graph


@pytest.mark.parametrize(
    ("encoding", "branch"),
    [
        ("utf-8", "── pluggy [required: "),
        ("cp1252", "  - pluggy [required: "),
    ],
)
def test_graph_tree_uses_characters_stdout_can_encode(monkeypatch, encoding, branch):
    # On Windows, piped or redirected stdout uses the locale encoding, e.g. cp1252.
    stdout = io.TextIOWrapper(io.BytesIO(), encoding=encoding)
    monkeypatch.setattr(sys, "stdout", stdout)
    project = mock.MagicMock()
    project.venv_locator.python.return_value = sys.executable
    project.venv_locator.exists = True
    project.s.is_verbose.return_value = False

    with pytest.raises(SystemExit) as excinfo:
        do_graph(project)

    assert excinfo.value.code == 0
    stdout.flush()
    assert branch in stdout.buffer.getvalue().decode(encoding)
