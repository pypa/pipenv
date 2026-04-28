"""Regression tests for Pipfile cache corruption during lock.

Before this fix, ``get_locked_dep`` popped ``version`` and ``ref`` keys
in-place from the entry it received.  That entry is sourced from the
cached ``parsed_pipfile`` document, so the mutation persisted across the
rest of the pipenv invocation — the next ``write_toml`` call would emit
``six = {}`` instead of ``six = {version = "*"}``.
"""
from unittest import mock

import pytest

from pipenv.project import Project
from pipenv.routines.lock import do_lock
from pipenv.utils import locking


def _identity_clean_resolved_dep(project, dep, is_top_level=False, current_entry=None):
    return {dep["name"]: dict(dep)}


PIPFILE_WITH_INLINE_AND_OUTLINE_TABLES = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
six = {version = "*"}

[packages.requests]
version = "*"
extras = ["socks"]

[packages.mypkg]
git = "https://example.com/mypkg.git"
ref = "main"
"""


def test_get_locked_dep_does_not_mutate_pipfile_section():
    pipfile_section = {
        "six": {"version": "*"},
        "requests": {"version": "*", "extras": ["socks"]},
        "mypkg": {"git": "https://example.com/mypkg.git", "ref": "main"},
    }
    snapshot = {k: dict(v) for k, v in pipfile_section.items()}

    with mock.patch.object(
        locking, "clean_resolved_dep", side_effect=_identity_clean_resolved_dep
    ):
        for dep in (
            {"name": "six", "version": "==1.16.0"},
            {"name": "requests", "version": "==2.32.3"},
            {"name": "mypkg"},
        ):
            locking.get_locked_dep(
                project=None, dep=dep, pipfile_section=pipfile_section
            )

    assert pipfile_section["six"] == snapshot["six"]
    assert pipfile_section["requests"] == snapshot["requests"]
    assert pipfile_section["mypkg"] == snapshot["mypkg"]


@pytest.fixture
def project_with_cached_outline_tables(tmp_path, monkeypatch):
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_WITH_INLINE_AND_OUTLINE_TABLES)
    monkeypatch.chdir(tmp_path)
    return Project(chdir=False)


def _fake_resolve_packages(*args, **kwargs):
    return [
        {"name": "six", "version": "==1.16.0"},
        {"name": "requests", "version": "==2.32.3", "extras": ["socks"]},
        {
            "name": "mypkg",
            "git": "https://example.com/mypkg.git",
            "ref": "deadbeef",
        },
    ]


def test_missing_lock_then_write_toml_keeps_cached_pipfile_entries(
    project_with_cached_outline_tables,
):
    project = project_with_cached_outline_tables

    with mock.patch.object(project.s, "PIPENV_RESOLVER_PARENT_PYTHON", True), mock.patch(
        "pipenv.resolver.resolve_packages", side_effect=_fake_resolve_packages
    ):
        do_lock(project, write=False, quiet=True)

    project.add_pipfile_entry_to_pipfile(
        "colorama", "colorama", "*", category="packages"
    )
    reparsed = project.parsed_pipfile["packages"]

    assert str(reparsed["six"]["version"]) == "*"
    assert str(reparsed["requests"]["version"]) == "*"
    assert list(reparsed["requests"]["extras"]) == ["socks"]
    assert str(reparsed["mypkg"]["ref"]) == "main"
    assert reparsed["colorama"] == "*"
