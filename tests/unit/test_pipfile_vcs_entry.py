"""Regression tests for VCS entry generation in ``Pipfile.generate_entry``.

``generate_entry`` splits the revision off a VCS line. Doing that with a plain
``rsplit("@", 1)`` breaks any URL that carries a user in its netloc, e.g.
``git+ssh://git@github.com/org/repo.git``: the host part was mistaken for the
revision and the recorded URL became ``ssh://git``. These tests pin the
netloc-aware behaviour.
"""

from __future__ import annotations

import pytest

from pipenv.patched.pip._internal.models.link import Link
from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.project import Project

PIPFILE_BARE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]

[dev-packages]
"""


@pytest.fixture
def project_bare(tmp_path, monkeypatch):
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_BARE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    return Project(chdir=False)


@pytest.fixture
def entry_for(project_bare, monkeypatch):
    """Return a callable building the Pipfile entry for a VCS line.

    ``expansive_install_req_from_line`` is stubbed out so the tests stay
    offline: the real helper clones the repository to resolve a revision,
    which is irrelevant to the string handling under test.
    """
    import pipenv.utils.pipfile as pipfile_module

    def _fake_from_line(line):
        return InstallRequirement(req=None, comes_from=None, link=Link(line.strip())), None

    monkeypatch.setattr(
        pipfile_module, "expansive_install_req_from_line", _fake_from_line
    )
    monkeypatch.setattr(pipfile_module, "determine_package_name", lambda package: "repo")

    def _build(line):
        _, _, entry = project_bare.pipfile.generate_entry(
            line, line, category="packages"
        )
        return entry

    return _build


@pytest.mark.utils
@pytest.mark.parametrize(
    "line, expected_git",
    [
        ("git+ssh://git@github.com/org/repo.git", "ssh://git@github.com/org/repo.git"),
        (
            "git+ssh://git@github.com/org/repo.git@v1.2.3",
            "ssh://git@github.com/org/repo.git",
        ),
        (
            "git+https://github.com/org/repo.git",
            "https://github.com/org/repo.git",
        ),
        (
            "git+https://github.com/org/repo.git@feature/x",
            "https://github.com/org/repo.git",
        ),
    ],
)
def test_vcs_url_is_not_split_on_netloc_user(entry_for, line, expected_git):
    """A ``user@host`` netloc must never be read as a revision."""
    entry = entry_for(line)

    assert entry["git"] == expected_git


@pytest.mark.utils
@pytest.mark.parametrize(
    "line, expected_ref",
    [
        ("git+ssh://git@github.com/org/repo.git", None),
        ("git+ssh://git@github.com/org/repo.git@v1.2.3", "v1.2.3"),
        ("git+ssh://git@github.com/org/repo.git@main", "main"),
        ("git+https://github.com/org/repo.git@feature/x", "feature/x"),
        ("git+https://github.com/org/repo.git", None),
    ],
)
def test_vcs_ref_is_extracted_only_when_present(entry_for, line, expected_ref):
    entry = entry_for(line)

    assert entry.get("ref") == expected_ref


@pytest.mark.utils
def test_vcs_ref_strips_fragment(entry_for):
    entry = entry_for(
        "git+ssh://git@github.com/org/repo.git@main#subdirectory=pkg"
    )

    assert entry["ref"] == "main"
    assert entry["subdirectory"] == "pkg"
