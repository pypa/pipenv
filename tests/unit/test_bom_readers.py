"""Files saved as UTF-8 with a byte order mark (BOM) must load like any other.

Editors such as Windows Notepad add a BOM when saving as UTF-8. Reading with
``encoding="utf-8"`` keeps it as a leading ``\\ufeff`` that the TOML and JSON
parsers reject, so each reader decodes with ``utf-8-sig``.
"""

import json

import pytest

from pipenv.project import Project
from pipenv.utils.pipfile import ProjectFile
from pipenv.utils.pylock import PylockFile
from pipenv.vendor import plette

PIPFILE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"

[dev-packages]
"""

PYLOCK = """\
lock-version = '1.0'
created-by = 'test-tool'

[[packages]]
name = 'requests'
version = '2.28.1'
"""

PYPROJECT = """\
[project]
name = "my-project"
version = "1.0.0"
requires-python = ">=3.9"
dependencies = ["requests>=2.28.0"]
"""

LOCKFILE = {
    "_meta": {
        "hash": {"sha256": "abc123"},
        "pipfile-spec": 6,
        "requires": {},
        "sources": [
            {"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}
        ],
    },
    "default": {"requests": {"version": "==2.28.1"}},
    "develop": {},
}


def write_bom(path, text):
    path.write_text(text, encoding="utf-8-sig")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    return path


@pytest.mark.utils
def test_project_file_reads_pipfile_with_bom(tmp_path):
    path = write_bom(tmp_path / "Pipfile", PIPFILE)
    project_file = ProjectFile.read(path, plette.Pipfile)
    assert "requests" in project_file.model.packages


@pytest.mark.utils
def test_project_pipfile_parses_pipfile_with_bom(tmp_path, monkeypatch):
    write_bom(tmp_path / "Pipfile", PIPFILE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    project = Project(chdir=False)
    assert "requests" in project.pipfile.parsed["packages"]


@pytest.mark.utils
def test_pylock_from_path_reads_file_with_bom(tmp_path):
    path = write_bom(tmp_path / "pylock.toml", PYLOCK)
    pylock = PylockFile.from_path(path)
    assert [p["name"] for p in pylock.packages] == ["requests"]


@pytest.mark.utils
def test_pylock_from_pyproject_reads_file_with_bom(tmp_path):
    path = write_bom(tmp_path / "pyproject.toml", PYPROJECT)
    pylock = PylockFile.from_pyproject(path)
    assert pylock.requires_python == ">=3.9"


@pytest.mark.utils
def test_pylock_from_lockfile_reads_pipfile_lock_with_bom(tmp_path):
    path = write_bom(tmp_path / "Pipfile.lock", json.dumps(LOCKFILE))
    pylock = PylockFile.from_lockfile(path, tmp_path / "pylock.toml")
    assert [p["name"] for p in pylock.packages] == ["requests"]


@pytest.mark.utils
def test_lockfile_load_reads_pipfile_lock_with_bom(tmp_path, monkeypatch):
    (tmp_path / "Pipfile").write_text(PIPFILE)
    write_bom(tmp_path / "Pipfile.lock", json.dumps(LOCKFILE))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    project = Project(chdir=False)
    loaded = project.lockfile.load(expand_env_vars=False)
    assert loaded["_meta"]["hash"]["sha256"] == "abc123"
