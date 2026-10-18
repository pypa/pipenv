"""Offline public CLI regression: index URLs keep pip-expandable ${VAR} placeholders (#5272)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("no_lock", [False, True])
def test_requirements_braces_bare_env_vars_in_index_urls(tmp_path, no_lock):
    source = Path(__file__).resolve().parents[2]
    url = "https://$PRIVATE_TOKEN@private.example/simple"
    (tmp_path / "Pipfile").write_text(
        f'[[source]]\nurl = "{url}"\nname = "private"\nverify_ssl = true\n\n[packages]\nexample = "==1.2.3"\n'
    )
    (tmp_path / "Pipfile.lock").write_text(
        json.dumps(
            {
                "_meta": {
                    "sources": [{"url": url, "name": "private", "verify_ssl": True}],
                    "hash": {"sha256": "0" * 64},
                    "pipfile-spec": 6,
                },
                "default": {"example": {"version": "==1.2.3", "index": "private"}},
                "develop": {},
            }
        )
    )
    env = os.environ.copy()
    env.pop("PIPENV_PYPI_MIRROR", None)
    env.update(
        PYTHONPATH=str(source),
        PIPENV_PIPFILE=str(tmp_path / "Pipfile"),
        PIPENV_IGNORE_VIRTUALENVS="1",
        PIPENV_DONT_LOAD_ENV="1",
    )
    args = [sys.executable, "-m", "pipenv", "requirements"]
    if no_lock:
        args.append("--no-lock")

    result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, check=True)

    # pip only expands the braced ${VAR} form in requirements files
    assert "-i https://${PRIVATE_TOKEN}@private.example/simple" in result.stdout.splitlines()
