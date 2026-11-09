"""Tests for the pipdeptree installation logic in pipenv routines."""

from __future__ import annotations

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


def test_pipdeptree_exits_non_zero_when_not_installed_and_install_fails(
    monkeypatch, graph_project
):
    """Test that pipdeptree command exits when installation fails."""
    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: False)
    monkeypatch.setattr(graph, "install_pipdeptree", lambda *a, **kw: False)
    run = mock.MagicMock()
    monkeypatch.setattr(graph, "run_command", run)

    with pytest.raises(SystemExit) as exc:
        graph.do_graph(graph_project)

    assert exc.value.code == 1
    run.assert_not_called()


def test_pipdeptree_exits_non_zero_when_installed_but_fails_after_install(
    monkeypatch, graph_project
):
    """Test that pipdeptree command exits when installation succeeds but module is still not found."""
    # Not found before the install, still not found after it "succeeded".
    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: False)
    monkeypatch.setattr(graph, "install_pipdeptree", lambda *a, **kw: True)
    run = mock.MagicMock()
    monkeypatch.setattr(graph, "run_command", run)

    with pytest.raises(SystemExit) as exc:
        graph.do_graph(graph_project)

    assert exc.value.code == 1
    run.assert_not_called()


def test_pipdeptree_installs_and_runs_when_not_installed(monkeypatch, graph_project):
    """Test that pipdeptree installs and runs when not installed."""
    # Not found before the install, then found after installation.
    calls = {"n": 0}

    def fake_check(*a, **kw):
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(graph, "is_pipdeptree_installed", fake_check)
    monkeypatch.setattr(graph, "install_pipdeptree", lambda *a, **kw: True)
    run = mock.MagicMock()
    run.return_value = mock.Mock(
        returncode=0, stdout="requests==2.31.0\n", stderr=""
    )
    monkeypatch.setattr(graph, "run_command", run)

    # do_graph always terminates via sys.exit; exit code 0 means success.
    with pytest.raises(SystemExit) as exc:
        graph.do_graph(graph_project)

    assert exc.value.code == 0
    cmd = run.call_args.args[0]
    assert "-m" in cmd and "pipdeptree" in cmd


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
