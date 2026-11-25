import subprocess
from pathlib import Path
from unittest.mock import Mock

import invoke
import pytest

from tasks import release as release_tasks


def test_release_can_resume_existing_version(monkeypatch, tmp_path):
    ctx = Mock()
    bump_version = Mock()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(release_tasks, "drop_dist_dirs", Mock())
    monkeypatch.setattr(release_tasks, "find_version", lambda ctx: "2026.7.0")
    monkeypatch.setattr(release_tasks, "bump_version", bump_version)
    monkeypatch.setattr(release_tasks, "_render_log", lambda ctx, version: "notes")
    monkeypatch.setattr(release_tasks, "generate_manual", Mock())
    monkeypatch.setattr(
        release_tasks,
        "get_version_file",
        lambda ctx: Path("pipenv/__version__.py"),
    )

    release_tasks.release.body(ctx, resume=True)

    bump_version.assert_not_called()
    commands = [call.args[0] for call in ctx.run.call_args_list]
    assert "towncrier build --version 2026.7.0 --yes" in commands
    assert 'git commit -m "Release v2026.7.0"' in commands
    assert any(command.startswith("git tag -a v2026.7.0") for command in commands)


def test_generate_changelog_removes_consumed_fragments(monkeypatch):
    ctx = Mock()
    monkeypatch.setattr(release_tasks, "find_version", lambda ctx: "2026.7.0")

    release_tasks.generate_changelog.body(ctx)

    ctx.run.assert_called_once_with(
        "towncrier build --version 2026.7.0 --yes"
    )


@pytest.mark.parametrize("pre", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_release_preserves_literal_tag_notes(monkeypatch, tmp_path, pre, dry_run):
    ctx = Mock()
    version = "2026.11.0"
    notes = (
        "Release notes\n\n"
        '- Use `uv <https://docs.astral.sh/uv/>`_ on ``$PATH`` with "quotes".\n'
        "- Keep pipenv's backslashes: C:\\tools\\uv.\n"
        "- Literal substitutions: $(touch dollar-expanded) `touch backtick-expanded`.\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(release_tasks, "drop_dist_dirs", Mock())
    monkeypatch.setattr(release_tasks, "find_version", lambda ctx: version)
    monkeypatch.setattr(release_tasks, "_render_log", lambda ctx, version: notes)
    monkeypatch.setattr(release_tasks, "generate_manual", Mock())
    monkeypatch.setattr(
        release_tasks, "get_version_file", lambda ctx: Path("pipenv/__version__.py")
    )

    release_tasks.release.body(ctx, resume=True, pre=pre, dry_run=dry_run)

    tag_calls = [
        call for call in ctx.run.call_args_list if call.args[0].startswith("git tag ")
    ]
    if dry_run:
        assert not tag_calls
        return

    assert len(tag_calls) == 1
    (tag_call,) = tag_calls
    # Run the generated command through Invoke's shell in an isolated repository.
    subprocess.run(["git", "init", "--quiet"], check=True)
    for key, value in [("user.name", "Release Test"), ("user.email", "test@example.com")]:
        subprocess.run(["git", "config", key, value], check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "Initial commit"], check=True, capture_output=True)
    result = invoke.Context().run(tag_call.args[0], hide=True, **tag_call.kwargs)

    assert not result.stderr
    assert not (tmp_path / "dollar-expanded").exists()
    assert not (tmp_path / "backtick-expanded").exists()
    tag = subprocess.check_output(["git", "cat-file", "tag", f"v{version}"], text=True)
    assert tag.split("\n\n", 1)[1] == f"Version v{version}\n\n{notes}"
