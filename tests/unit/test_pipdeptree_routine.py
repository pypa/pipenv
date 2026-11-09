"""Tests for the on-demand pipdeptree install in the graph routine."""

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


def test_graph_exits_when_pipdeptree_install_fails(monkeypatch, graph_project):
    """When pipdeptree is missing and installing it fails, graph must abort."""
    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: False)
    # Simulate the install command failing (run_command returns non-zero).
    run = mock.MagicMock(return_value=mock.Mock(returncode=1, stdout="", stderr=""))
    monkeypatch.setattr(graph, "run_command", run)

    with pytest.raises(SystemExit) as exc:
        graph.do_graph(graph_project)

    assert exc.value.code == 1


def test_graph_installs_then_runs_when_missing(monkeypatch, graph_project):
    """When pipdeptree is missing it is installed, then the tree is printed."""
    calls = {"n": 0}

    def fake_check(*a, **kw):
        calls["n"] += 1
        return calls["n"] > 1  # not installed before, installed after

    monkeypatch.setattr(graph, "is_pipdeptree_installed", fake_check)

    run = mock.MagicMock()
    # First call is the `pip install pipdeptree` step; the second is the
    # actual `pipdeptree` invocation that prints the tree.
    run.side_effect = [
        mock.Mock(returncode=0, stdout="", stderr=""),
        mock.Mock(returncode=0, stdout="requests==2.31.0\n", stderr=""),
    ]
    monkeypatch.setattr(graph, "run_command", run)

    with pytest.raises(SystemExit) as exc:
        graph.do_graph(graph_project)

    assert exc.value.code == 0
    # The first run_command call must have been the install step.
    install_cmd = run.call_args_list[0].args[0]
    assert "install" in install_cmd and "pipdeptree>=2.0.0" in install_cmd


def test_graph_runs_when_already_installed(monkeypatch, graph_project):
    """When pipdeptree is already present it is run directly (no install)."""
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
    run.assert_called_once()
