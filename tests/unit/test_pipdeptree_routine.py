"""Tests for the pipdeptree installation logic in pipenv routines."""

from __future__ import annotations

import sys
from unittest import mock

import pytest

from pipenv.routines import graph


@pytest.fixture
def graph_project():
    proj = mock.MagicMock()
    proj.s.is_quiet.return_value = True
    proj.venv_locator.exists = True
    proj.venv_locator.python.return_value = "/venv/bin/python"
    return proj


def test_pipdeptree_exits_non_zero_when_not_installed_and_no_opt_in(
    monkeypatch, graph_project
):
    """Test that the graph command exits cleanly when pipdeptree can't be installed."""
    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: False)
    monkeypatch.delenv("PIPENV_AUTO_INSTALL_PIPDEPTREE", raising=False)
    run = mock.MagicMock()
    monkeypatch.setattr(graph, "run_command", run)

    with pytest.raises(SystemExit) as exc:
        graph.do_graph(graph_project)

    assert exc.value.code == 1
    run.assert_not_called()


def test_pipdeptree_non_interactive_auto_install(monkeypatch, graph_project):
    """Test that in a non-interactive environment, auto-install opt-in works."""
    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: False)
    monkeypatch.setenv("PIPENV_AUTO_INSTALL_PIPDEPTREE", "1")
    run = mock.MagicMock()
    run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(graph, "run_command", run)

    with mock.patch.object(sys.stdin, "isatty", return_value=False):
        with pytest.raises(SystemExit):
            graph.do_graph(graph_project)

    # Auto-install path was taken (run_command was called for pip install).
    assert run.called


def test_pipdeptree_runs_when_already_installed(monkeypatch, graph_project):
    """Test that pipdeptree runs directly when already installed."""
    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: True)
    run = mock.MagicMock()
    run.return_value = mock.Mock(
        returncode=0, stdout="requests==2.31.0\n", stderr=""
    )
    monkeypatch.setattr(graph, "run_command", run)

    with pytest.raises(SystemExit) as exc:
        graph.do_graph(graph_project)

    assert exc.value.code == 0
    cmd = run.call_args.args[0]
    assert "-m" in cmd and "pipdeptree" in cmd
