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
from pipenv.utils.processes import run_command
from pipenv.utils.project import ensure_project
from pipenv.utils.shell import project_python
from pipenv.vendor import click, plette


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
    c = sp.run(cmd,capture_output=True)
    return c.stdout, c.stderr, c.returncode


def parse_safety_output(output, quiet):
    try:
        json_report = json.loads(output)
        meta = json_report.get("report_meta", {})
        vulnerabilities_found = meta.get("vulnerabilities_found", 0)
        db_type = "commercial" if meta.get("api_key", False) else "free"

        if quiet:
            click.secho(
                f"{vulnerabilities_found} vulnerabilities found.",
                fg="red" if vulnerabilities_found else "green",
            )
        else:
            fg = "red" if vulnerabilities_found else "green"
            message = f"Scan complete using Safety's {db_type} vulnerability database."
            click.echo()
            click.secho(f"{vulnerabilities_found} vulnerabilities found.", fg=fg)
            click.echo()

            for vuln in json_report.get("vulnerabilities", []):
                click.echo(
                    "{}: {} {} open to vulnerability {} ({}). More info: {}".format(
                        click.style(vuln["vulnerability_id"], bold=True, fg="red"),
                        click.style(vuln["package_name"], fg="green"),
                        click.style(vuln["analyzed_version"], fg="yellow", bold=True),
                        click.style(vuln["vulnerability_id"], bold=True),
                        click.style(vuln["vulnerable_spec"], fg="yellow", bold=False),
                        click.style(vuln["more_info_url"], bold=True),
                    )
                )
                click.echo(f"{vuln['advisory']}")
                click.echo()

            click.secho(message, fg="white", bold=True)

    except json.JSONDecodeError:
        click.echo("Failed to parse Safety output.")

def _get_safety():
    return shutil.which("safety")

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

    safety_path = _get_safety()
    if not safety_path:
        click.secho("Safety isn't installed. Please install safety on your system.", bold=True)
        sys.exit(1)

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

    cmd = [safety_path, "check"] + options

    if db:
        if not quiet and not project.s.is_quiet():
            click.echo(f"Using {db} database")
        cmd.append(f"--db={db}")

    if ignore:
        for cve in ignore:
            cmd.extend(["--ignore", cve])

    os.environ["SAFETY_CUSTOM_INTEGRATION"] = "True"
    os.environ["SAFETY_SOURCE"] = "pipenv"
    os.environ["SAFETY_PURE_YAML"] = "True"
    output, error, exit_code = run_safety_check(cmd, verbose)

    if quiet:
        parse_safety_output(output, quiet)
    else:
        sys.stdout.write(output.decode())
        sys.stderr.write(error.decode())

    sys.exit(exit_code)
