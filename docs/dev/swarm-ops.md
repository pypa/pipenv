# Swarm-Agent Operating Procedure

Operating manual for subagents executing tasks from
[`modernization-plan.md`](./modernization-plan.md). Read this once before
your first task; refer back as needed.

## 1. Scope and branch

Modernization work is coordinated on the long-lived branch
`maintenance/code-cleanup-2026-05`, cut from `main`. The default workflow
is: commit directly to the working branch. Per-initiative feature
branches off the working branch are allowed when (and only when) a task
description explicitly says so.

Agents **never**:

- merge to `main`
- force-push anywhere
- push at all, unless the orchestrator explicitly instructs

## 2. Pre-commit checklist

Before every commit:

1. `python -m pytest tests/unit -x` — must exit 0. Skipped tests (Windows-only,
   etc.) are fine; failures are not.
2. `ruff check pipenv/` — must exit 0. This is the project's linter and is
   also enforced by pre-commit hooks.
3. If the diff touches user-visible surface (logging, error messages,
   exit codes), grep the diff for `print(`, `logger.`, `raise `, and
   `sys.exit(` and call those out in the commit body so a reviewer can
   verify intent.
4. Commit message includes the trailer
   `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

## 3. Off-limits paths

Do not modify any of:

- `pipenv/patched/` — vendored pip; managed by separate tooling.
- `pipenv/vendor/` — vendored third-party packages; managed by separate
  tooling.
- `pipenv/__version__.py` — release tooling owns this.
- `CHANGELOG.md` — Towncrier generates this from `news/` fragments at
  release time.
- The repo's own `Pipfile.lock`.

## 4. Commit message conventions

Match the prefixes already in use. Verify with `git log --oneline -20`.
Common ones in this repo: `refactor:`, `chore:`, `chore(deps):`,
`docs:`, `docs(dev):`, `fix:`, `feat:`, `test:`, `perf:`, `vendor:`.

Rules:

- Subject line: single sentence, under 70 chars, imperative mood.
- Body: explain *why*, not *what*. The diff shows the what.
- Trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

## 5. News fragments (Towncrier)

pipenv uses Towncrier; fragments live in `news/`. Configured types include
`feature`, `behavior`, `bugfix`, `vendor`, `doc`, `trivial`, `removal`
(see `[tool.towncrier]` in `pyproject.toml`).

Rules of thumb:

- **Behavior-preserving refactors:** no fragment needed.
- **User-visible changes:** fragment required, committed in the same
  commit as the code change.
- Filename pattern follows what's already in `news/` (e.g.
  `+cool-down-period.feature.rst`, `<issue>.bugfix.rst`). Inspect the
  directory and copy the pattern.
- If your task description mentions `news/`, a fragment is required.

## 6. Review-flagged TODOs

When a task surfaces a side concern that a reviewer should see but isn't
blocking the current task, leave an inline comment tagged
`TODO(swarm): ...` in the code. These are greppable; the reviewer can
sweep them with `rg "TODO\(swarm\)"` at the end of the wave.

## 7. Definition of "task complete"

A task is complete when **all** of the following hold:

1. The acceptance criteria listed in the plan entry are met.
2. The validation steps in the plan entry pass.
3. The commit(s) for the task work are made on the working branch.
4. The task's entry in `docs/dev/modernization-plan.md` has been updated:
   `status` set to `Completed`, `log` filled in with a 2–3 line summary,
   and `files edited/created` populated.

The plan-file update is a **separate** commit from the task work itself,
typically with a `chore(plan): mark <task-id> complete` subject.
