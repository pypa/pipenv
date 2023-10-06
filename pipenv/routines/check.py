import io
import json as simplejson
import logging
import os
import sys
import tempfile
from pathlib import Path

from pipenv import exceptions, pep508checker
from pipenv.utils.processes import run_command
from pipenv.utils.project import ensure_project
from pipenv.utils.shell import cmd_list_to_shell, project_python
from pipenv.vendor import click, plette


def build_options(
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
    import json

    if not verbose:
        logging.getLogger("pipenv").setLevel(logging.WARN)

    if not system:
        # Ensure that virtualenv is available.
        ensure_project(
            project,
            python=python,
            validate=False,
            warn=False,
            pypi_mirror=pypi_mirror,
        )
    if not quiet and not project.s.is_quiet():
        click.secho("Checking PEP 508 requirements...", bold=True)
    pep508checker_path = pep508checker.__file__.rstrip("cdo")
    safety_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "patched", "safety"
    )
    _cmd = [project_python(project, system=system)]
    # Run the PEP 508 checker in the virtualenv.
    cmd = _cmd + [Path(pep508checker_path).as_posix()]
    c = run_command(cmd, is_verbose=project.s.is_verbose())
    results = []
    if c.returncode is not None:
        try:
            results = simplejson.loads(c.stdout.strip())
        except json.JSONDecodeError:
            click.echo(
                "{}\n{}\n{}".format(
                    click.style(
                        "Failed parsing pep508 results: ",
                        fg="white",
                        bold=True,
                    ),
                    c.stdout.strip(),
                    c.stderr.strip(),
                )
            )
            sys.exit(1)
    # Load the pipfile.
    p = plette.Pipfile.load(open(project.pipfile_location))
    p = plette.Lockfile.with_meta_from(p)
    failed = False
    # Assert each specified requirement.
    for marker, specifier in p._data["_meta"]["requires"].items():
        if marker in results:
            try:
                assert results[marker] == specifier
            except AssertionError:
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
    else:
        if not quiet and not project.s.is_quiet():
            click.secho("Passed!", fg="green")
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
        if not isinstance(ignore, (tuple, list)):
            ignore = [ignore]
        ignored = [["--ignore", cve] for cve in ignore]
        if not quiet and not project.s.is_quiet():
            click.echo(
                "Notice: Ignoring Vulnerabilit{} {}".format(
                    "ies" if len(ignored) > 1 else "y",
                    click.style(", ".join(ignore), fg="yellow"),
                ),
                err=True,
            )
    else:
        ignored = []

    if use_installed:
        target_venv_packages = run_command(
            _cmd + ["-m", "pip", "list", "--format=freeze"],
            is_verbose=project.s.is_verbose(),
        )
    elif categories:
        target_venv_packages = run_command(
            ["pipenv", "requirements", "--categories", categories],
            is_verbose=project.s.is_verbose(),
        )
    else:
        target_venv_packages = run_command(
            ["pipenv", "requirements"], is_verbose=project.s.is_verbose()
        )

    temp_requirements = tempfile.NamedTemporaryFile(
        mode="w+",
        prefix=f"{project.virtualenv_name}",
        suffix="_requirements.txt",
        delete=False,
    )
    temp_requirements.write(target_venv_packages.stdout.strip())
    temp_requirements.close()

    options = build_options(
        audit_and_monitor=audit_and_monitor,
        exit_code=exit_code,
        output=output,
        save_json=save_json,
        policy_file=policy_file,
        safety_project=safety_project,
        temp_requirements_name=temp_requirements.name,
    )

    cmd = _cmd + [safety_path, "check"] + options

    if db:
        if not quiet and not project.s.is_quiet():
            click.echo(f"Using {db} database")
        cmd.append(f"--db={db}")
    elif key or project.s.PIPENV_PYUP_API_KEY:
        cmd = cmd + [f"--key={key or project.s.PIPENV_PYUP_API_KEY}"]
    else:
        PIPENV_SAFETY_DB = (
            "https://d2qjmgddvqvu75.cloudfront.net/aws/safety/pipenv/1.0.0/"
        )
        os.environ["SAFETY_ANNOUNCEMENTS_URL"] = f"{PIPENV_SAFETY_DB}announcements.json"
        cmd.append(f"--db={PIPENV_SAFETY_DB}")

    if ignored:
        for cve in ignored:
            cmd += cve

    os.environ["SAFETY_CUSTOM_INTEGRATION"] = "True"
    os.environ["SAFETY_SOURCE"] = "pipenv"
    os.environ["SAFETY_PURE_YAML"] = "True"

    from pipenv.patched.safety.cli import cli

    sys.argv = cmd[1:]

    if output == "minimal":
        from contextlib import redirect_stderr, redirect_stdout

        code = 0

        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            try:
                cli(prog_name="pipenv")
            except SystemExit as exit_signal:
                code = exit_signal.code

        report = out.getvalue()
        error = err.getvalue()

        try:
            json_report = simplejson.loads(report)
        except Exception:
            raise exceptions.PipenvCmdError(
                cmd_list_to_shell(cmd), report, error, exit_code=code
            )
        meta = json_report.get("report_meta")
        vulnerabilities_found = meta.get("vulnerabilities_found")

        fg = "green"
        message = "All good!"
        db_type = "commercial" if meta.get("api_key", False) else "free"

        if vulnerabilities_found >= 0:
            fg = "red"
            message = (
                f"Scan was complete using Safety’s {db_type} vulnerability database."
            )

        click.echo()
        click.secho(f"{vulnerabilities_found} vulnerabilities found.", fg=fg)
        click.echo()

        vulnerabilities = json_report.get("vulnerabilities", [])

        for vuln in vulnerabilities:
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
        sys.exit(code)

    cli(prog_name="pipenv")

    temp_requirements.remove()
