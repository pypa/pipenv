"""``pipenv graph`` reports a missing virtualenv and exits with 1."""

from unittest import mock

import pytest

from pipenv.routines import graph


def test_graph_without_virtualenv_exits_with_error(monkeypatch, capsys):
    project = mock.MagicMock()
    project.venv_locator.python.return_value = "/venv/bin/python"
    project.venv_locator.exists = False

    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: True)

    with pytest.raises(SystemExit) as excinfo:
        graph.do_graph(project)

    assert excinfo.value.code == 1
    assert "No virtualenv has been created" in capsys.readouterr().err
