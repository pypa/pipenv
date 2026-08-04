from pathlib import Path
from unittest.mock import Mock

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
