"""Tests for the exit status of ``pipenv.routines.audit.do_audit``."""

from __future__ import annotations

from unittest import mock

import pytest

from pipenv.routines import audit


@pytest.fixture
def audit_project():
    proj = mock.MagicMock()
    proj.s.is_quiet.return_value = True
    return proj


def test_audit_exits_non_zero_when_pip_audit_is_not_installed(
    monkeypatch, audit_project
):
    monkeypatch.setattr(audit, "is_pip_audit_installed", lambda *a, **kw: False)
    monkeypatch.setattr(audit, "install_pip_audit", lambda *a, **kw: False)
    run = mock.MagicMock()
    monkeypatch.setattr(audit.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc:
        audit.do_audit(audit_project, system=True, quiet=True)

    assert exc.value.code == 1
    run.assert_not_called()


def test_audit_exits_non_zero_when_pip_audit_is_missing_after_install(
    monkeypatch, audit_project
):
    # Not found before the install, still not found after it "succeeded".
    monkeypatch.setattr(audit, "is_pip_audit_installed", lambda *a, **kw: False)
    monkeypatch.setattr(audit, "install_pip_audit", lambda *a, **kw: True)
    run = mock.MagicMock()
    monkeypatch.setattr(audit.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc:
        audit.do_audit(audit_project, system=True, quiet=True)

    assert exc.value.code == 1
    run.assert_not_called()
