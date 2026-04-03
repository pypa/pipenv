"""
Audit command implementation using pip-audit for vulnerability scanning.

This module provides the preferred way to audit Python packages for known
security vulnerabilities using pip-audit, which queries the Python Packaging
Advisory Database (PyPI) or Open Source Vulnerabilities (OSV) database.
"""

import logging
import subprocess
import sys
import tempfile

from pipenv.utils import console, err
from pipenv.utils.processes import run_command
from pipenv.utils.project import ensure_project
from pipenv.utils.shell import project_python


def is_pip_audit_installed(project=None, system=False):
    """Check if pip-audit is installed by trying to run it."""
    if project:
        python = project_python(project, system=system)
    else:
        python = sys.executable

    try:
        result = subprocess.run(
            [python, "-m", "pip_audit", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def install_pip_audit(project, system=False):
    """Install pip-audit."""
    from pipenv.utils import Confirm

    python = project_python(project, system=system)

    console.print(
        "[yellow bold]pip-audit is required for vulnerability scanning but not installed.[/yellow bold]"
    )

    install = Confirm.ask(
        "Would you like to install pip-audit? This will not modify your Pipfile/lockfile.",
        default=True,
    )

    if not install:
        console.print(
            "[yellow]Vulnerability scanning skipped. Install pip-audit with 'pip install pip-audit'[/yellow]"
        )
        return False

    console.print("[green]Installing pip-audit...[/green]")
    cmd = [python, "-m", "pip", "install", "pip-audit>=2.7.0", "--quiet"]
    c = run_command(cmd)

    if c.returncode != 0:
        err.print(
            "[red]Failed to install pip-audit. Please install it manually with 'pip install pip-audit'[/red]"
        )
        return False

    console.print("[green]pip-audit installed successfully![/green]")
    return True


def build_audit_options(
    output="columns",
    strict=False,
    ignore=None,
    fix=False,
    dry_run=False,
    skip_editable=False,
    no_deps=False,
    local_only=False,
    vulnerability_service="pypi",
    descriptions=False,
    aliases=False,
    output_file=None,
    requirements_file=None,
    use_lockfile=False,
):
    """Build command line options for pip-audit."""
    options = []

    # Output format
    if output and output != "columns":
        options.extend(["-f", output])

    # Vulnerability service
    if vulnerability_service and vulnerability_service != "pypi":
        options.extend(["-s", vulnerability_service])

    # Flags
    if strict:
        options.append("--strict")
    if fix:
        options.append("--fix")
    if dry_run:
        options.append("--dry-run")
    if skip_editable:
        options.append("--skip-editable")
    if no_deps:
        options.append("--no-deps")
    if local_only:
        options.append("--local")
    if descriptions:
        options.append("--desc")
    if aliases:
        options.append("--aliases")

    # Note: use_lockfile is handled in do_audit by generating a temporary
    # requirements file from Pipfile.lock, since pip-audit's --locked flag
    # does not support Pipfile.lock format.

    # Requirements file
    if requirements_file:
        options.extend(["-r", requirements_file])

    # Output file
    if output_file:
        options.extend(["-o", output_file])

    # Ignore specific vulnerabilities
    if ignore:
        for vuln_id in ignore:
            options.extend(["--ignore-vuln", vuln_id])

    return options


def do_audit(  # noqa: PLR0913
    project,
    python=False,
    system=False,
    output="columns",
    quiet=False,
    verbose=False,
    strict=False,
    ignore=None,
    fix=False,
    dry_run=False,
    skip_editable=False,
    no_deps=False,
    local_only=False,
    vulnerability_service="pypi",
    descriptions=False,
    aliases=False,
    output_file=None,
    pypi_mirror=None,
    categories="",
    use_installed=False,
    use_lockfile=False,
):
    """Audit packages for known security vulnerabilities using pip-audit.

    This is the preferred method for vulnerability scanning in pipenv.
    It uses the Python Packaging Advisory Database (PyPI) or OSV database.

    Supports auditing from:
    - The current virtualenv (default)
    - Pipfile.lock (with --locked flag, converted to requirements format for pip-audit)
    """
    if not verbose:
        logging.getLogger("pipenv").setLevel(logging.ERROR if quiet else logging.WARN)

    if not system:
        ensure_project(
            project,
            python=python,
            validate=False,
            warn=False,
            pypi_mirror=pypi_mirror,
        )

    if not quiet and not project.s.is_quiet():
        if use_lockfile:
            console.print(
                "[bold]Auditing lockfile packages for vulnerabilities...[/bold]"
            )
        else:
            console.print("[bold]Auditing packages for vulnerabilities...[/bold]")

    # Check if pip-audit is installed
    if not is_pip_audit_installed(project, system=system):
        if not install_pip_audit(project, system=system):
            console.print("[yellow]Vulnerability audit aborted.[/yellow]")
            return

        # Check again after installation
        if not is_pip_audit_installed(project, system=system):
            err.print(
                "[red]pip-audit installation was reported successful but module not found. "
                "Please try again or install manually with 'pip install pip-audit'[/red]"
            )
            return

    # Build options for pip-audit
    options = build_audit_options(
        output=output,
        strict=strict,
        ignore=ignore,
        fix=fix,
        dry_run=dry_run,
        skip_editable=skip_editable,
        no_deps=no_deps,
        local_only=local_only,
        vulnerability_service=vulnerability_service,
        descriptions=descriptions,
        aliases=aliases,
        output_file=output_file,
        use_lockfile=use_lockfile,
    )

    # Build the command
    python_path = project_python(project, system=system)
    cmd = [python_path, "-m", "pip_audit"] + options

    # If using lockfile mode, generate a temporary requirements file from
    # Pipfile.lock and pass it via -r.  pip-audit's own --locked flag only
    # recognises pylock.toml / poetry.lock / uv.lock — not Pipfile.lock.
    tmp_requirements = None
    if use_lockfile:
        if not project.lockfile_exists:
            err.print(
                "[red]Pipfile.lock not found. Run 'pipenv lock' first.[/red]"
            )
            sys.exit(1)

        from pipenv.utils.requirements import requirements_from_lockfile

        lockfile = project.load_lockfile(expand_env_vars=False)
        deps = {}
        deps.update(lockfile.get("default", {}))
        deps.update(lockfile.get("develop", {}))

        lines = requirements_from_lockfile(
            deps, include_hashes=False, include_markers=True
        )

        tmp_requirements = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="pipenv-audit-", delete=False
        )
        tmp_requirements.write("\n".join(lines))
        tmp_requirements.flush()
        tmp_requirements.close()
        cmd.extend(["-r", tmp_requirements.name])

    if not quiet and not project.s.is_quiet() and verbose:
        console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")

    # Run pip-audit
    try:
        result = subprocess.run(
            cmd,
            capture_output=False,  # Let output go directly to terminal
            check=False,
        )
        sys.exit(result.returncode)
    except Exception as e:
        err.print(f"[red]Error running pip-audit: {str(e)}[/red]")
        sys.exit(1)
    finally:
        if tmp_requirements is not None:
            import os

            os.unlink(tmp_requirements.name)
