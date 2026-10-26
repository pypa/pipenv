"""The Pipfile and Pipfile.lock are UTF-8 whatever the locale encoding is.

``Pipfile.read()`` and ``Lockfile.load()`` already decode them as
``utf-8-sig``. These tests cover the other places that read or write them,
which used the locale encoding (e.g. cp1252 or cp932 on Windows) and so
crashed on, or re-encoded, a Pipfile with non-ASCII text in it, and did not
accept a byte order mark.
"""

import io
import json

import pytest

from pipenv.project import Project
from pipenv.utils.locking import Lockfile
from pipenv.vendor import plette

PIPFILE = """\
# 社内ライブラリはローカルのパスから入れる
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"
mylib = {path = "./ライブラリ/mylib", editable = true}

[dev-packages]
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


@pytest.fixture(params=["utf-8", "utf-8-sig"])
def project(request, tmp_path, monkeypatch):
    (tmp_path / "Pipfile").write_text(PIPFILE, encoding=request.param)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    return Project(chdir=False)


@pytest.mark.utils
def test_calculate_hash_decodes_pipfile_as_utf8(project):
    expected = plette.Pipfile.load(io.StringIO(PIPFILE)).get_hash().value
    assert project.pipfile.calculate_hash() == expected


@pytest.mark.utils
def test_write_toml_writes_pipfile_as_utf8(project, tmp_path):
    project.pipfile.write_toml(project.pipfile.parsed)
    contents = (tmp_path / "Pipfile").read_text(encoding="utf-8")
    assert "# 社内ライブラリはローカルのパスから入れる" in contents
    assert "./ライブラリ/mylib" in contents


@pytest.mark.utils
def test_lockfile_without_meta_reads_pipfile_as_utf8(project, tmp_path):
    (tmp_path / "Pipfile.lock").write_text(json.dumps({"default": {}}))
    loaded = project.lockfile.load(expand_env_vars=False)
    assert loaded["_meta"]["sources"][0]["name"] == "pypi"


@pytest.mark.utils
def test_lockfile_as_dict_without_lockfile_reads_pipfile_as_utf8(project):
    lockfile = project.lockfile.as_dict()
    assert lockfile["_meta"]["sources"][0]["name"] == "pypi"


@pytest.mark.utils
def test_locking_lockfile_load_reads_pipfile_lock_with_bom(tmp_path):
    (tmp_path / "Pipfile").write_text(PIPFILE, encoding="utf-8")
    path = tmp_path / "Pipfile.lock"
    path.write_text(json.dumps(LOCKFILE), encoding="utf-8-sig")
    lockfile = Lockfile.load(str(path))
    # Not mistaken for a corrupt lockfile, backed up and regenerated.
    assert lockfile.lockfile._data["_meta"]["hash"]["sha256"] == "abc123"
    assert not (tmp_path / "Pipfile.lock.bak").exists()
