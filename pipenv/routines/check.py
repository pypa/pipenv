import io
import json
import logging
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pipenv import pep508checker
from pipenv.patched.safety.cli import cli
from pipenv.utils.processes import run_command
from pipenv.utils.project import ensure_project
from pipenv.utils.shell import project_python
from pipenv.vendor import click, plette


def build_safety_options(
    audit_and_monitor=True,
    exit_code=True,
    output="screen",
    save_json="",
    policy_file="",
    safety_project=None,
    temp_requirements_name="",
):
    options = [
        "--audit-and-monitor" if audit_and_monitor else "--disable-audit-and-monitor",
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

    options.extend(["--file", temp_requirements_name])

    return options


def run_pep508_check(project, system, python):
    pep508checker_path = pep508checker.__file__.rstrip("cdo")
    cmd = [project_python(project, system=system), Path(pep508checker_path).as_posix()]
    c = run_command(cmd, is_verbose=project.s.is_verbose())

    if c.returncode is not None:
        try:
            return json.loads(c.stdout.strip())
        except json.JSONDecodeError:
            click.echo(
                f"Failed parsing pep508 results:\n{c.stdout.strip()}\n{c.stderr.strip()}",
                err=True,
            )
            sys.exit(1)
    return {}


def check_pep508_requirements(project, results, quiet):
    p = plette.Pipfile.load(open(project.pipfile_location))
    p = plette.Lockfile.with_meta_from(p)
    failed = False

    for marker, specifier in p._data["_meta"]["requires"].items():
        if marker in results:
            if results[marker] != specifier:
                failed = True
                click.echo(
                    "Specifier {} does not match {} ({})."
                    "".format(
                        click.style(marker, fg="green"),
                        click.style(specifier, fg="cyan"),
                        click.style(results[marker], fg="yellow"),
                    ),
                    err=True,
                )

    if failed:
        click.secho("Failed!", fg="red", err=True)
        sys.exit(1)
    elif not quiet and not project.s.is_quiet():
        click.secho("Passed!", fg="green")


def get_requirements(project, use_installed, categories):
    _cmd = [project_python(project, system=False)]
    if use_installed:
        return run_command(
            _cmd + ["-m", "pip", "list", "--format=freeze"],
            is_verbose=project.s.is_verbose(),
        )
    elif categories:
        return run_command(
            ["pipenv", "requirements", "--categories", categories],
            is_verbose=project.s.is_verbose(),
        )
    else:
        return run_command(["pipenv", "requirements"], is_verbose=project.s.is_verbose())


def create_temp_requirements(project, requirements):
    temp_requirements = tempfile.NamedTemporaryFile(
        mode="w+",
        prefix=f"{project.virtualenv_name}",
        suffix="_requirements.txt",
        delete=False,
    )
    temp_requirements.write(requirements.stdout.strip())
    temp_requirements.close()
    return temp_requirements


def run_safety_check(cmd, quiet):
    sys.argv = cmd[1:]

    if quiet:
        out = io.StringIO()
        err = io.StringIO()
        exit_code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                cli(prog_name="pipenv")
            except SystemExit as exit_signal:
                exit_code = exit_signal.code
        return out.getvalue(), err.getvalue(), exit_code
    else:
        cli(prog_name="pipenv")


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

    if not quiet and not project.s.is_quiet():
        click.secho("Checking PEP 508 requirements...", bold=True)

    results = run_pep508_check(project, system, python)
    check_pep508_requirements(project, results, quiet)

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

    requirements = get_requirements(project, use_installed, categories)
    temp_requirements = create_temp_requirements(project, requirements)

    options = build_safety_options(
        audit_and_monitor=audit_and_monitor,
        exit_code=exit_code,
        output=output,
        save_json=save_json,
        policy_file=policy_file,
        safety_project=safety_project,
        temp_requirements_name=temp_requirements.name,
    )

    safety_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "patched", "safety"
    )
    cmd = [project_python(project, system=system), safety_path, "check"] + options

    if db:
        if not quiet and not project.s.is_quiet():
            click.echo(f"Using {db} database")
        cmd.append(f"--db={db}")
    elif key or project.s.PIPENV_PYUP_API_KEY:
        cmd.append(f"--key={key or project.s.PIPENV_PYUP_API_KEY}")
    else:
        PIPENV_SAFETY_DB = (
            "https://d2qjmgddvqvu75.cloudfront.net/aws/safety/pipenv/1.0.0/"
        )
        os.environ["SAFETY_ANNOUNCEMENTS_URL"] = f"{PIPENV_SAFETY_DB}announcements.json"
        cmd.append(f"--db={PIPENV_SAFETY_DB}")

    if ignore:
        for cve in ignore:
            cmd.extend(["--ignore", cve])

    os.environ["SAFETY_CUSTOM_INTEGRATION"] = "True"
    os.environ["SAFETY_SOURCE"] = "pipenv"
    os.environ["SAFETY_PURE_YAML"] = "True"

    output, error, exit_code = run_safety_check(cmd, quiet)

    if quiet:
        parse_safety_output(output, quiet)
    else:
        sys.stdout.write(output)
        sys.stderr.write(error)

    temp_requirements.unlink()
    sys.exit(exit_code)
