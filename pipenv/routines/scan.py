import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from pipenv import pep508checker
from pipenv.utils import console, err
from pipenv.utils.processes import run_command
from pipenv.utils.project import ensure_project
from pipenv.utils.shell import project_python
from pipenv.vendor import click, plette


def build_safety_check_options(
    audit_and_monitor=True,
    exit_code=True,
    output="screen",
    save_json="",
    policy_file="",
    safety_project=None,
    temp_requirements_path="",
    ignore=None,
    key=None,
    db=None,
    project=None,
):
    """Build command line options for the safety check command."""
    options = []

    # Add exit code option
    if exit_code:
        options.append("--exit-code")
    else:
        options.append("--continue-on-error")

    # Add audit and monitor option
    if audit_and_monitor:
        options.append("--audit-and-monitor")
    else:
        options.append("--disable-audit-and-monitor")

    # Map output formats to safety CLI options
    if output == "full-report":
        options.append("--full-report")
    elif output in ["json", "minimal"]:
        options.append("--json")
    elif output not in ["screen", "default"]:
        options.append(f"--output={output}")

    if save_json:
        options.append(f"--save-json={save_json}")

    if policy_file:
        options.append(f"--policy-file={policy_file}")

    if safety_project:
        options.append(f"--project={safety_project}")

    # Make sure we're using the absolute path to the requirements file
    if temp_requirements_path:
        options.extend(["--file", temp_requirements_path])
        console.print(f"[dim]Using requirements file: {temp_requirements_path}[/dim]")

    # Add database options
    if db:
        options.append(f"--db={db}")
    elif key or (project and project.s.PIPENV_PYUP_API_KEY):
        api_key = key or project.s.PIPENV_PYUP_API_KEY
        options.append(f"--key={api_key}")
    else:
        PIPENV_SAFETY_DB = "https://pyup.io/aws/safety/free/2.0.0/"
        os.environ["SAFETY_ANNOUNCEMENTS_URL"] = f"{PIPENV_SAFETY_DB}announcements.json"
        options.append(f"--db={PIPENV_SAFETY_DB}")

    # Add ignore options
    if ignore:
        for cve in ignore:
            options.extend(["--ignore", cve])

    return options


def build_safety_scan_options(
    output="screen",
    save_json="",
    policy_file="",
    temp_requirements_path="",
    key=None,
    db=None,
    project=None,
):
    """Build command line options for the safety scan command."""
    options = []
    global_options = []

    # Set output format
    if output not in ["screen", "default"]:
        options.append(f"--output={output}")

    # Add detailed output for screen format
    if output in ["screen", "default"]:
        options.append("--detailed-output")

    # Save results to file if requested
    if save_json:
        options.extend(["--save-as", "json", save_json])

    # Add policy file if specified
    if policy_file:
        options.append(f"--policy-file={policy_file}")

    # Add target directory (current directory by default)
    options.append("--target=.")

    # Add global options

    # Set stage to ci to avoid authentication prompt
    global_options.append("--stage=cicd")

    if key or (project and project.s.PIPENV_PYUP_API_KEY):
        api_key = key or project.s.PIPENV_PYUP_API_KEY
        global_options.append(f"--key={api_key}")
    else:
        # For CI stage, we need to provide a key
        # Use a dummy key to avoid authentication prompt
        global_options.append("--key=dummy-key")

    # Note: The --db option is not supported by the scan command
    # We'll set the SAFETY_API_URL environment variable instead
    if db:
        os.environ["SAFETY_API_URL"] = db
    else:
        PIPENV_SAFETY_DB = "https://pyup.io/aws/safety/free/2.0.0/"
        os.environ["SAFETY_ANNOUNCEMENTS_URL"] = f"{PIPENV_SAFETY_DB}announcements.json"

    return global_options, options


def run_pep508_check(project, system, python):
    """Run PEP 508 environment marker checks."""
    pep508checker_path = pep508checker.__file__.rstrip("cdo")
    cmd = [project_python(project, system=system), Path(pep508checker_path).as_posix()]
    c = run_command(cmd, is_verbose=project.s.is_verbose())

    if c.returncode is not None:
        try:
            return json.loads(c.stdout.strip())
        except json.JSONDecodeError:
            err.print(
                f"Failed parsing pep508 results:\n{c.stdout.strip()}\n{c.stderr.strip()}"
            )
            sys.exit(1)
    return {}


def check_pep508_requirements(project, results, quiet):
    """Verify PEP 508 environment markers in Pipfile match the current environment."""
    p = plette.Pipfile.load(open(project.pipfile_location))
    p = plette.Lockfile.with_meta_from(p)
    failed = False

    for marker, specifier in p._data["_meta"]["requires"].items():
        if marker in results:
            if results[marker] != specifier:
                failed = True
                err.print(
                    f"Specifier [green]{marker}[/green] does not match [cyan]{specifier}[/cyan] "
                    f"([yellow]{results[marker]}[/yellow])."
                )

    if failed:
        err.print("[red]Failed![/red]")
        sys.exit(1)
    elif not quiet and not project.s.is_quiet():
        console.print("[green]Passed![/green]")


def get_requirements(project, use_installed, categories):
    """Get package requirements from either installed packages or Pipfile.lock."""
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


def create_temp_requirements_file(requirements_content):
    """Create a temporary requirements file for safety to scan.

    Uses the tempfile module to ensure proper cleanup.
    """
    fd, temp_path = tempfile.mkstemp(prefix="pipenv_safety_", suffix=".txt")
    try:
        with os.fdopen(fd, "w") as temp_file:
            temp_file.write(requirements_content)

        console.print(f"[dim]Created temporary requirements file: {temp_path}[/dim]")
        return temp_path
    except Exception as e:
        err.print(f"[red]Failed to create temporary requirements file: {e}[/red]")
        os.unlink(temp_path)
        sys.exit(1)


def is_safety_installed(project=None, system=False):
    """Check if safety is installed by trying to run it."""
    import subprocess

    if project:
        python = project_python(project, system=system)
    else:
        python = sys.executable

    try:
        # Try to run safety --help to check if it's installed
        result = subprocess.run(
            [python, "-m", "safety", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def install_safety(project, system=False, auto_install=False):
    """Install safety and its dependencies."""
    python = project_python(project, system=system)

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
        return False

    console.print("[green]Installing safety...[/green]")
    # Install safety directly rather than as an extra to ensure it works in development mode
    cmd = [python, "-m", "pip", "install", "safety>=3.0.0", "typer>=0.9.0", "--quiet"]
    c = run_command(cmd)

    if c.returncode != 0:
        err.print(
            "[red]Failed to install safety. Please install it manually with 'pip install pipenv[safety]'[/red]"
        )
        return False

    console.print("[green]Safety installed successfully![/green]")
    return True


def run_safety_scan(cmd, quiet):
    """Run safety scan with the given command."""
    # Run safety as a separate process instead of importing it
    import subprocess

    try:
        # Use subprocess to run safety directly
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        err.print(f"[red]Error running safety: {str(e)}[/red]")
        sys.exit(1)


def parse_safety_output(output, quiet):
    """Parse and display safety scan output in a user-friendly format."""
    try:
        json_report = json.loads(output)
        meta = json_report.get("report_meta", {})
        vulnerabilities_found = meta.get("vulnerabilities_found", 0)
        db_type = "commercial" if meta.get("api_key", False) else "free"

        if quiet:
            color = "red" if vulnerabilities_found else "green"
            console.print(
                f"[{color}]{vulnerabilities_found} vulnerabilities found.[/{color}]"
            )
        else:
            color = "red" if vulnerabilities_found else "green"
            message = f"Scan complete using Safety's {db_type} vulnerability database."
            console.print()
            console.print(
                f"[{color}]{vulnerabilities_found} vulnerabilities found.[/{color}]"
            )
            console.print()

            for vuln in json_report.get("vulnerabilities", []):
                console.print(
                    f"[bold red]{vuln['vulnerability_id']}[/bold red]: "
                    f"[green]{vuln['package_name']}[/green] "
                    f"[yellow bold]{vuln['analyzed_version']}[/yellow bold] "
                    f"open to vulnerability [bold]{vuln['vulnerability_id']}[/bold] "
                    f"([yellow]{vuln['vulnerable_spec']}[/yellow]). "
                    f"More info: [bold]{vuln['more_info_url']}[/bold]"
                )
                console.print(f"{vuln['advisory']}")
                console.print()

            console.print(f"[white bold]{message}[/white bold]")

    except json.JSONDecodeError:
        err.print("Failed to parse Safety output.")


def do_scan(  # noqa: PLR0913
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
    legacy_mode=False,
    auto_install=False,
):
    """Run a security vulnerability scan on dependencies.

    This is the new, improved version of the check command.
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
        console.print("[bold]Checking PEP 508 requirements...[/bold]")

    results = run_pep508_check(project, system, python)
    check_pep508_requirements(project, results, quiet)

    if not project.lockfile_exists:
        return

    if not quiet and not project.s.is_quiet():
        if use_installed:
            console.print(
                "[bold]Scanning installed packages for vulnerabilities...[/bold]"
            )
        else:
            console.print(
                "[bold]Scanning Pipfile.lock packages for vulnerabilities...[/bold]"
            )

    if ignore:
        ignore = [ignore] if not isinstance(ignore, (tuple, list)) else ignore
        if not quiet and not project.s.is_quiet():
            err.print(
                "Notice: Ignoring Vulnerabilit{} {}".format(
                    "ies" if len(ignore) > 1 else "y",
                    f"[yellow]{', '.join(ignore)}[/yellow]",
                )
            )

    # Get requirements and create a temporary file
    requirements = get_requirements(project, use_installed, categories)
    temp_requirements_path = create_temp_requirements_file(requirements.stdout.strip())

    try:
        # Check if safety is installed
        if not is_safety_installed(project, system=system):
            if not install_safety(project, system=system, auto_install=auto_install):
                console.print("[yellow]Vulnerability scanning aborted.[/yellow]")
                return

            # Check again after installation
            if not is_safety_installed(project, system=system):
                # Try to install safety directly using subprocess to ensure it's in the correct environment
                import subprocess

                try:
                    python = project_python(project, system=system)
                    subprocess.check_call(
                        [python, "-m", "pip", "install", "safety>=3.0.0", "typer>=0.9.0"],
                        capture_output=True,
                    )
                except Exception:
                    pass

            if not is_safety_installed(project, system=system):
                err.print(
                    "[red]Safety installation was reported successful but module not found. "
                    "Please try again or install manually with 'pip install pipenv[safety]'[/red]"
                )
                return

        # Set up environment variables for safety
        os.environ["SAFETY_CUSTOM_INTEGRATION"] = "True"
        os.environ["SAFETY_SOURCE"] = "pipenv"
        os.environ["SAFETY_PURE_YAML"] = "True"

        # Build options for safety command based on mode
        if legacy_mode:
            # Use the check command with appropriate options
            options = build_safety_check_options(
                audit_and_monitor=audit_and_monitor,
                exit_code=exit_code,
                output=output,
                save_json=save_json,
                policy_file=policy_file,
                safety_project=safety_project,
                temp_requirements_path=temp_requirements_path,
                ignore=ignore,
                key=key,
                db=db,
                project=project,
            )
            cmd = [
                project_python(project, system=system),
                "-m",
                "safety",
                "check",
            ] + options
        else:
            # Use the scan command with appropriate options
            global_options, scan_options = build_safety_scan_options(
                output=output,
                save_json=save_json,
                policy_file=policy_file,
                temp_requirements_path=temp_requirements_path,
                key=key,
                db=db,
                project=project,
            )

            # For scan command, global options come before the command
            cmd = (
                [project_python(project, system=system), "-m", "safety"]
                + global_options
                + ["scan"]
                + scan_options
            )

            # Note: scan command doesn't support ignore directly, but we can use a policy file
            if ignore and not policy_file:
                console.print(
                    "[yellow]Note: Ignoring vulnerabilities with the scan command requires a policy file.[/yellow]"
                )

        # Run the safety scan
        output, error, exit_code = run_safety_scan(cmd, quiet)

        if quiet:
            parse_safety_output(output, quiet)
        else:
            sys.stdout.write(output)
            sys.stderr.write(error)

        sys.exit(exit_code)
    finally:
        # Always clean up the temporary file
        try:
            os.unlink(temp_requirements_path)
        except Exception as e:
            err.print(
                f"[yellow]Warning: Failed to delete temporary file {temp_requirements_path}: {e}[/yellow]"
            )
