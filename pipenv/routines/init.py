"""``pipenv init`` — create a Pipfile for a new project, optionally by dialog.

Pipenv manages application environments, not package metadata, so the
dialog only asks about things a Pipfile actually records: the Python
version, the package index, and the initial packages.  Name / version /
author belong in ``pyproject.toml`` and are deliberately out of scope.
"""

import os
import shlex
import sys
from pathlib import Path

from pipenv.patched.pip._vendor.packaging.requirements import (
    InvalidRequirement,
    Requirement,
)
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.patched.pip._vendor.rich.prompt import Confirm, Prompt
from pipenv.utils import console, err


def parse_package_list(text):
    """Turn ``"requests flask>=3 'uvicorn[standard]'"`` into Pipfile entries.

    Returns ``(entries, rejected)`` where ``entries`` maps the canonical
    name to a Pipfile entry and ``rejected`` lists the tokens that are
    not plain PEP 508 requirements (URLs, paths, editables).  Those still
    work with ``pipenv install`` afterwards; they just need the full
    install machinery to build a correct Pipfile entry.
    """
    entries = {}
    rejected = []
    try:
        tokens = shlex.split(text)
    except ValueError:  # unbalanced quotes
        return entries, [text]
    for token in tokens:
        try:
            req = Requirement(token)
        except InvalidRequirement:
            rejected.append(token)
            continue
        if req.url:
            rejected.append(token)
            continue
        version = str(req.specifier) or "*"
        entry = {"version": version}
        if req.extras:
            entry["extras"] = sorted(req.extras)
        if req.marker:
            entry["markers"] = str(req.marker)
        entries[canonicalize_name(req.name)] = (
            version if len(entry) == 1 else entry
        )
    return entries, rejected


def _ask(question, default, interactive):
    if not interactive:
        return default
    return Prompt.ask(question, default=default, console=err)


def _confirm(question, default, interactive):
    if not interactive:
        return default
    return Confirm.ask(question, default=default, console=err)


def _ask_packages(question, interactive):
    if not interactive:
        return {}
    while True:
        entries, rejected = parse_package_list(
            Prompt.ask(question, default="", show_default=False, console=err)
        )
        if not rejected:
            return entries
        err.print(
            f"[yellow]Not a plain requirement: {', '.join(rejected)}.[/yellow] "
            "Add those afterwards with [bold]pipenv install[/bold]."
        )


def _install_or_discard(project, ctx, pipfile_path, do_install):
    """Run ``do_install``; if it fails, delete the Pipfile ``init`` just wrote.

    Otherwise a typo'd or nonexistent package is left in a Pipfile that
    blocks re-running ``init``.  ``do_install`` exits via ``SystemExit``
    on success too (code 0) and on lock failure (code 1), so a plain
    ``except Exception`` would miss the common failure path.
    """
    try:
        do_install(project, ctx)
    except SystemExit as exc:
        if exc.code in (None, 0):
            raise
        _discard_pipfile(pipfile_path)
        raise
    except Exception:
        _discard_pipfile(pipfile_path)
        raise


def _discard_pipfile(pipfile_path):
    pipfile_path.unlink(missing_ok=True)
    err.print(
        f"[bold red]Installation failed, so {pipfile_path} was removed.[/bold red] "
        "Fix the problem above and run [bold]pipenv init[/bold] again."
    )


def do_project_init(project, ctx, yes=False, install=None):
    """Create a Pipfile in the current directory.

    ``yes`` accepts every default without prompting (like ``npm init -y``);
    a non-interactive stdin implies it.  ``install`` forces (True) or
    skips (False) creating the virtualenv and locking afterwards; ``None``
    asks, defaulting to *yes* interactively and *no* under ``--yes``.
    """
    from pipenv.routines.install import do_install

    interactive = not yes and sys.stdin.isatty()

    # Always initialise in the directory pipenv was invoked from: a Pipfile
    # found by the usual parent-directory walk (which Project() has already
    # chdir'd into) belongs to some *other* project.
    if not project.s.PIPENV_PIPFILE:
        os.chdir(project._original_dir)
        project.pipfile._location = str(project._original_dir / "Pipfile")
        project.pipfile._name = None
    pipfile_path = Path(project.pipfile.location)
    if pipfile_path.exists():
        err.print(
            f"[bold red]A Pipfile already exists at {pipfile_path}.[/bold red] "
            "Use [bold]pipenv install[/bold] to add packages to it."
        )
        sys.exit(1)

    # ``--python`` may be an interpreter path or a bare version like
    # ``3.12``; create_pipfile only understands the former.
    python = ctx.target_env.python
    python_path = python if python and Path(python).is_file() else None
    project.create_pipfile(python=python_path)

    requirements = pipfile_path.parent / "requirements.txt"
    if requirements.is_file() and _confirm(
        f"Import packages from [bold]{requirements.name}[/bold]?", True, interactive
    ):
        from pipenv.utils.dependencies import import_requirements

        import_requirements(project, r=str(requirements), replace_default_source=True)

    data = project.pipfile.parsed
    requires = data.setdefault("requires", {})
    current = requires.get("python_version", "")
    default = python if python and not python_path else current
    chosen = _ask("Python version", default, interactive).strip()
    if chosen and chosen != current:
        requires["python_version"] = ".".join(chosen.split(".")[:2])
        if len(chosen.split(".")) > 2:
            requires["python_full_version"] = chosen
        else:
            requires.pop("python_full_version", None)

    source = data["source"][0]
    url = _ask("Package index URL", source["url"], interactive).strip()
    if url and url != source["url"]:
        source["url"] = url
        source["verify_ssl"] = url.startswith("https")

    for category, label in (("packages", "Packages"), ("dev-packages", "Dev packages")):
        entries = _ask_packages(
            f"{label} [dim](space-separated, blank for none)[/dim]", interactive
        )
        data.setdefault(category, {}).update(entries)

    project.pipfile.write_toml(data)
    console.print(f"[bold green]Created {pipfile_path}[/bold green]")

    if install is None:
        install = interactive and _confirm(
            "Create the virtualenv and lock now?", True, interactive
        )
    if install:
        _install_or_discard(project, ctx, pipfile_path, do_install)
    else:
        console.print(
            "Run [bold]pipenv install[/bold] when you're ready to create the "
            "virtualenv and lock."
        )
