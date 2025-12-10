"""
Audit command implementation using pip-audit for vulnerability scanning.

This module provides the preferred way to audit Python packages for known
security vulnerabilities using pip-audit, which queries the Python Packaging
Advisory Database (PyPI) or Open Source Vulnerabilities (OSV) database.
"""

import logging
import subprocess
import sys

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
    from pipenv.vendor import click

    python = project_python(project, system=system)

    console.print(
        "[yellow bold]pip-audit is required for vulnerability scanning but not installed.[/yellow bold]"
    )

    install = click.confirm(
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

    # Use lockfile (pyproject.toml / pylock.toml)
    if use_lockfile:
        options.append("--locked")

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
    - pyproject.toml / pylock.toml files (with --locked flag)
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

    # If using lockfile mode, add the project directory path
    if use_lockfile:
        cmd.append(project.project_directory)

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
