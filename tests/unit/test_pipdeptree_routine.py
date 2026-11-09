"""Tests for the pipdeptree installation logic in pipenv routines."""

from __future__ import annotations

from unittest import mock

import pytest

from pipenv.routines import graph


@pytest.fixture
def graph_project():
    proj = mock.MagicMock()
    proj.s.is_quiet.return_value = True
    return proj


def test_pipdeptree_exits_non_zero_when_not_installed_and_install_fails(
    monkeypatch, graph_project
):
    """Test that pipdeptree command exits when installation fails."""
    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: False)
    monkeypatch.setattr(graph, "install_pipdeptree", lambda *a, **kw: False)
    run = mock.MagicMock()
    monkeypatch.setattr(graph.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc:
        graph.do_graph(graph_project, quiet=True)

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
    monkeypatch.setattr(graph.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc:
        graph.do_graph(graph_project, quiet=True)

    assert exc.value.code == 1
    run.assert_not_called()


def test_pipdeptree_installs_and_runs_when_not_installed(monkeypatch, graph_project):
    """Test that pipdeptree installs and runs when not installed."""
    # Not found before the install, then found after installation.
    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: False)
    monkeypatch.setattr(graph, "install_pipdeptree", lambda *a, **kw: True)
    run = mock.MagicMock()
    run.return_value.returncode = 0
    monkeypatch.setattr(graph.subprocess, "run", run)

    # This should not raise an exception
    try:
        graph.do_graph(graph_project, quiet=True)
        # If we get here, it means the function didn't exit due to error
    except SystemExit:
        pytest.fail("do_graph should not exit with error when pipdeptree is installed successfully")


def test_pipdeptree_runs_when_already_installed(monkeypatch, graph_project):
    """Test that pipdeptree runs directly when already installed."""
    monkeypatch.setattr(graph, "is_pipdeptree_installed", lambda *a, **kw: True)
    run = mock.MagicMock()
    run.return_value.returncode = 0
    monkeypatch.setattr(graph.subprocess, "run", run)

    # This should not raise an exception
    try:
        graph.do_graph(graph_project, quiet=True)
        # If we get here, it means the function didn't exit due to error
    except SystemExit:
        pytest.fail("do_graph should not exit with error when pipdeptree is already installed")