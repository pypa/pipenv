"""Offline public CLI regression for requirements mirror selection (#5270)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("no_lock", [False, True])
@pytest.mark.parametrize("selection", ["flag", "env", "precedence", "none", "excluded"])
def test_requirements_mirror(tmp_path, no_lock, selection):
    source = Path(__file__).resolve().parents[2]
    sources = [
        {"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True},
        {"url": "https://private.example/simple", "name": "private", "verify_ssl": True},
    ]
    pipfile = (
        "\n".join(f'[[source]]\nurl = "{s["url"]}"\nname = "{s["name"]}"\nverify_ssl = true\n' for s in sources)
        + '\n[packages]\nexample = "==1.2.3"\n'
    )
    lock = json.dumps(
        {
            "_meta": {"sources": sources, "hash": {"sha256": "0" * 64}, "pipfile-spec": 6},
            "default": {"example": {"version": "==1.2.3"}},
            "develop": {},
        }
    )
    (tmp_path / "Pipfile").write_text(pipfile)
    (tmp_path / "Pipfile.lock").write_text(lock)
    env = os.environ.copy()
    env.pop("PIPENV_PYPI_MIRROR", None)
    env.update(PYTHONPATH=str(source), PIPENV_PIPFILE=str(tmp_path / "Pipfile"), PIPENV_IGNORE_VIRTUALENVS="1", PIPENV_DONT_LOAD_ENV="1")
    args = [sys.executable, "-m", "pipenv", "requirements"]
    if no_lock:
        args.append("--no-lock")
    if selection in ("env", "precedence"):
        env["PIPENV_PYPI_MIRROR"] = "https://env.example/simple"
    if selection in ("flag", "precedence", "excluded"):
        args.extend(["--pypi-mirror", "https://flag.example/simple"])
    if selection == "excluded":
        args.append("--exclude-index")
    result = subprocess.run(args, cwd=tmp_path, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    if selection == "excluded":
        assert lines == ["example==1.2.3"]
    else:
        host = "env" if selection == "env" else "flag"
        index = "https://pypi.org/simple" if selection == "none" else f"https://{host}.example/simple"
        assert lines == [f"-i {index}", "--extra-index-url https://private.example/simple", "example==1.2.3"]
    assert (tmp_path / "Pipfile").read_text() == pipfile
    assert (tmp_path / "Pipfile.lock").read_text() == lock
