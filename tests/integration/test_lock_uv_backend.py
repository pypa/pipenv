"""Integration tests for the ``uv`` resolver backend (gh-6109).

Skipped unless a ``uv`` binary is on ``$PATH``.  Both tests use the
offline ``file://`` index fixture, so they need no network access.
"""
import shutil

import pytest

pytestmark = [
    pytest.mark.lock,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed"),
]


def _strip_requires_python_markers(section):
    """The pip backend AND-merges each package's Requires-Python into
    ``markers``; uv doesn't report Requires-Python.  Drop markers that
    consist only of ``python_version`` clauses before comparing."""
    cleaned = {}
    for name, entry in section.items():
        entry = dict(entry)
        markers = entry.get("markers", "")
        if markers and all(
            clause.strip().startswith("python_version")
            for clause in markers.split(" and ")
        ):
            del entry["markers"]
        cleaned[name] = entry
    return cleaned


def test_uv_backend_matches_pip_backend(pipenv_instance_file_pypi):
    with pipenv_instance_file_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            f.write(
                f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "testindex"

[packages]
requests = "==2.19.1"
colorama = {{version = "*", markers = "sys_platform == 'win32'"}}

[dev-packages]
six = "*"
"""
            )
        c = p.pipenv("lock --backend pip")
        assert c.returncode == 0, c.stderr
        pip_lock = p.lockfile

        c = p.pipenv("lock --backend uv")
        assert c.returncode == 0, c.stderr
        uv_lock = p.lockfile

        for section in ("default", "develop"):
            assert _strip_requires_python_markers(
                uv_lock[section]
            ) == _strip_requires_python_markers(pip_lock[section])


def test_uv_backend_reports_conflicts(pipenv_instance_file_pypi):
    with pipenv_instance_file_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            f.write(
                f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "testindex"

[packages]
requests = "==2.19.1"
urllib3 = "==1.20"
"""
            )
        c = p.pipenv("lock --backend uv")
        assert c.returncode != 0
        assert "No solution found" in c.stderr
