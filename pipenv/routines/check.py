import configparser
import io
import json
import logging
import os
import subprocess as sp
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


from pipenv import pep508checker
from pipenv.utils import console, err
from pipenv.utils.processes import run_command, subprocess_run
from pipenv.utils.project import ensure_project
from pipenv.utils.shell import project_python
from pipenv.vendor import click, plette


def _get_safety(project, system=False, auto_install=True):
    """Install safety and its dependencies."""
    python = project_python(project, system=system)

    cmd = [python, "-m", "safety"]
    c = subprocess_run(cmd)
    if c.returncode:
        console.print(
            "[yellow bold]Safety package is required for vulnerability scanning but not installed.[/yellow bold]"
        )

        install = auto_install
        if not auto_install:
            install = click.confirm(
                "Would you like to install safety? This will not modify your Pipfile/lockfile.",
                default=True,
            )

        if not install:
            console.print(
                "[yellow]Vulnerability scanning skipped. Install safety with 'pip install pipenv[safety]'[/yellow]"
            )
            return ""

        console.print("[green]Installing safety...[/green]")

        # Install safety directly rather than as an extra to ensure it works in development mode
        cmd = [python, "-m", "pip", "install", "safety>=3.0.0", "typer>=0.9.0", "--quiet"]
        c = run_command(cmd)

        if c.returncode != 0:
            err.print(
                "[red]Failed to install safety. Please install it manually with 'pip install pipenv[safety]'[/red]"
            )
            return ""

        console.print("[green]Safety installed successfully![/green]")
    else:
        console.print("[green]Safety found![/green]")

    return os.path.join(os.path.dirname(python), "safety")


def build_safety_options(
    exit_code=True,
    output="screen",
    save_json="",
    policy_file="",
    safety_project=None,
):
    options = [
        "--exit-code" if exit_code else "--continue-on-error",
    ]
    formats = {"full-report": "--full-report", "minimal": "--json"}

    if output in formats:
        options.append(formats.get(output, ""))
    elif output not in ["screen", "default"]:
        options.append(f"--output={output}")

    if save_json:
        options.append(f"--save-json={save_json}")

    if policy_file:
        options.append(f"--policy-file={policy_file}")

    if safety_project:
        options.append(f"--project={safety_project}")

    return options


def run_safety_check(cmd, verbose):
    if verbose:
        click.echo(f"Running: {' '.join(cmd)}")
    c = sp.run(cmd, capture_output=False)
    return c.stdout, c.stderr, c.returncode


def has_safey_auth_token() -> bool:
    """"
    Retrieve a token from the local authentication configuration.

    This returns tokens saved in the local auth configuration.
    There are two types of tokens: access_token and id_token

    Args:
        name (str): The name of the token to retrieve.

    Returns:
        Optional[str]: The token value, or None if not found.
    """

    authconfig = Path("~", ".safety", "auth.ini").expanduser() 
    config = configparser.ConfigParser()
    config.read(authconfig)
    if 'auth' in config.sections() and 'access_token' in config['auth']:
        value = config['auth']['access_token']
        if value:
            return True

    return False
    

def do_check(
    project,
    python=False,
    system=False,
    db=None,
    ignore=None,
    output="screen",
    key=None,
    quiet=False,
    verbose=False,
    exit_code=True,
    policy_file="",
    save_json="",
    audit_and_monitor=True,
    safety_project=None,
    pypi_mirror=None,
    use_installed=False,
    categories="",
):
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

    if not shutil.which("safety"):
        safety_path = _get_safety(project)

    if not has_safey_auth_token():
        click.secho("Could not find saftey token. Use `safety check` to manually login to your account", bold=True)
        sys.exit(1)

    if not project.lockfile_exists:
        return

    if not quiet and not project.s.is_quiet():
        if use_installed:
            click.secho(
                "Checking installed packages for vulnerabilities...",
                bold=True,
            )
        else:
            click.secho(
                "Checking Pipfile.lock packages for vulnerabilities...",
                bold=True,
            )

    if ignore:
        ignore = [ignore] if not isinstance(ignore, (tuple, list)) else ignore
        if not quiet and not project.s.is_quiet():
            click.echo(
                "Notice: Ignoring Vulnerabilit{} {}".format(
                    "ies" if len(ignore) > 1 else "y",
                    click.style(", ".join(ignore), fg="yellow"),
                ),
                err=True,
            )

    options = build_safety_options(
        exit_code=exit_code,
        output=output,
        save_json=save_json,
        policy_file=policy_file,
        safety_project=safety_project,
    )

    cmd = [safety_path, "scan"] + options

    if db:
        if not quiet and not project.s.is_quiet():
            click.echo(f"Using {db} database")
        cmd.append(f"--db={db}")

    if ignore:
        for cve in ignore:
            cmd.extend(["--ignore", cve])

    _, _, exit_code = run_safety_check(cmd, verbose)

    sys.exit(exit_code)
