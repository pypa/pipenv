"""Tests for ``pipenv.routines.clean.remove_extraneous_packages``."""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def clean_project():
    proj = mock.MagicMock()
    proj.s.is_verbose.return_value = False
    proj.installed_package_names = ["six", "requests", "sphinx", "stale"]
    # A lockfile-only section ("docs") that the Pipfile does not declare.
    proj.lockfile.content = {
        "_meta": {"hash": {"sha256": "abc"}},
        "default": {"requests": {"version": "==2.32.0"}},
        "develop": {"six": {"version": "==1.16.0"}},
        "docs": {"Sphinx": {"version": "==8.0.0"}},
    }
    proj.pipfile.get_package_categories.return_value = ["default", "develop"]
    return proj


@pytest.fixture
def run_command(monkeypatch):
    m = mock.MagicMock()
    m.return_value.returncode = 0
    monkeypatch.setattr("pipenv.routines.clean.run_command", m)
    monkeypatch.setattr("pipenv.routines.clean.project_python", lambda *a, **k: "py")
    monkeypatch.setattr("pipenv.routines.clean.get_runnable_pip", lambda: "pip")
    return m


def _uninstalled(run_command):
    return [c.args[0][3] for c in run_command.call_args_list]


def test_keeps_every_lockfile_section(clean_project, run_command):
    from pipenv.routines.clean import remove_extraneous_packages

    assert remove_extraneous_packages(clean_project) is False
    assert _uninstalled(run_command) == ["stale"]


@pytest.mark.parametrize("bare", [False, True])
def test_dry_run_never_uninstalls(clean_project, run_command, bare):
    from pipenv.routines.clean import remove_extraneous_packages

    remove_extraneous_packages(clean_project, dry_run=True, bare=bare)
    run_command.assert_not_called()


def test_reports_uninstall_failure(clean_project, run_command):
    from pipenv.routines.clean import remove_extraneous_packages

    run_command.return_value.returncode = 1
    assert remove_extraneous_packages(clean_project) is True
