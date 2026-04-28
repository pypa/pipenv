"""Regression test for Pipfile cache corruption during lock.

Before this fix, ``get_locked_dep`` popped ``version`` and ``ref`` keys
in-place from the entry it received.  That entry is sourced from the
cached ``parsed_pipfile`` document, so the mutation persisted across the
rest of the pipenv invocation — the next ``write_toml`` call would emit
``six = {}`` instead of ``six = {version = "*"}``.

This test patches ``clean_resolved_dep`` (the only project-dependent
collaborator of ``get_locked_dep``) to a no-op and asserts that the
input ``pipfile_section`` is left untouched.
"""
from unittest import mock

from pipenv.utils import locking


def _identity_clean_resolved_dep(project, dep, is_top_level=False, current_entry=None):
    return {dep["name"]: dict(dep)}


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
