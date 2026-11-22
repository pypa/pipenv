"""The direct ``pip install safety`` retry in check/scan must actually run."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from pipenv.routines import check, scan


def _patch_common(monkeypatch, module):
    monkeypatch.setattr(module, "run_pep508_check", lambda *a, **kw: {})
    monkeypatch.setattr(module, "check_pep508_requirements", lambda *a, **kw: None)
    monkeypatch.setattr(
        module, "get_requirements", lambda *a, **kw: SimpleNamespace(stdout="x==1")
    )
    monkeypatch.setattr(
        module,
        "create_temp_requirements",
        lambda *a, **kw: Path("does-not-exist-req.txt"),
        raising=False,
    )
    monkeypatch.setattr(
        module, "create_temp_requirements_file", lambda *a, **kw: "req.txt", raising=False
    )
    monkeypatch.setattr(module, "project_python", lambda *a, **kw: "python")
    monkeypatch.setattr(module, "install_safety", lambda *a, **kw: True)
    # Not installed before, still "not found" right after the install reported success.
    monkeypatch.setattr(module, "is_safety_installed", lambda *a, **kw: False)


@pytest.mark.parametrize(
    "module, func", [(check, check.do_check), (scan, scan.do_scan)]
)
def test_direct_pip_install_retry_runs(monkeypatch, module, func):
    _patch_common(monkeypatch, module)

    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    # ``check_call`` forwards to ``Popen``, which has no ``capture_output``.
    real_popen = subprocess.Popen

    def strict_popen(*args, **kwargs):
        if "capture_output" in kwargs:
            raise TypeError("unexpected keyword argument 'capture_output'")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", strict_popen)

    proj = mock.MagicMock()
    proj.s.is_quiet.return_value = True
    with pytest.raises(SystemExit):
        func(proj, system=True, quiet=True)

    assert len(calls) == 1
    assert calls[0][1:4] == ["-m", "pip", "install"]
