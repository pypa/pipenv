"""Tests that ``pipenv check`` / ``pipenv scan`` fail when safety cannot be used."""

from __future__ import annotations

from unittest import mock

import pytest

from pipenv.routines import check, scan


@pytest.fixture(params=[check, scan], ids=["check", "scan"])
def routine(request, monkeypatch):
    mod = request.param
    monkeypatch.setattr(mod, "run_pep508_check", lambda *a, **kw: {})
    monkeypatch.setattr(mod, "check_pep508_requirements", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "get_requirements", lambda *a, **kw: mock.Mock(stdout="requests==2.0\n"))
    monkeypatch.setattr(mod, "create_temp_requirements_file", lambda *a, **kw: "reqs.txt", raising=False)
    monkeypatch.setattr(mod, "create_temp_requirements", lambda *a, **kw: mock.Mock(name="t"), raising=False)
    monkeypatch.setattr(mod, "build_safety_options", lambda *a, **kw: [], raising=False)
    monkeypatch.setattr(mod.os, "unlink", lambda *a, **kw: None, raising=False)
    return mod


@pytest.fixture
def project():
    proj = mock.MagicMock()
    proj.s.is_quiet.return_value = True
    proj.lockfile.exists = True
    return proj


def _run(mod, project):
    func = mod.do_scan if mod is scan else mod.do_check
    func(project, system=True, quiet=True, auto_install=True)


def test_exits_non_zero_when_safety_install_fails(routine, project, monkeypatch):
    monkeypatch.setattr(routine, "is_safety_installed", lambda *a, **kw: False)
    monkeypatch.setattr(routine, "run_command", lambda *a, **kw: mock.Mock(returncode=1))
    monkeypatch.setattr(routine, "project_python", lambda *a, **kw: "python")

    with pytest.raises(SystemExit) as exc:
        _run(routine, project)

    assert exc.value.code == 1


def test_exits_non_zero_when_safety_missing_after_install(routine, project, monkeypatch):
    monkeypatch.setattr(routine, "is_safety_installed", lambda *a, **kw: False)
    monkeypatch.setattr(routine, "install_safety", lambda *a, **kw: True)
    monkeypatch.setattr(routine, "project_python", lambda *a, **kw: "python")
    monkeypatch.setattr("subprocess.check_call", lambda *a, **kw: 0)

    with pytest.raises(SystemExit) as exc:
        _run(routine, project)

    assert exc.value.code == 1
