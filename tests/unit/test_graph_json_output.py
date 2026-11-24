"""``pipenv graph --json`` output must stay valid JSON whatever the terminal width."""

import io
import json
import sys
from unittest import mock

import pytest

from pipenv.patched.pip._vendor.rich.console import Console
from pipenv.routines import graph
from pipenv.routines.graph import do_graph

LONG_NAME = "a-very-long-package-name-" + "x" * 75  # 100 characters

JSON_OUTPUT = json.dumps(
    [
        {
            "package": {
                "key": LONG_NAME,
                "package_name": LONG_NAME,
                "installed_version": "1.0.0",
            },
            "dependencies": [],
        }
    ]
)
JSON_TREE_OUTPUT = json.dumps(
    [
        {
            "key": LONG_NAME,
            "package_name": LONG_NAME,
            "installed_version": "1.0.0",
            "required_version": "1.0.0",
            "dependencies": [],
        }
    ]
)


@pytest.mark.parametrize(
    ("kwargs", "stdout"),
    [
        ({"json": True}, JSON_OUTPUT),
        ({"json_tree": True}, JSON_TREE_OUTPUT),
        ({"json": True, "bare": True}, JSON_OUTPUT),
    ],
)
def test_graph_json_is_not_wrapped_by_rich(monkeypatch, kwargs, stdout):
    buffer = io.StringIO()
    # A narrow, non-terminal console wraps long lines unless told not to.
    console = Console(file=buffer, width=80, force_terminal=False)
    monkeypatch.setattr(graph, "console", console)
    monkeypatch.setattr(sys, "stdout", buffer)
    result = mock.MagicMock(stdout=stdout, stderr="", returncode=0)
    monkeypatch.setattr(graph, "run_command", lambda *a, **k: result)
    project = mock.MagicMock()
    project.venv_locator.python.return_value = sys.executable
    project.venv_locator.exists = True
    project.s.is_verbose.return_value = False

    with pytest.raises(SystemExit) as excinfo:
        do_graph(project, **kwargs)

    assert excinfo.value.code == 0
    parsed = json.loads(buffer.getvalue())
    assert LONG_NAME in json.dumps(parsed)
