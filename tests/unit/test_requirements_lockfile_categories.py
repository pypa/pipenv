"""``pipenv requirements --categories`` accepts lockfile section names in every mode."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = {"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}
PIPFILE = (
    '[[source]]\nurl = "https://pypi.org/simple"\nname = "pypi"\nverify_ssl = true\n'
    '\n[packages]\nrequests = "==2.32.3"\n'
    '\n[dev-packages]\npytest = "==8.3.4"\n'
)
LOCK = {
    "_meta": {"sources": [SOURCE], "hash": {"sha256": "0" * 64}, "pipfile-spec": 6},
    "default": {"requests": {"version": "==2.32.3"}, "idna": {"version": "==3.10"}},
    "develop": {"pytest": {"version": "==8.3.4"}, "pluggy": {"version": "==1.5.0"}},
}


@pytest.mark.parametrize("mode", ["--from-pipfile", "--no-lock"])
@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("default", "requests==2.32.3"),
        ("packages", "requests==2.32.3"),
        ("develop", "pytest==8.3.4"),
        ("dev-packages", "pytest==8.3.4"),
    ],
)
def test_requirements_categories_lockfile_section_names(tmp_path, mode, category, expected):
    source = Path(__file__).resolve().parents[2]
    (tmp_path / "Pipfile").write_text(PIPFILE)
    (tmp_path / "Pipfile.lock").write_text(json.dumps(LOCK))
    env = os.environ.copy()
    env.update(PYTHONPATH=str(source), PIPENV_PIPFILE=str(tmp_path / "Pipfile"), PIPENV_IGNORE_VIRTUALENVS="1", PIPENV_DONT_LOAD_ENV="1")
    args = [sys.executable, "-m", "pipenv", "requirements", "--categories", category, mode]
    result = subprocess.run(args, cwd=tmp_path, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["-i https://pypi.org/simple", expected]
