"""Tests for ``pipenv init`` (``pipenv.routines.init``)."""

from __future__ import annotations

from unittest import mock

import pytest

from pipenv.routines.context import RoutineContext
from pipenv.routines.init import do_project_init, parse_package_list


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", {}),
        ("requests", {"requests": "*"}),
        ("Flask>=3,<4", {"flask": "<4,>=3"}),
        ("'Flask>=3' Django==5.1", {"flask": ">=3", "django": "==5.1"}),
        (
            "uvicorn[standard]>=0.30",
            {"uvicorn": {"version": ">=0.30", "extras": ["standard"]}},
        ),
        (
            "'pywin32; sys_platform == \"win32\"'",
            {"pywin32": {"version": "*", "markers": 'sys_platform == "win32"'}},
        ),
    ],
)
def test_parse_package_list(text, expected):
    entries, rejected = parse_package_list(text)
    assert entries == expected
    assert rejected == []


@pytest.mark.parametrize(
    "token",
    ["./localpkg", "-e .", "'pkg @ https://example.com/pkg.whl'", "git+https://x/y", "'oops"],
)
def test_parse_package_list_rejects_non_plain_requirements(token):
    entries, rejected = parse_package_list(token)
    assert rejected
    assert "pkg" not in entries


@pytest.fixture
def project(tmp_path, monkeypatch):
    from pipenv.project import Project

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    monkeypatch.setenv("PIPENV_DEFAULT_PYTHON_VERSION", "3.12")
    return Project


def _ctx(python=None):
    return RoutineContext.from_cli(python=python)


def test_yes_writes_defaults_and_imports_requirements(project, tmp_path):
    (tmp_path / "requirements.txt").write_text("six==1.16.0\n")
    proj = project()
    with mock.patch("pipenv.routines.install.do_install") as do_install:
        do_project_init(proj, _ctx(), yes=True)

    parsed = proj.pipfile.parsed
    assert parsed["packages"]["six"] == "==1.16.0"
    assert parsed["source"][0]["url"] == proj.default_source["url"]
    assert "python_version" in parsed["requires"]
    do_install.assert_not_called()


def test_bare_python_version_is_recorded(project, tmp_path):
    proj = project()
    do_project_init(proj, _ctx(python="3.11"), yes=True, install=False)
    assert proj.pipfile.parsed["requires"]["python_version"] == "3.11"


def test_refuses_existing_pipfile(project, tmp_path):
    (tmp_path / "Pipfile").write_text("[packages]\n")
    with pytest.raises(SystemExit) as exc:
        do_project_init(project(), _ctx(), yes=True)
    assert exc.value.code == 1


def test_parent_pipfile_does_not_block(project, tmp_path, monkeypatch):
    (tmp_path / "Pipfile").write_text("[packages]\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)
    proj = project()
    do_project_init(proj, _ctx(), yes=True, install=False)
    assert (sub / "Pipfile").is_file()
    assert (tmp_path / "Pipfile").read_text() == "[packages]\n"


def test_interactive_dialog(project, tmp_path, monkeypatch):
    answers = iter(
        [
            "3.11",  # Python version
            "https://mirror.example/simple",  # index
            "requests ./local",  # packages, rejected once
            "requests 'flask[async]>=3'",  # packages
            "pytest",  # dev packages
        ]
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "pipenv.routines.init.Prompt.ask", lambda *a, **k: next(answers)
    )
    monkeypatch.setattr("pipenv.routines.init.Confirm.ask", lambda *a, **k: True)
    proj = project()
    with mock.patch("pipenv.routines.install.do_install") as do_install:
        do_project_init(proj, _ctx())

    parsed = proj.pipfile.parsed
    assert parsed["requires"]["python_version"] == "3.11"
    assert parsed["source"][0]["url"] == "https://mirror.example/simple"
    assert parsed["packages"]["requests"] == "*"
    assert parsed["packages"]["flask"]["extras"] == ["async"]
    assert parsed["dev-packages"]["pytest"] == "*"
    do_install.assert_called_once()


@pytest.mark.parametrize("failure", [SystemExit(1), RuntimeError("boom")])
def test_failed_install_removes_new_pipfile(project, tmp_path, failure):
    proj = project()
    with mock.patch(
        "pipenv.routines.install.do_install", side_effect=failure
    ), pytest.raises(type(failure)):
        do_project_init(proj, _ctx(), yes=True, install=True)
    assert not (tmp_path / "Pipfile").exists()


def test_successful_install_keeps_pipfile(project, tmp_path):
    proj = project()
    with mock.patch(
        "pipenv.routines.install.do_install", side_effect=SystemExit(0)
    ), pytest.raises(SystemExit):
        do_project_init(proj, _ctx(), yes=True, install=True)
    assert (tmp_path / "Pipfile").is_file()
