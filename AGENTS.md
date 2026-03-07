# AGENTS.md — Pipenv

Guidelines for AI coding agents working in this repository.

## Project Overview

Pipenv is a Python packaging tool that manages virtualenvs and dependencies via
Pipfile/Pipfile.lock. Built on Click, it vendors its own copy of pip and many
dependencies under `pipenv/vendor/` and `pipenv/patched/`.

**Python required:** >=3.10

## Build & Install

```bash
pip install -e .              # Editable install
pip install -e .[tests,dev]   # With test and dev extras
pipenv install --dev          # Full dev environment via pipenv itself
python -m build               # Build sdist + wheel
twine check dist/*            # Validate built package
```

## Linting & Formatting

```bash
ruff check .                          # Lint (primary linter)
ruff check --fix .                    # Lint with auto-fix
black pipenv/*.py                     # Format (line-length=90)
pre-commit run --all-files            # Run all pre-commit hooks
```

- **Ruff** is the primary linter (line-length=137, rules: ASYNC, B, C4, C90, E,
  F, FLY, G, I, ISC, PERF, PIE, PL, TID, UP, W, YTT).
- **Black** is the formatter (line-length=90).
- **isort** with `profile = black` handles import sorting.
- **mypy** configured but `ignore_missing_imports = true` and `follow_imports = "skip"`.
- Ruff and Black exclude `pipenv/vendor/`, `pipenv/patched/`, `tests/fixtures/`,
  `tests/pypi/`, and `tests/test_artifacts/`.

## Testing

### Quick Reference

```bash
# Unit tests (fast, no external deps)
pipenv run pytest tests/unit/ -v

# Full test suite with parallelism
pipenv run pytest -ra -n auto -v --fulltrace tests

# Single test file
pipenv run pytest tests/unit/test_utils.py -v

# Single test by name (-k pattern match)
pipenv run pytest -ra -k 'test_basic_install' -vvv

# Single test by node ID
pipenv run pytest tests/unit/test_utils.py::test_format_toml -v

# Tests by marker
pipenv run pytest -m install -v

# Via Makefile
make tests                            # Full parallel suite
make test-specific tests='test_name'  # By -k pattern
```

### Test Structure

- `tests/unit/` — Fast isolated tests. No pipenv instance or network needed.
- `tests/integration/` — Slower tests that create temporary project directories.
  Require a local pypi-server on port 8080 (see `run-tests.sh`).
- `tests/test_artifacts/` — Git submodules (requests, flask, etc.) used by tests.
  Run `git submodule sync && git submodule update --init --recursive` before
  integration tests.

### Test Conventions

- Use plain `assert` for assertions, `pytest.raises` for expected exceptions.
- Integration tests use the `pipenv_instance_private_pypi` or
  `pipenv_instance_pypi` fixture as a context manager:
  ```python
  @pytest.mark.install
  def test_example(pipenv_instance_private_pypi):
      with pipenv_instance_private_pypi() as p:
          c = p.pipenv("install six")
          assert c.returncode == 0
  ```
- Unit tests use standard pytest fixtures (`tmp_path`, `monkeypatch`).
- Decorate tests with appropriate markers: `@pytest.mark.install`,
  `@pytest.mark.basic`, `@pytest.mark.utils`, `@pytest.mark.lock`,
  `@pytest.mark.cli`, `@pytest.mark.sync`, etc.
- Test naming: `test_<feature>_<scenario>` in snake_case.
- Both `monkeypatch` and `unittest.mock` are used for mocking.

### Key Pytest Config (pyproject.toml)

- `addopts = "-ra --no-cov"`
- `testpaths = ["tests"]`
- Parallel execution via `pytest-xdist` (`-n auto`)
- Rerun flaky tests via `pytest-rerunfailures`

## Code Style

### Imports

- **Order:** stdlib, third-party, local (enforced by isort, profile=black).
- Use `if typing.TYPE_CHECKING:` guards for heavy or circular imports.
- Conditional imports are common for version compat:
  ```python
  if sys.version_info < (3, 11):
      import tomli as tomllib
  else:
      import tomllib
  ```
- Vendored deps imported as `pipenv.vendor.<pkg>` or `pipenv.patched.pip._vendor.<pkg>`.

### Type Annotations

- Mixed style across codebase. Files with `from __future__ import annotations`
  use modern syntax (`str | None`, `list[str]`). Otherwise use `typing` module.
- When adding new code, prefer modern annotations with
  `from __future__ import annotations`.
- Use `TYPE_CHECKING` guards for import-only types.

### Naming

| Entity | Convention | Example |
|--------|-----------|---------|
| Functions/methods | `snake_case` | `get_installed_packages()` |
| Classes | `PascalCase` | `Environment`, `PackageRequirement` |
| Constants | `UPPER_SNAKE_CASE` | `PIPENV_ROOT`, `DEFAULT_NEWLINES` |
| Private members | Leading underscore | `_python`, `_base_paths` |
| Settings | `PIPENV_` prefix | Mirrors environment variable names |

### Docstrings

- Sphinx/reST style is predominant (`:param name:`, `:return:`, `:rtype:`).
- Not all functions have docstrings, but public API should.

### Error Handling

- Custom exception hierarchy based on Click exceptions:
  - `PipenvException(ClickException)` — base exception
  - Subclasses: `PipenvCmdError`, `JSONParseError`, `InstallError`,
    `ResolutionFailure`, `PipenvUsageError`, `PipenvFileError`
- Exceptions use Rich console for formatted terminal output via custom `show()`.
- `contextlib.suppress()` preferred for ignoring expected errors.
- Avoid bare `except:` — use `except Exception:` at minimum.

### Formatting Rules

- **Line length:** 90 (Black), 137 (Ruff max).
- **Indentation:** 4 spaces (2 spaces for TOML/YAML).
- **Line endings:** LF.
- **Encoding:** UTF-8.
- **Trailing whitespace:** trimmed.

## Architecture

- **CLI:** Click-based, defined in `pipenv/cli/command.py` + `pipenv/cli/options.py`.
- **Routines:** One module per CLI command in `pipenv/routines/`
  (e.g., `install.py`, `lock.py`, `sync.py`).
- **Project:** Central `Project` class holds all state (Pipfile, lockfile,
  virtualenv, sources) in `pipenv/project.py`.
- **Environment:** `Environment` class in `pipenv/environment.py` manages
  virtualenv context and package inspection.
- **Utils:** Split into focused modules under `pipenv/utils/` (~20 modules).
- **Settings:** `environments.Setting` reads `PIPENV_*` environment variables.
- **Vendored deps:** Do NOT edit `pipenv/vendor/` or `pipenv/patched/` directly.
  Use `python -m invoke vendoring.update` to re-vendor.

## Pre-commit Hooks

Hooks exclude `pipenv/patched/`, `pipenv/vendor/`, and `tests/`. Key hooks:
- `ruff` (with `--fix --exit-non-zero-on-fix`)
- `black`
- `check-ast`, `check-toml`, `check-yaml`, `debug-statements`
- `trailing-whitespace`, `end-of-file-fixer`
- `python-no-eval`, `python-no-log-warn`
- `pyproject-fmt`, `validate-pyproject`
- News fragment filename validation (must match `news/*.{feature|behavior|bugfix|vendor|doc|trivial|removal|process}.rst`)

## Changelog

Uses **towncrier**. Add changelog fragments to `news/` directory with the format
`<issue-number>.<type>.rst` where type is one of: `feature`, `behavior`,
`bugfix`, `vendor`, `doc`, `trivial`, `removal`, `process`.
