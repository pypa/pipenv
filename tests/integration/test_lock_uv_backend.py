"""Integration tests for the ``uv`` resolver backend (gh-6109).

Skipped unless a ``uv`` binary is on ``$PATH``.  Both tests use the
offline ``file://`` index fixture or indexes they generate, so they need
no network access.
"""
import hashlib
import shutil
import subprocess
import zipfile
from pathlib import Path

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


def _write_wheel(directory, name, version, requires=()):
    """Write a minimal wheel into ``directory`` and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / f"{name}-{version}-py3-none-any.whl"
    dist_info = f"{name}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    metadata += "".join(f"Requires-Dist: {r}\n" for r in requires)
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"{name}.py", "")
        archive.writestr(f"{dist_info}/METADATA", metadata)
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
    return wheel


def _add_to_index(root, name, version, requires=()):
    """Add a package to the simple index at ``root``; return the wheel."""
    wheel = _write_wheel(root / name, name, version, requires)
    links = "".join(
        f'<a href="{w.name}">{w.name}</a>' for w in sorted((root / name).glob("*.whl"))
    )
    (root / name / "index.html").write_text(f"<html><body>{links}</body></html>")
    return wheel


def _write_two_index_pipfile(p, public, private, packages, dev_packages):
    Path(p.pipfile_path).write_text(
        f"""
[[source]]
url = "{public.as_uri()}/"
verify_ssl = true
name = "public"

[[source]]
url = "{private.as_uri()}/"
verify_ssl = true
name = "private"

[packages]
{packages}

[dev-packages]
{dev_packages}
"""
    )


def test_uv_backend_pin_in_other_category_restricts_transitive_use(
    pipenv_instance_file_pypi, tmp_path
):
    public, private = tmp_path / "public", tmp_path / "private"
    _add_to_index(public, "shared", "2.0")
    _add_to_index(public, "devtool", "1.0", requires=["shared"])
    wheel = _add_to_index(private, "shared", "1.0")
    with pipenv_instance_file_pypi() as p:
        _write_two_index_pipfile(
            p,
            public,
            private,
            'shared = {version = "*", index = "private"}',
            'devtool = "*"',
        )
        c = p.pipenv("lock --backend uv")
        assert c.returncode == 0, c.stderr
        expected = f"sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}"
        for section in ("default", "develop"):
            entry = p.lockfile[section]["shared"]
            assert entry["version"] == "==1.0"
            assert entry["hashes"] == [expected]
            assert entry["index"] == "private"


def test_uv_backend_unused_pin_in_other_category_is_not_locked(
    pipenv_instance_file_pypi, tmp_path
):
    public, private = tmp_path / "public", tmp_path / "private"
    _add_to_index(public, "devtool", "1.0")
    _add_to_index(private, "helper", "1.0")
    _add_to_index(private, "shared", "1.0", requires=["helper"])
    _add_to_index(public, "helper", "1.0")
    with pipenv_instance_file_pypi() as p:
        _write_two_index_pipfile(
            p,
            public,
            private,
            'shared = {version = "*", index = "private"}',
            'devtool = "*"',
        )
        c = p.pipenv("lock --backend uv")
        assert c.returncode == 0, c.stderr
        assert set(p.lockfile["develop"]) == {"devtool"}


def test_uv_backend_local_requirements(pipenv_instance_file_pypi, tmp_path):
    """Each local form the Pipfile can express, through a real uv run."""
    index = tmp_path / "index"
    _add_to_index(index, "helper", "1.0")
    wheel = _write_wheel(tmp_path / "wheels", "localwheel", "1.0")

    def write_project(root, name):
        root.mkdir(parents=True)
        (root / f"{name}.py").write_text("")
        (root / "pyproject.toml").write_text(
            f"""
[project]
name = "{name}"
version = "1.0"
[project.optional-dependencies]
test = ["helper"]
[build-system]
requires = ["uv_build"]
build-backend = "uv_build"
"""
        )

    write_project(tmp_path / "editablepkg", "editablepkg")
    write_project(tmp_path / "plainpkg", "plainpkg")
    repo = tmp_path / "repo"
    write_project(repo / "sub", "gitpkg")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(git + ["-C", str(repo), "add", "."], check=True)
    subprocess.run(git + ["-C", str(repo), "commit", "-qm", "init"], check=True)

    with pipenv_instance_file_pypi() as p:
        Path(p.pipfile_path).write_text(
            f"""
[[source]]
url = "{index.as_uri()}/"
verify_ssl = true
name = "index"

[packages]
editablepkg = {{path = "{tmp_path / 'editablepkg'}", editable = true, extras = ["test"], markers = "os_name != 'nonexistent'"}}
plainpkg = {{path = "{tmp_path / 'plainpkg'}", extras = ["test"]}}
localwheel = {{file = "{wheel}"}}
gitpkg = {{git = "{repo.as_uri()}", subdirectory = "sub", extras = ["test"], markers = "os_name != 'nonexistent'"}}
"""
        )
        c = p.pipenv("lock --backend uv")
        assert c.returncode == 0, c.stderr
        default = p.lockfile["default"]

    assert default["editablepkg"]["editable"] is True
    assert default["editablepkg"]["extras"] == ["test"]
    assert default["editablepkg"]["markers"] == "os_name != 'nonexistent'"
    assert default["plainpkg"]["path"] == str(tmp_path / "plainpkg")
    assert default["plainpkg"]["extras"] == ["test"]
    assert default["localwheel"]["file"] == str(wheel)
    expected = f"sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}"
    assert default["localwheel"]["hashes"] == [expected]
    assert default["gitpkg"]["git"] == repo.as_uri()
    assert default["gitpkg"]["subdirectory"] == "sub"
    assert default["gitpkg"]["markers"] == "os_name != 'nonexistent'"
    assert "helper" in default


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
