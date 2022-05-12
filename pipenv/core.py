import json as simplejson
import logging
import os
import shutil
import sys
import tempfile
import time
import warnings
from pathlib import Path
from posixpath import expandvars

import click
import dotenv
import pipfile
import vistir

from pipenv import environments, exceptions, pep508checker, progress
from pipenv._compat import decode_for_output, fix_utf8
from pipenv.patched import crayons
from pipenv.utils.dependencies import (
    convert_deps_to_pip,
    get_canonical_names,
    is_pinned,
    is_required_version,
    is_star,
    pep423_name,
    python_version,
)
from pipenv.utils.indexes import get_source_list, parse_indexes, prepare_pip_source_args
from pipenv.utils.internet import download_file, get_host_and_port, is_valid_url
from pipenv.utils.processes import run_command
from pipenv.utils.resolver import venv_resolve_deps
from pipenv.utils.shell import (
    cmd_list_to_shell,
    find_python,
    is_python_command,
    subprocess_run,
)
from pipenv.utils.spinner import create_spinner

if environments.is_type_checking():
    from typing import Dict, List, Optional, Union

    from pipenv.project import Project
    from pipenv.vendor.requirementslib.models.requirements import Requirement

    TSourceDict = Dict[str, Union[str, bool]]


# Packages that should be ignored later.
BAD_PACKAGES = (
    "distribute",
    "packaging",
    "pip",
    "pkg-resources",
    "setuptools",
    "wheel",
)

FIRST_PACKAGES = ("cython",)

if not environments.PIPENV_HIDE_EMOJIS:
    now = time.localtime()
    # Halloween easter-egg.
    if ((now.tm_mon == 10) and (now.tm_mday == 30)) or (
        (now.tm_mon == 10) and (now.tm_mday == 31)
    ):
        INSTALL_LABEL = "🎃   "
    # Christmas easter-egg.
    elif ((now.tm_mon == 12) and (now.tm_mday == 24)) or (
        (now.tm_mon == 12) and (now.tm_mday == 25)
    ):
        INSTALL_LABEL = "🎅   "
    else:
        INSTALL_LABEL = "🐍   "
    INSTALL_LABEL2 = crayons.normal("☤  ", bold=True)
    STARTING_LABEL = "    "
else:
    INSTALL_LABEL = "   "
    INSTALL_LABEL2 = "   "
    STARTING_LABEL = "   "

# Disable colors, for the color blind and others who do not prefer colors.
if environments.PIPENV_COLORBLIND:
    crayons.disable()


def do_clear(project):
    click.echo(crayons.normal(fix_utf8("Clearing caches..."), bold=True))
    try:
        from pip._internal import locations
    except ImportError:  # pip 9.
        from pip import locations

    try:
        shutil.rmtree(
            project.s.PIPENV_CACHE_DIR, onerror=vistir.path.handle_remove_readonly
        )
        # Other processes may be writing into this directory simultaneously.
        shutil.rmtree(
            locations.USER_CACHE_DIR,
            ignore_errors=environments.PIPENV_IS_CI,
            onerror=vistir.path.handle_remove_readonly,
        )
    except OSError as e:
        # Ignore FileNotFoundError. This is needed for Python 2.7.
        import errno

        if e.errno == errno.ENOENT:
            pass
        raise


def load_dot_env(project, as_dict=False, quiet=False):
    """Loads .env file into sys.environ."""
    if not project.s.PIPENV_DONT_LOAD_ENV:
        # If the project doesn't exist yet, check current directory for a .env file
        project_directory = project.project_directory or "."
        dotenv_file = project.s.PIPENV_DOTENV_LOCATION or os.sep.join(
            [project_directory, ".env"]
        )

        if not os.path.isfile(dotenv_file) and project.s.PIPENV_DOTENV_LOCATION:
            click.echo(
                "{}: file {}={} does not exist!!\n{}".format(
                    crayons.red("Warning", bold=True),
                    crayons.normal("PIPENV_DOTENV_LOCATION", bold=True),
                    crayons.normal(project.s.PIPENV_DOTENV_LOCATION, bold=True),
                    crayons.red("Not loading environment variables.", bold=True),
                ),
                err=True,
            )
        if as_dict:
            return dotenv.dotenv_values(dotenv_file)
        elif os.path.isfile(dotenv_file):
            if not quiet:
                click.echo(
                    crayons.normal(
                        fix_utf8("Loading .env environment variables..."), bold=True
                    ),
                    err=True,
                )
            dotenv.load_dotenv(dotenv_file, override=True)
        project.s.initialize()


def cleanup_virtualenv(project, bare=True):
    """Removes the virtualenv directory from the system."""
    if not bare:
        click.echo(crayons.red("Environment creation aborted."))
    try:
        # Delete the virtualenv.
        shutil.rmtree(project.virtualenv_location)
    except OSError as e:
        click.echo(
            "{} An error occurred while removing {}!".format(
                crayons.red("Error: ", bold=True),
                crayons.green(project.virtualenv_location),
            ),
            err=True,
        )
        click.echo(crayons.cyan(e), err=True)


def import_requirements(project, r=None, dev=False):
    from pipenv.patched.notpip._internal.req.constructors import (
        install_req_from_parsed_requirement,
    )
    from pipenv.patched.notpip._vendor import requests as pip_requests
    from pipenv.vendor.pip_shims.shims import parse_requirements

    # Parse requirements.txt file with Pip's parser.
    # Pip requires a `PipSession` which is a subclass of requests.Session.
    # Since we're not making any network calls, it's initialized to nothing.
    if r:
        assert os.path.isfile(r)
    # Default path, if none is provided.
    if r is None:
        r = project.requirements_location
    with open(r) as f:
        contents = f.read()
    indexes = []
    trusted_hosts = []
    # Find and add extra indexes.
    for line in contents.split("\n"):
        index, extra_index, trusted_host, _ = parse_indexes(line.strip(), strict=True)
        if index:
            indexes = [index]
        if extra_index:
            indexes.append(extra_index)
        if trusted_host:
            trusted_hosts.append(get_host_and_port(trusted_host))
    indexes = sorted(set(indexes))
    trusted_hosts = sorted(set(trusted_hosts))
    reqs = [
        install_req_from_parsed_requirement(f)
        for f in parse_requirements(r, session=pip_requests)
    ]
    for package in reqs:
        if package.name not in BAD_PACKAGES:
            if package.link is not None:
                package_string = (
                    f"-e {package.link}" if package.editable else str(package.link)
                )
                project.add_package_to_pipfile(package_string, dev=dev)
            else:
                project.add_package_to_pipfile(str(package.req), dev=dev)
    for index in indexes:
        # don't require HTTPS for trusted hosts (see: https://pip.pypa.io/en/stable/cli/pip/#cmdoption-trusted-host)
        host_and_port = get_host_and_port(index)
        require_valid_https = not any(
            (
                v in trusted_hosts
                for v in (
                    host_and_port,
                    host_and_port.partition(":")[
                        0
                    ],  # also check if hostname without port is in trusted_hosts
                )
            )
        )
        project.add_index_to_pipfile(index, verify_ssl=require_valid_https)
    project.recase_pipfile()


def ensure_environment():
    # Skip this on Windows...
    if os.name != "nt":
        if "LANG" not in os.environ:
            click.echo(
                "{}: the environment variable {} is not set!"
                "\nWe recommend setting this in {} (or equivalent) for "
                "proper expected behavior.".format(
                    crayons.red("Warning", bold=True),
                    crayons.normal("LANG", bold=True),
                    crayons.green("~/.profile"),
                ),
                err=True,
            )


def ensure_pipfile(project, validate=True, skip_requirements=False, system=False):
    """Creates a Pipfile for the project, if it doesn't exist."""

    # Assert Pipfile exists.
    python = (
        project._which("python")
        if not (project.s.USING_DEFAULT_PYTHON or system)
        else None
    )
    if project.pipfile_is_empty:
        # Show an error message and exit if system is passed and no pipfile exists
        if system and not project.s.PIPENV_VIRTUALENV:
            raise exceptions.PipenvOptionsError(
                "--system",
                "--system is intended to be used for pre-existing Pipfile "
                "installation, not installation of specific packages. Aborting.",
            )
        # If there's a requirements file, but no Pipfile...
        if project.requirements_exists and not skip_requirements:
            requirements_dir_path = os.path.dirname(project.requirements_location)
            click.echo(
                "{0} found in {1} instead of {2}! Converting...".format(
                    crayons.normal("requirements.txt", bold=True),
                    crayons.yellow(requirements_dir_path, bold=True),
                    crayons.normal("Pipfile", bold=True),
                )
            )
            # Create a Pipfile...
            project.create_pipfile(python=python)
            with create_spinner("Importing requirements...", project.s) as sp:
                # Import requirements.txt.
                try:
                    import_requirements(project)
                except Exception:
                    sp.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format("Failed..."))
                else:
                    sp.ok(environments.PIPENV_SPINNER_OK_TEXT.format("Success!"))
            # Warn the user of side-effects.
            click.echo(
                "{0}: Your {1} now contains pinned versions, if your {2} did. \n"
                "We recommend updating your {1} to specify the {3} version, instead."
                "".format(
                    crayons.red("Warning", bold=True),
                    crayons.normal("Pipfile", bold=True),
                    crayons.normal("requirements.txt", bold=True),
                    crayons.normal('"*"', bold=True),
                )
            )
        else:
            click.echo(
                crayons.normal(
                    fix_utf8("Creating a Pipfile for this project..."), bold=True
                ),
                err=True,
            )
            # Create the pipfile if it doesn't exist.
            project.create_pipfile(python=python)
    # Validate the Pipfile's contents.
    if validate and project.virtualenv_exists and not project.s.PIPENV_SKIP_VALIDATION:
        # Ensure that Pipfile is using proper casing.
        p = project.parsed_pipfile
        changed = project.ensure_proper_casing()
        # Write changes out to disk.
        if changed:
            click.echo(
                crayons.normal("Fixing package names in Pipfile...", bold=True), err=True
            )
            project.write_toml(p)


def find_a_system_python(line):
    """Find a Python installation from a given line.

    This tries to parse the line in various of ways:

    * Looks like an absolute path? Use it directly.
    * Looks like a py.exe call? Use py.exe to get the executable.
    * Starts with "py" something? Looks like a python command. Try to find it
      in PATH, and use it directly.
    * Search for "python" and "pythonX.Y" executables in PATH to find a match.
    * Nothing fits, return None.
    """

    from .vendor.pythonfinder import Finder

    finder = Finder(system=False, global_search=True)
    if not line:
        return next(iter(finder.find_all_python_versions()), None)
    # Use the windows finder executable
    if (line.startswith("py ") or line.startswith("py.exe ")) and os.name == "nt":
        line = line.split(" ", 1)[1].lstrip("-")
    python_entry = find_python(finder, line)
    return python_entry


def ensure_python(project, three=None, python=None):
    # Runtime import is necessary due to the possibility that the environments module may have been reloaded.
    if project.s.PIPENV_PYTHON and python is False and three is None:
        python = project.s.PIPENV_PYTHON

    def abort(msg=""):
        click.echo(
            "{}\nYou can specify specific versions of Python with:\n{}".format(
                crayons.red(msg),
                crayons.yellow(
                    "$ pipenv --python {}".format(os.sep.join(("path", "to", "python")))
                ),
            ),
            err=True,
        )
        sys.exit(1)

    project.s.USING_DEFAULT_PYTHON = three is None and not python
    # Find out which python is desired.
    if not python:
        python = convert_three_to_python(three, python)
    if not python:
        python = project.required_python_version
    if not python:
        python = project.s.PIPENV_DEFAULT_PYTHON_VERSION
    path_to_python = find_a_system_python(python)
    if project.s.is_verbose():
        click.echo(f"Using python: {python}", err=True)
        click.echo(f"Path to python: {path_to_python}", err=True)
    if not path_to_python and python is not None:
        # We need to install Python.
        click.echo(
            "{}: Python {} {}".format(
                crayons.red("Warning", bold=True),
                crayons.cyan(python),
                fix_utf8("was not found on your system..."),
            ),
            err=True,
        )
        # check for python installers
        from .installers import Asdf, InstallerError, InstallerNotFound, Pyenv

        # prefer pyenv if both pyenv and asdf are installed as it's
        # dedicated to python installs so probably the preferred
        # method of the user for new python installs.
        installer = None
        if not project.s.PIPENV_DONT_USE_PYENV:
            try:
                installer = Pyenv(project)
            except InstallerNotFound:
                pass
        if installer is None and not project.s.PIPENV_DONT_USE_ASDF:
            try:
                installer = Asdf(project)
            except InstallerNotFound:
                pass

        if not installer:
            abort("Neither 'pyenv' nor 'asdf' could be found to install Python.")
        else:
            if environments.SESSION_IS_INTERACTIVE or project.s.PIPENV_YES:
                try:
                    version = installer.find_version_to_install(python)
                except ValueError:
                    abort()
                except InstallerError as e:
                    abort(f"Something went wrong while installing Python:\n{e.err}")
                s = "{} {} {}".format(
                    "Would you like us to install",
                    crayons.green(f"CPython {version}"),
                    f"with {installer}?",
                )
                # Prompt the user to continue...
                if not (project.s.PIPENV_YES or click.confirm(s, default=True)):
                    abort()
                else:
                    # Tell the user we're installing Python.
                    click.echo(
                        "{} {} {} {}{}".format(
                            crayons.normal("Installing", bold=True),
                            crayons.green(f"CPython {version}", bold=True),
                            crayons.normal(f"with {installer.cmd}", bold=True),
                            crayons.normal("(this may take a few minutes)"),
                            crayons.normal("...", bold=True),
                        )
                    )
                    with create_spinner("Installing python...", project.s) as sp:
                        try:
                            c = installer.install(version)
                        except InstallerError as e:
                            sp.fail(
                                environments.PIPENV_SPINNER_FAIL_TEXT.format("Failed...")
                            )
                            click.echo(fix_utf8("Something went wrong..."), err=True)
                            click.echo(crayons.cyan(e.err), err=True)
                        else:
                            sp.ok(environments.PIPENV_SPINNER_OK_TEXT.format("Success!"))
                            # Print the results, in a beautiful blue...
                            click.echo(crayons.cyan(c.stdout), err=True)
                            # Clear the pythonfinder caches
                            from .vendor.pythonfinder import Finder

                            finder = Finder(system=False, global_search=True)
                            finder.find_python_version.cache_clear()
                            finder.find_all_python_versions.cache_clear()
                    # Find the newly installed Python, hopefully.
                    version = str(version)
                    path_to_python = find_a_system_python(version)
                    try:
                        assert python_version(path_to_python) == version
                    except AssertionError:
                        click.echo(
                            "{}: The Python you just installed is not available on your {}, apparently."
                            "".format(
                                crayons.red("Warning", bold=True),
                                crayons.normal("PATH", bold=True),
                            ),
                            err=True,
                        )
                        sys.exit(1)
    return path_to_python


def ensure_virtualenv(
    project, three=None, python=None, site_packages=None, pypi_mirror=None
):
    """Creates a virtualenv, if one doesn't exist."""

    def abort():
        sys.exit(1)

    if not project.virtualenv_exists:
        try:
            # Ensure environment variables are set properly.
            ensure_environment()
            # Ensure Python is available.
            python = ensure_python(project, three=three, python=python)
            if python is not None and not isinstance(python, str):
                python = python.path.as_posix()
            # Create the virtualenv.
            # Abort if --system (or running in a virtualenv).
            if project.s.PIPENV_USE_SYSTEM:
                click.echo(
                    crayons.red(
                        "You are attempting to re–create a virtualenv that "
                        "Pipenv did not create. Aborting."
                    )
                )
                sys.exit(1)
            do_create_virtualenv(
                project,
                python=python,
                site_packages=site_packages,
                pypi_mirror=pypi_mirror,
            )
        except KeyboardInterrupt:
            # If interrupted, cleanup the virtualenv.
            cleanup_virtualenv(project, bare=False)
            sys.exit(1)
    # If --python or --three were passed...
    elif (python) or (three is not None) or (site_packages is not None):
        project.s.USING_DEFAULT_PYTHON = False
        # Ensure python is installed before deleting existing virtual env
        python = ensure_python(project, three=three, python=python)
        if python is not None and not isinstance(python, str):
            python = python.path.as_posix()

        click.echo(crayons.red("Virtualenv already exists!"), err=True)
        # If VIRTUAL_ENV is set, there is a possibility that we are
        # going to remove the active virtualenv that the user cares
        # about, so confirm first.
        if "VIRTUAL_ENV" in os.environ:
            if not (
                project.s.PIPENV_YES
                or click.confirm("Use existing virtualenv?", default=True)
            ):
                abort()
        click.echo(
            crayons.normal(fix_utf8("Using existing virtualenv..."), bold=True), err=True
        )
        # Remove the virtualenv.
        cleanup_virtualenv(project, bare=True)
        # Call this function again.
        ensure_virtualenv(
            project,
            three=three,
            python=python,
            site_packages=site_packages,
            pypi_mirror=pypi_mirror,
        )


def ensure_project(
    project,
    three=None,
    python=None,
    validate=True,
    system=False,
    warn=True,
    site_packages=None,
    deploy=False,
    skip_requirements=False,
    pypi_mirror=None,
    clear=False,
):
    """Ensures both Pipfile and virtualenv exist for the project."""

    # Automatically use an activated virtualenv.
    if project.s.PIPENV_USE_SYSTEM or project.virtualenv_exists:
        system_or_exists = True
    else:
        system_or_exists = system  # default to False
    if not project.pipfile_exists and deploy:
        raise exceptions.PipfileNotFound
    # Skip virtualenv creation when --system was used.
    if not system_or_exists:
        ensure_virtualenv(
            project,
            three=three,
            python=python,
            site_packages=site_packages,
            pypi_mirror=pypi_mirror,
        )
        if warn:
            # Warn users if they are using the wrong version of Python.
            if project.required_python_version:
                path_to_python = project._which("python") or project._which("py")
                if path_to_python and project.required_python_version not in (
                    python_version(path_to_python) or ""
                ):
                    click.echo(
                        "{}: Your Pipfile requires {} {}, "
                        "but you are using {} ({}).".format(
                            crayons.red("Warning", bold=True),
                            crayons.normal("python_version", bold=True),
                            crayons.cyan(project.required_python_version),
                            crayons.cyan(python_version(path_to_python) or "unknown"),
                            crayons.green(shorten_path(path_to_python)),
                        ),
                        err=True,
                    )
                    click.echo(
                        "  {} and rebuilding the virtual environment "
                        "may resolve the issue.".format(crayons.green("$ pipenv --rm")),
                        err=True,
                    )
                    if not deploy:
                        click.echo(
                            "  {} will surely fail."
                            "".format(crayons.yellow("$ pipenv check")),
                            err=True,
                        )
                    else:
                        raise exceptions.DeployException
    # Ensure the Pipfile exists.
    ensure_pipfile(
        project,
        validate=validate,
        skip_requirements=skip_requirements,
        system=system_or_exists,
    )


def shorten_path(location, bold=False):
    """Returns a visually shorter representation of a given system path."""
    original = location
    short = os.sep.join(
        [s[0] if len(s) > (len("2long4")) else s for s in location.split(os.sep)]
    )
    short = short.split(os.sep)
    short[-1] = original.split(os.sep)[-1]
    if bold:
        short[-1] = str(crayons.normal(short[-1], bold=True))
    return os.sep.join(short)


# return short
def do_where(project, virtualenv=False, bare=True):
    """Executes the where functionality."""
    if not virtualenv:
        if not project.pipfile_exists:
            click.echo(
                "No Pipfile present at project home. Consider running "
                "{} first to automatically generate a Pipfile for you."
                "".format(crayons.green("`pipenv install`")),
                err=True,
            )
            return
        location = project.pipfile_location
        # Shorten the virtual display of the path to the virtualenv.
        if not bare:
            location = shorten_path(location)
            click.echo(
                "Pipfile found at {}.\n  Considering this to be the project home."
                "".format(crayons.green(location)),
                err=True,
            )
        else:
            click.echo(project.project_directory)
    else:
        location = project.virtualenv_location
        if not bare:
            click.echo(f"Virtualenv location: {crayons.green(location)}", err=True)
        else:
            click.echo(location)


def _cleanup_procs(project, procs, failed_deps_queue, retry=True):
    while not procs.empty():
        c = procs.get()
        try:
            out, err = c.communicate()
        except AttributeError:
            out, err = c.stdout, c.stderr
        failed = c.returncode != 0
        if "Ignoring" in out:
            click.echo(crayons.yellow(out.strip()))
        elif project.s.is_verbose():
            click.echo(crayons.cyan(out.strip() or err.strip()))
        # The Installation failed...
        if failed:
            # If there is a mismatch in installed locations or the install fails
            # due to wrongful disabling of pep517, we should allow for
            # additional passes at installation
            if "does not match installed location" in err:
                project.environment.expand_egg_links()
                click.echo(
                    "{}".format(
                        crayons.yellow(
                            "Failed initial installation: Failed to overwrite existing "
                            "package, likely due to path aliasing. Expanding and trying "
                            "again!"
                        )
                    )
                )
                dep = c.dep.copy()
                dep.use_pep517 = True
            elif "Disabling PEP 517 processing is invalid" in err:
                dep = c.dep.copy()
                dep.use_pep517 = True
            elif not retry:
                # The Installation failed...
                # We echo both c.stdout and c.stderr because pip returns error details on out.
                err = err.strip().splitlines() if err else []
                out = out.strip().splitlines() if out else []
                err_lines = [line for message in [out, err] for line in message]
                # Return the subprocess' return code.
                raise exceptions.InstallError(c.dep.name, extra=err_lines)
            else:
                # Alert the user.
                dep = c.dep.copy()
                dep.use_pep517 = False
                click.echo(
                    "{} {}! Will try again.".format(
                        crayons.red("An error occurred while installing"),
                        crayons.green(dep.as_line()),
                    ),
                    err=True,
                )
            # Save the Failed Dependency for later.
            failed_deps_queue.put(dep)


def batch_install(
    project,
    deps_list,
    procs,
    failed_deps_queue,
    requirements_dir,
    no_deps=True,
    ignore_hashes=False,
    allow_global=False,
    blocking=False,
    pypi_mirror=None,
    retry=True,
    sequential_deps=None,
):
    from .vendor.requirementslib.models.utils import (
        strip_extras_markers_from_requirement,
    )

    if sequential_deps is None:
        sequential_deps = []
    failed = not retry
    install_deps = not no_deps
    if not failed:
        label = INSTALL_LABEL if not environments.PIPENV_HIDE_EMOJIS else ""
    else:
        label = INSTALL_LABEL2

    deps_to_install = deps_list[:]
    deps_to_install.extend(sequential_deps)
    deps_to_install = [
        dep for dep in deps_to_install if not project.environment.is_satisfied(dep)
    ]
    sequential_dep_names = [d.name for d in sequential_deps]

    deps_list_bar = progress.bar(
        deps_to_install, width=32, label=label, hide=environments.PIPENV_IS_CI
    )

    trusted_hosts = []
    # Install these because
    for dep in deps_list_bar:
        extra_indexes = []
        if dep.req.req:
            dep.req.req = strip_extras_markers_from_requirement(dep.req.req)
        if dep.markers:
            dep.markers = str(strip_extras_markers_from_requirement(dep.get_markers()))
        # Install the module.
        is_artifact = False
        if dep.is_file_or_url and (
            dep.is_direct_url
            or any(dep.req.uri.endswith(ext) for ext in ["zip", "tar.gz"])
        ):
            is_artifact = True
        elif dep.is_vcs:
            is_artifact = True
        if not project.s.PIPENV_RESOLVE_VCS and is_artifact and not dep.editable:
            install_deps = True
            no_deps = False

        with vistir.contextmanagers.temp_environ():
            if not allow_global:
                os.environ["PIP_USER"] = "0"
                if "PYTHONHOME" in os.environ:
                    del os.environ["PYTHONHOME"]
            if "GIT_CONFIG" in os.environ and dep.is_vcs:
                del os.environ["GIT_CONFIG"]
            use_pep517 = True
            if failed and not dep.is_vcs:
                use_pep517 = getattr(dep, "use_pep517", False)

            is_sequential = sequential_deps and dep.name in sequential_dep_names
            is_blocking = any([dep.editable, dep.is_vcs, blocking, is_sequential])
            c = pip_install(
                project,
                dep,
                ignore_hashes=any([ignore_hashes, dep.editable, dep.is_vcs]),
                allow_global=allow_global,
                no_deps=not install_deps,
                block=is_blocking,
                index=dep.index,
                requirements_dir=requirements_dir,
                pypi_mirror=pypi_mirror,
                trusted_hosts=trusted_hosts,
                extra_indexes=extra_indexes,
                use_pep517=use_pep517,
            )
            c.dep = dep

            procs.put(c)
            if procs.full() or procs.qsize() == len(deps_list) or is_sequential:
                _cleanup_procs(project, procs, failed_deps_queue, retry=retry)


def do_install_dependencies(
    project,
    dev=False,
    dev_only=False,
    bare=False,
    emit_requirements=False,
    allow_global=False,
    ignore_hashes=False,
    skip_lock=False,
    concurrent=True,
    requirements_dir=None,
    pypi_mirror=None,
):
    """ "
    Executes the install functionality.

    If emit_requirements is True, simply spits out a requirements format to stdout.
    """

    import queue

    if emit_requirements:
        bare = True
    # Load the lockfile if it exists, or if dev_only is being used.
    if skip_lock or not project.lockfile_exists:
        if not bare:
            click.echo(
                crayons.normal(
                    fix_utf8("Installing dependencies from Pipfile..."), bold=True
                )
            )
        # skip_lock should completely bypass the lockfile (broken in 4dac1676)
        lockfile = project.get_or_create_lockfile(from_pipfile=True)
    else:
        lockfile = project.get_or_create_lockfile()
        if not bare:
            click.echo(
                crayons.normal(
                    fix_utf8(
                        "Installing dependencies from Pipfile.lock ({})...".format(
                            lockfile["_meta"].get("hash", {}).get("sha256")[-6:]
                        )
                    ),
                    bold=True,
                )
            )
    # Allow pip to resolve dependencies when in skip-lock mode.
    no_deps = not skip_lock  # skip_lock true, no_deps False, pip resolves deps
    dev = dev or dev_only
    deps_list = list(lockfile.get_requirements(dev=dev, only=dev_only))
    if emit_requirements:
        index_args = prepare_pip_source_args(
            get_source_list(project, pypi_mirror=pypi_mirror)
        )
        index_args = " ".join(index_args).replace(" -", "\n-")
        deps = [req.as_line(sources=False, include_hashes=False) for req in deps_list]
        click.echo(index_args)
        click.echo("\n".join(sorted(deps)))
        sys.exit(0)
    if concurrent:
        nprocs = project.s.PIPENV_MAX_SUBPROCESS
    else:
        nprocs = 1
    procs = queue.Queue(maxsize=nprocs)
    failed_deps_queue = queue.Queue()
    if skip_lock:
        ignore_hashes = True
    editable_or_vcs_deps = [dep for dep in deps_list if (dep.editable or dep.vcs)]
    normal_deps = [dep for dep in deps_list if not (dep.editable or dep.vcs)]
    install_kwargs = {
        "no_deps": no_deps,
        "ignore_hashes": ignore_hashes,
        "allow_global": allow_global,
        "blocking": not concurrent,
        "pypi_mirror": pypi_mirror,
        "sequential_deps": editable_or_vcs_deps,
    }

    batch_install(
        project, normal_deps, procs, failed_deps_queue, requirements_dir, **install_kwargs
    )

    if not procs.empty():
        _cleanup_procs(project, procs, failed_deps_queue)

    # Iterate over the hopefully-poorly-packaged dependencies...
    if not failed_deps_queue.empty():
        click.echo(
            crayons.normal(
                fix_utf8("Installing initially failed dependencies..."), bold=True
            )
        )
        retry_list = []
        while not failed_deps_queue.empty():
            failed_dep = failed_deps_queue.get()
            retry_list.append(failed_dep)
        install_kwargs.update({"retry": False})
        batch_install(
            project,
            retry_list,
            procs,
            failed_deps_queue,
            requirements_dir,
            **install_kwargs,
        )
    if not procs.empty():
        _cleanup_procs(project, procs, failed_deps_queue, retry=False)
    if not failed_deps_queue.empty():
        failed_list = []
        while not failed_deps_queue.empty():
            failed_dep = failed_deps_queue.get()
            failed_list.append(failed_dep)
        click.echo(
            click.style(
                f"Failed to install some dependency or packages.  "
                f"The following have failed installation and attempted retry: {failed_list}",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)


def convert_three_to_python(three, python):
    """Converts a Three flag into a Python flag, and raises customer warnings
    in the process, if needed.
    """
    if not python:
        if three is False:
            return "2"

        elif three is True:
            return "3"

    else:
        return python


def do_create_virtualenv(project, python=None, site_packages=None, pypi_mirror=None):
    """Creates a virtualenv."""

    click.echo(
        crayons.normal(fix_utf8("Creating a virtualenv for this project..."), bold=True),
        err=True,
    )
    click.echo(
        f"Pipfile: {crayons.yellow(project.pipfile_location, bold=True)}",
        err=True,
    )

    # Default to using sys.executable, if Python wasn't provided.
    using_string = "Using"
    if not python:
        python = sys.executable
        using_string = "Using default python from"
    click.echo(
        "{0} {1} {3} {2}".format(
            crayons.normal(using_string, bold=True),
            crayons.yellow(python, bold=True),
            crayons.normal(fix_utf8("to create virtualenv..."), bold=True),
            crayons.green(f"({python_version(python)})"),
        ),
        err=True,
    )

    cmd = [
        Path(sys.executable).absolute().as_posix(),
        "-m",
        "virtualenv",
        f"--prompt={project.name}",
        f"--python={python}",
        project.get_location_for_virtualenv(),
    ]

    # Pass site-packages flag to virtualenv, if desired...
    if site_packages:
        click.echo(
            crayons.normal(fix_utf8("Making site-packages available..."), bold=True),
            err=True,
        )
        cmd.append("--system-site-packages")

    if pypi_mirror:
        pip_config = {"PIP_INDEX_URL": pypi_mirror}
    else:
        pip_config = {}

    # Actually create the virtualenv.
    error = None
    with create_spinner("Creating virtual environment...", project.s) as sp:
        c = subprocess_run(cmd, env=pip_config)
        click.echo(crayons.cyan(f"{c.stdout}"), err=True)
        if c.returncode != 0:
            error = (
                c.stderr if project.s.is_verbose() else exceptions.prettify_exc(c.stderr)
            )
            sp.fail(
                environments.PIPENV_SPINNER_FAIL_TEXT.format(
                    "Failed creating virtual environment"
                )
            )
        else:
            sp.green.ok(
                environments.PIPENV_SPINNER_OK_TEXT.format(
                    "Successfully created virtual environment!"
                )
            )
    if error is not None:
        raise exceptions.VirtualenvCreationException(extra=crayons.red(f"{error}"))

    # Associate project directory with the environment.
    # This mimics Pew's "setproject".
    project_file_name = os.path.join(project.virtualenv_location, ".project")
    with open(project_file_name, "w") as f:
        f.write(project.project_directory)
    from .environment import Environment

    sources = project.pipfile_sources
    # project.get_location_for_virtualenv is only for if we are creating a new virtualenv
    # whereas virtualenv_location is for the current path to the runtime
    project._environment = Environment(
        prefix=project.virtualenv_location,
        is_venv=True,
        sources=sources,
        pipfile=project.parsed_pipfile,
        project=project,
    )
    project._environment.add_dist("pipenv")
    # Say where the virtualenv is.
    do_where(project, virtualenv=True, bare=False)


def parse_download_fname(fname, name):
    fname, fextension = os.path.splitext(fname)
    if fextension == ".whl":
        fname = "-".join(fname.split("-")[:-3])
    if fname.endswith(".tar"):
        fname, _ = os.path.splitext(fname)
    # Substring out package name (plus dash) from file name to get version.
    version = fname[len(name) + 1 :]
    # Ignore implicit post releases in version number.
    if "-" in version and version.split("-")[1].isdigit():
        version = version.split("-")[0]
    return version


def get_downloads_info(project, names_map, section):
    from .vendor.requirementslib.models.requirements import Requirement

    info = []
    p = project.parsed_pipfile
    for fname in os.listdir(project.download_location):
        # Get name from filename mapping.
        name = Requirement.from_line(names_map[fname]).name
        # Get the version info from the filenames.
        version = parse_download_fname(fname, name)
        # Get the hash of each file.
        cmd = [
            which_pip(project),
            "hash",
            os.sep.join([project.download_location, fname]),
        ]
        c = subprocess_run(cmd)
        hash = c.stdout.split("--hash=")[1].strip()
        # Verify we're adding the correct version from Pipfile
        # and not one from a dependency.
        specified_version = p[section].get(name, "")
        if is_required_version(version, specified_version):
            info.append(dict(name=name, version=version, hash=hash))
    return info


def overwrite_dev(prod, dev):
    dev_keys = set(list(dev.keys()))
    prod_keys = set(list(prod.keys()))
    for pkg in dev_keys & prod_keys:
        dev[pkg] = prod[pkg]
    return dev


def do_lock(
    project,
    ctx=None,
    system=False,
    clear=False,
    pre=False,
    keep_outdated=False,
    write=True,
    pypi_mirror=None,
):
    """Executes the freeze functionality."""

    cached_lockfile = {}
    if not pre:
        pre = project.settings.get("allow_prereleases")
    if keep_outdated:
        if not project.lockfile_exists:
            raise exceptions.PipenvOptionsError(
                "--keep-outdated",
                ctx=ctx,
                message="Pipfile.lock must exist to use --keep-outdated!",
            )
        cached_lockfile = project.lockfile_content
    # Create the lockfile.
    lockfile = project._lockfile
    # Cleanup lockfile.
    for section in ("default", "develop"):
        for k, v in lockfile[section].copy().items():
            if not hasattr(v, "keys"):
                del lockfile[section][k]
    # Resolve dev-package dependencies followed by packages dependencies.
    for is_dev in [True, False]:
        pipfile_section = "dev-packages" if is_dev else "packages"
        if project.pipfile_exists:
            packages = project.parsed_pipfile.get(pipfile_section, {})
        else:
            packages = getattr(project, pipfile_section.replace("-", "_"))

        if write:
            # Alert the user of progress.
            click.echo(
                "{} {} {}".format(
                    crayons.normal("Locking"),
                    crayons.yellow("[{}]".format(pipfile_section.replace("_", "-"))),
                    crayons.normal(fix_utf8("dependencies...")),
                ),
                err=True,
            )

        # Mutates the lockfile
        venv_resolve_deps(
            packages,
            which=project._which,
            project=project,
            dev=is_dev,
            clear=clear,
            pre=pre,
            allow_global=system,
            pypi_mirror=pypi_mirror,
            pipfile=packages,
            lockfile=lockfile,
            keep_outdated=keep_outdated,
        )

    # Support for --keep-outdated...
    if keep_outdated:
        from pipenv.vendor.packaging.utils import canonicalize_name

        for section_name, section in (
            ("default", project.packages),
            ("develop", project.dev_packages),
        ):
            for package_specified in section.keys():
                if not is_pinned(section[package_specified]):
                    canonical_name = canonicalize_name(package_specified)
                    if canonical_name in cached_lockfile[section_name]:
                        lockfile[section_name][canonical_name] = cached_lockfile[
                            section_name
                        ][canonical_name].copy()
            for key in ["default", "develop"]:
                packages = set(cached_lockfile[key].keys())
                new_lockfile = set(lockfile[key].keys())
                missing = packages - new_lockfile
                for missing_pkg in missing:
                    lockfile[key][missing_pkg] = cached_lockfile[key][missing_pkg].copy()
    # Overwrite any develop packages with default packages.
    lockfile["develop"].update(
        overwrite_dev(lockfile.get("default", {}), lockfile["develop"])
    )
    if write:
        project.write_lockfile(lockfile)
        click.echo(
            "{}".format(
                crayons.normal(
                    "Updated Pipfile.lock ({})!".format(
                        lockfile["_meta"].get("hash", {}).get("sha256")[-6:]
                    ),
                    bold=True,
                )
            ),
            err=True,
        )
    else:
        return lockfile


def do_purge(project, bare=False, downloads=False, allow_global=False):
    """Executes the purge functionality."""

    if downloads:
        if not bare:
            click.echo(
                crayons.normal(fix_utf8("Clearing out downloads directory..."), bold=True)
            )
        shutil.rmtree(project.download_location)
        return

    # Remove comments from the output, if any.
    installed = {
        pep423_name(pkg.project_name)
        for pkg in project.environment.get_installed_packages()
    }
    bad_pkgs = {pep423_name(pkg) for pkg in BAD_PACKAGES}
    # Remove setuptools, pip, etc from targets for removal
    to_remove = installed - bad_pkgs

    # Skip purging if there is no packages which needs to be removed
    if not to_remove:
        if not bare:
            click.echo("Found 0 installed package, skip purging.")
            click.echo(crayons.green("Environment now purged and fresh!"))
        return installed

    if not bare:
        click.echo(fix_utf8(f"Found {len(to_remove)} installed package(s), purging..."))

    command = [
        which_pip(project, allow_global=allow_global),
        "uninstall",
        "-y",
    ] + list(to_remove)
    if project.s.is_verbose():
        click.echo(f"$ {cmd_list_to_shell(command)}")
    c = subprocess_run(command)
    if c.returncode != 0:
        raise exceptions.UninstallError(
            installed, cmd_list_to_shell(command), c.stdout + c.stderr, c.returncode
        )
    if not bare:
        click.echo(crayons.cyan(c.stdout))
        click.echo(crayons.green("Environment now purged and fresh!"))
    return installed


def do_init(
    project,
    dev=False,
    dev_only=False,
    emit_requirements=False,
    allow_global=False,
    ignore_pipfile=False,
    skip_lock=False,
    system=False,
    concurrent=True,
    deploy=False,
    pre=False,
    keep_outdated=False,
    requirements_dir=None,
    pypi_mirror=None,
):
    """Executes the init functionality."""

    python = None
    if project.s.PIPENV_PYTHON is not None:
        python = project.s.PIPENV_PYTHON
    elif project.s.PIPENV_DEFAULT_PYTHON_VERSION is not None:
        python = project.s.PIPENV_DEFAULT_PYTHON_VERSION

    if not system and not project.s.PIPENV_USE_SYSTEM:
        if not project.virtualenv_exists:
            try:
                do_create_virtualenv(
                    project, python=python, three=None, pypi_mirror=pypi_mirror
                )
            except KeyboardInterrupt:
                cleanup_virtualenv(project, bare=False)
                sys.exit(1)
    # Ensure the Pipfile exists.
    if not deploy:
        ensure_pipfile(project, system=system)
    if not requirements_dir:
        requirements_dir = vistir.path.create_tracked_tempdir(
            suffix="-requirements", prefix="pipenv-"
        )
    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if (project.lockfile_exists and not ignore_pipfile) and not skip_lock:
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            if deploy:
                click.echo(
                    crayons.red(
                        "Your Pipfile.lock ({}) is out of date. Expected: ({}).".format(
                            old_hash[-6:], new_hash[-6:]
                        )
                    )
                )
                raise exceptions.DeployException
            elif (system or allow_global) and not (project.s.PIPENV_VIRTUALENV):
                click.echo(
                    crayons.yellow(
                        fix_utf8(
                            "Pipfile.lock ({}) out of date, but installation "
                            "uses {} re-building lockfile must happen in "
                            "isolation. Please rebuild lockfile in a virtualenv. "
                            "Continuing anyway...".format(old_hash[-6:], "--system")
                        )
                    ),
                    err=True,
                )
            else:
                if old_hash:
                    msg = fix_utf8("Pipfile.lock ({0}) out of date, updating to ({1})...")
                else:
                    msg = fix_utf8("Pipfile.lock is corrupted, replaced with ({1})...")
                click.echo(
                    crayons.yellow(msg.format(old_hash[-6:], new_hash[-6:]), bold=True),
                    err=True,
                )
                do_lock(
                    project,
                    system=system,
                    pre=pre,
                    keep_outdated=keep_outdated,
                    write=True,
                    pypi_mirror=pypi_mirror,
                )
    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists and not skip_lock:
        # Unless we're in a virtualenv not managed by pipenv, abort if we're
        # using the system's python.
        if (system or allow_global) and not (project.s.PIPENV_VIRTUALENV):
            raise exceptions.PipenvOptionsError(
                "--system",
                "--system is intended to be used for Pipfile installation, "
                "not installation of specific packages. Aborting.\n"
                "See also: --deploy flag.",
            )
        else:
            click.echo(
                crayons.normal(
                    fix_utf8("Pipfile.lock not found, creating..."), bold=True
                ),
                err=True,
            )
            do_lock(
                project,
                system=system,
                pre=pre,
                keep_outdated=keep_outdated,
                write=True,
                pypi_mirror=pypi_mirror,
            )
    do_install_dependencies(
        project,
        dev=dev,
        dev_only=dev_only,
        emit_requirements=emit_requirements,
        allow_global=allow_global,
        skip_lock=skip_lock,
        concurrent=concurrent,
        requirements_dir=requirements_dir,
        pypi_mirror=pypi_mirror,
    )

    # Hint the user what to do to activate the virtualenv.
    if not allow_global and not deploy and "PIPENV_ACTIVE" not in os.environ:
        click.echo(
            "To activate this project's virtualenv, run {}.\n"
            "Alternatively, run a command "
            "inside the virtualenv with {}.".format(
                crayons.yellow("pipenv shell"), crayons.yellow("pipenv run")
            )
        )


def get_pip_args(
    project,
    pre=False,  # type: bool
    verbose=False,  # type: bool
    upgrade=False,  # type: bool
    require_hashes=False,  # type: bool
    no_build_isolation=False,  # type: bool
    no_use_pep517=False,  # type: bool
    no_deps=False,  # type: bool
    selective_upgrade=False,  # type: bool
    src_dir=None,  # type: Optional[str]
):
    # type: (...) -> List[str]
    from .vendor.packaging.version import parse as parse_version

    arg_map = {
        "pre": ["--pre"],
        "verbose": ["--verbose"],
        "upgrade": ["--upgrade"],
        "require_hashes": ["--require-hashes"],
        "no_build_isolation": ["--no-build-isolation"],
        "no_use_pep517": [],
        "no_deps": ["--no-deps"],
        "selective_upgrade": [
            "--upgrade-strategy=only-if-needed",
            "--exists-action={}".format(project.s.PIP_EXISTS_ACTION or "i"),
        ],
        "src_dir": src_dir,
    }
    if project.environment.pip_version >= parse_version("19.0"):
        arg_map["no_use_pep517"].append("--no-use-pep517")
    if project.environment.pip_version < parse_version("19.1"):
        arg_map["no_use_pep517"].append("--no-build-isolation")
    arg_set = []
    for key in arg_map.keys():
        if key in locals() and locals().get(key):
            arg_set.extend(arg_map.get(key))
        elif key == "selective_upgrade" and not locals().get(key):
            arg_set.append("--exists-action=i")
    return list(dict.fromkeys(arg_set))


def get_requirement_line(
    requirement,  # type: Requirement
    src_dir=None,  # type: Optional[str]
    include_hashes=True,  # type: bool
    format_for_file=False,  # type: bool
):
    # type: (...) -> Union[List[str], str]
    line = None
    if requirement.vcs or requirement.is_file_or_url:
        if src_dir and requirement.line_instance.wheel_kwargs:
            requirement.line_instance._wheel_kwargs.update({"src_dir": src_dir})
        requirement.line_instance.vcsrepo
        line = requirement.line_instance.line
        if requirement.line_instance.markers:
            line = f"{line}; {requirement.line_instance.markers}"
            if not format_for_file:
                line = f'"{line}"'
        if requirement.editable:
            if not format_for_file:
                return ["-e", line]
            return f"-e {line}"
        if not format_for_file:
            return [line]
        return line
    return requirement.as_line(include_hashes=include_hashes, as_list=not format_for_file)


def write_requirement_to_file(
    project,  # type: Project
    requirement,  # type: Requirement
    requirements_dir=None,  # type: Optional[str]
    src_dir=None,  # type: Optional[str]
    include_hashes=True,  # type: bool
):
    # type: (...) -> str
    if not requirements_dir:
        requirements_dir = vistir.path.create_tracked_tempdir(
            prefix="pipenv", suffix="requirements"
        )
    line = requirement.line_instance.get_line(
        with_prefix=True, with_hashes=include_hashes, with_markers=True, as_list=False
    )

    f = tempfile.NamedTemporaryFile(
        prefix="pipenv-", suffix="-requirement.txt", dir=requirements_dir, delete=False
    )
    if project.s.is_verbose():
        click.echo(
            f"Writing supplied requirement line to temporary file: {line!r}", err=True
        )
    f.write(vistir.misc.to_bytes(line))
    r = f.name
    f.close()
    return r


def pip_install(
    project,
    requirement=None,
    r=None,
    allow_global=False,
    ignore_hashes=False,
    no_deps=None,
    block=True,
    index=None,
    pre=False,
    selective_upgrade=False,
    requirements_dir=None,
    extra_indexes=None,
    pypi_mirror=None,
    trusted_hosts=None,
    use_pep517=True,
):
    piplogger = logging.getLogger("pipenv.patched.notpip._internal.commands.install")
    if not trusted_hosts:
        trusted_hosts = []
    trusted_hosts.extend(os.environ.get("PIP_TRUSTED_HOSTS", []))
    if not allow_global:
        src_dir = os.getenv(
            "PIP_SRC", os.getenv("PIP_SRC_DIR", project.virtualenv_src_location)
        )
    else:
        src_dir = os.getenv("PIP_SRC", os.getenv("PIP_SRC_DIR"))
    if requirement:
        if requirement.editable or not requirement.hashes:
            ignore_hashes = True
        elif not (requirement.is_vcs or requirement.editable or requirement.vcs):
            ignore_hashes = False
    line = None
    # Try installing for each source in project.sources.
    search_all_sources = project.settings.get("install_search_all_sources", False)
    if not index and requirement.index:
        index = requirement.index
    if index and not extra_indexes:
        if search_all_sources:
            extra_indexes = list(project.sources)
        else:  # Default: index restrictions apply during installation
            extra_indexes = []
            if requirement.index:
                extra_indexes = list(
                    filter(lambda d: d.get("name") == requirement.index, project.sources)
                )
            if not extra_indexes:
                extra_indexes = list(project.sources)
    if requirement and requirement.vcs or requirement.editable:
        requirement.index = None
        # Install dependencies when a package is a non-editable VCS dependency.
        # Don't specify a source directory when using --system.
        if not requirement.editable and no_deps is not True:
            # Leave this off because old Pipfile.lock don't have all deps included
            # TODO: When can it be turned back on?
            no_deps = False
        elif requirement.editable and no_deps is None:
            no_deps = True

    r = write_requirement_to_file(
        project,
        requirement,
        requirements_dir=requirements_dir,
        src_dir=src_dir,
        include_hashes=not ignore_hashes,
    )
    sources = get_source_list(
        project,
        index,
        extra_indexes=extra_indexes,
        trusted_hosts=trusted_hosts,
        pypi_mirror=pypi_mirror,
    )
    if not search_all_sources and requirement.index in sources:
        sources = list(filter(lambda d: d.get("name") == requirement.index, sources))
    if r:
        with open(r, "r") as fh:
            if "--hash" not in fh.read():
                ignore_hashes = True
    if project.s.is_verbose():
        piplogger.setLevel(logging.WARN)
        if requirement:
            click.echo(
                crayons.normal(f"Installing {requirement.name!r}", bold=True),
                err=True,
            )

    pip_command = [
        project._which("python", allow_global=allow_global),
        "-m",
        "pip",
        "install",
    ]
    pip_args = get_pip_args(
        project,
        pre=pre,
        verbose=project.s.is_verbose(),
        upgrade=True,
        selective_upgrade=selective_upgrade,
        no_use_pep517=not use_pep517,
        no_deps=no_deps,
        require_hashes=not ignore_hashes,
    )
    pip_command.extend(pip_args)
    if r:
        pip_command.extend(["-r", vistir.path.normalize_path(r)])
    elif line:
        pip_command.extend(line)
    pip_command.extend(prepare_pip_source_args(sources))
    if project.s.is_verbose():
        click.echo(f"$ {cmd_list_to_shell(pip_command)}", err=True)
    cache_dir = Path(project.s.PIPENV_CACHE_DIR)
    default_exists_action = "w"
    if selective_upgrade:
        default_exists_action = "i"
    exists_action = project.s.PIP_EXISTS_ACTION or default_exists_action
    pip_config = {
        "PIP_CACHE_DIR": cache_dir.as_posix(),
        "PIP_WHEEL_DIR": cache_dir.joinpath("wheels").as_posix(),
        "PIP_DESTINATION_DIR": cache_dir.joinpath("pkgs").as_posix(),
        "PIP_EXISTS_ACTION": exists_action,
        "PATH": os.environ.get("PATH"),
    }
    if src_dir:
        if project.s.is_verbose():
            click.echo(f"Using source directory: {src_dir!r}", err=True)
        pip_config.update({"PIP_SRC": src_dir})
    c = subprocess_run(pip_command, block=block, env=pip_config)
    c.env = pip_config
    return c


def pip_download(project, package_name):
    cache_dir = Path(project.s.PIPENV_CACHE_DIR)
    pip_config = {
        "PIP_CACHE_DIR": cache_dir.as_posix(),
        "PIP_WHEEL_DIR": cache_dir.joinpath("wheels").as_posix(),
        "PIP_DESTINATION_DIR": cache_dir.joinpath("pkgs").as_posix(),
    }
    for source in project.sources:
        cmd = [
            which_pip(project),
            "download",
            package_name,
            "-i",
            source["url"],
            "-d",
            project.download_location,
        ]
        c = subprocess_run(cmd, env=pip_config)
        if c.returncode == 0:
            break

    return c


def fallback_which(command, location=None, allow_global=False, system=False):
    """
    A fallback implementation of the `which` utility command that relies exclusively on
    searching the path for commands.

    :param str command: The command to search for, optional
    :param str location: The search location to prioritize (prepend to path), defaults to None
    :param bool allow_global: Whether to search the global path, defaults to False
    :param bool system: Whether to use the system python instead of pipenv's python, defaults to False
    :raises ValueError: Raised if no command is provided
    :raises TypeError: Raised if the command provided is not a string
    :return: A path to the discovered command location
    :rtype: str
    """

    from .vendor.pythonfinder import Finder

    if not command:
        raise ValueError("fallback_which: Must provide a command to search for...")
    if not isinstance(command, str):
        raise TypeError(f"Provided command must be a string, received {command!r}")
    global_search = system or allow_global
    if location is None:
        global_search = True
    finder = Finder(system=False, global_search=global_search, path=location)
    if is_python_command(command):
        result = find_python(finder, command)
        if result:
            return result
    result = finder.which(command)
    if result:
        return result.path.as_posix()
    return ""


def which_pip(project, allow_global=False):
    """Returns the location of virtualenv-installed pip."""

    location = None
    if "VIRTUAL_ENV" in os.environ:
        location = os.environ["VIRTUAL_ENV"]
    if allow_global:
        if location:
            pip = project._which("pip", location=location)
            if pip:
                return pip

        for p in ("pip", "pip3", "pip2"):
            where = system_which(p)
            if where:
                return where

    pip = project._which("pip")
    if not pip:
        pip = fallback_which("pip", allow_global=allow_global, location=location)
    return pip


def system_which(command, path=None):
    """Emulates the system's which. Returns None if not found."""
    import shutil

    result = shutil.which(command, path=path)
    if result is None:
        _which = "where" if os.name == "nt" else "which -a"
        env = {"PATH": path} if path else None
        c = subprocess_run(f"{_which} {command}", shell=True, env=env)
        if c.returncode == 127:
            click.echo(
                "{}: the {} system utility is required for Pipenv to find Python installations properly."
                "\n  Please install it.".format(
                    crayons.red("Warning", bold=True), crayons.yellow(_which)
                ),
                err=True,
            )
        if c.returncode == 0:
            result = next(iter(c.stdout.splitlines()), None)
    return result


def format_help(help):
    """Formats the help string."""
    help = help.replace("Options:", str(crayons.normal("Options:", bold=True)))
    help = help.replace(
        "Usage: pipenv", str("Usage: {}".format(crayons.normal("pipenv", bold=True)))
    )
    help = help.replace("  check", str(crayons.red("  check", bold=True)))
    help = help.replace("  clean", str(crayons.red("  clean", bold=True)))
    help = help.replace("  graph", str(crayons.red("  graph", bold=True)))
    help = help.replace("  install", str(crayons.magenta("  install", bold=True)))
    help = help.replace("  lock", str(crayons.green("  lock", bold=True)))
    help = help.replace("  open", str(crayons.red("  open", bold=True)))
    help = help.replace("  run", str(crayons.yellow("  run", bold=True)))
    help = help.replace("  shell", str(crayons.yellow("  shell", bold=True)))
    help = help.replace("  scripts", str(crayons.yellow("  scripts", bold=True)))
    help = help.replace("  sync", str(crayons.green("  sync", bold=True)))
    help = help.replace("  uninstall", str(crayons.magenta("  uninstall", bold=True)))
    help = help.replace("  update", str(crayons.green("  update", bold=True)))
    additional_help = """
Usage Examples:
   Create a new project using Python 3.7, specifically:
   $ {}

   Remove project virtualenv (inferred from current directory):
   $ {}

   Install all dependencies for a project (including dev):
   $ {}

   Create a lockfile containing pre-releases:
   $ {}

   Show a graph of your installed dependencies:
   $ {}

   Check your installed dependencies for security vulnerabilities:
   $ {}

   Install a local setup.py into your virtual environment/Pipfile:
   $ {}

   Use a lower-level pip command:
   $ {}

Commands:""".format(
        crayons.yellow("pipenv --python 3.7"),
        crayons.yellow("pipenv --rm"),
        crayons.yellow("pipenv install --dev"),
        crayons.yellow("pipenv lock --pre"),
        crayons.yellow("pipenv graph"),
        crayons.yellow("pipenv check"),
        crayons.yellow("pipenv install -e ."),
        crayons.yellow("pipenv run pip freeze"),
    )
    help = help.replace("Commands:", additional_help)
    return help


def format_pip_error(error):
    error = error.replace("Expected", str(crayons.green("Expected", bold=True)))
    error = error.replace("Got", str(crayons.red("Got", bold=True)))
    error = error.replace(
        "THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE",
        str(
            crayons.red(
                "THESE PACKAGES DO NOT MATCH THE HASHES FROM Pipfile.lock!", bold=True
            )
        ),
    )
    error = error.replace(
        "someone may have tampered with them",
        str(crayons.red("someone may have tampered with them")),
    )
    error = error.replace("option to pip install", "option to 'pipenv install'")
    return error


def format_pip_output(out, r=None):
    def gen(out):
        for line in out.split("\n"):
            # Remove requirements file information from pip9 output.
            if "(from -r" in line:
                yield line[: line.index("(from -r")]

            else:
                yield line

    out = "\n".join([line for line in gen(out)])
    return out


def warn_in_virtualenv(project):
    # Only warn if pipenv isn't already active.
    if environments.is_in_virtualenv() and not project.s.is_quiet():
        click.echo(
            "{}: Pipenv found itself running within a virtual environment, "
            "so it will automatically use that environment, instead of "
            "creating its own for any project. You can set "
            "{} to force pipenv to ignore that environment and create "
            "its own instead. You can set {} to suppress this "
            "warning.".format(
                crayons.green("Courtesy Notice"),
                crayons.normal("PIPENV_IGNORE_VIRTUALENVS=1", bold=True),
                crayons.normal("PIPENV_VERBOSITY=-1", bold=True),
            ),
            err=True,
        )


def ensure_lockfile(project, keep_outdated=False, pypi_mirror=None):
    """Ensures that the lockfile is up-to-date."""
    if not keep_outdated:
        keep_outdated = project.settings.get("keep_outdated")
    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if project.lockfile_exists:
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            click.echo(
                crayons.yellow(
                    fix_utf8(
                        "Pipfile.lock ({}) out of date, updating to ({})...".format(
                            old_hash[-6:], new_hash[-6:]
                        )
                    ),
                    bold=True,
                ),
                err=True,
            )
            do_lock(project, keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)
    else:
        do_lock(project, keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)


def do_py(project, ctx=None, system=False):
    if not project.virtualenv_exists:
        click.echo(
            "{}({}){}".format(
                crayons.red("No virtualenv has been created for this project "),
                crayons.yellow(project.project_directory, bold=True),
                crayons.red(" yet!"),
            ),
            err=True,
        )
        ctx.abort()

    try:
        click.echo(project._which("python", allow_global=system))
    except AttributeError:
        click.echo(crayons.red("No project found!"))


def do_outdated(project, pypi_mirror=None, pre=False, clear=False):
    # TODO: Allow --skip-lock here?
    from collections import namedtuple
    from collections.abc import Mapping

    from .vendor.packaging.utils import canonicalize_name
    from .vendor.requirementslib.models.requirements import Requirement
    from .vendor.requirementslib.models.utils import get_version

    packages = {}
    package_info = namedtuple("PackageInfo", ["name", "installed", "available"])

    installed_packages = project.environment.get_installed_packages()
    outdated_packages = {
        canonicalize_name(pkg.project_name): package_info(
            pkg.project_name, pkg.parsed_version, pkg.latest_version
        )
        for pkg in project.environment.get_outdated_packages()
    }
    reverse_deps = {
        canonicalize_name(name): deps
        for name, deps in project.environment.reverse_dependencies().items()
    }
    for result in installed_packages:
        dep = Requirement.from_line(str(result.as_requirement()))
        packages.update(dep.as_pipfile())
    updated_packages = {}
    lockfile = do_lock(
        project, clear=clear, pre=pre, write=False, pypi_mirror=pypi_mirror
    )
    for section in ("develop", "default"):
        for package in lockfile[section]:
            try:
                updated_packages[package] = lockfile[section][package]["version"]
            except KeyError:
                pass
    outdated = []
    skipped = []
    for package in packages:
        norm_name = pep423_name(package)
        if norm_name in updated_packages:
            if updated_packages[norm_name] != packages[package]:
                outdated.append(
                    package_info(package, updated_packages[norm_name], packages[package])
                )
            elif canonicalize_name(package) in outdated_packages:
                skipped.append(outdated_packages[canonicalize_name(package)])
    for package, old_version, new_version in skipped:
        name_in_pipfile = project.get_package_name_in_pipfile(package)
        pipfile_version_text = ""
        required = ""
        version = None
        if name_in_pipfile:
            version = get_version(project.packages[name_in_pipfile])
            rdeps = reverse_deps.get(canonicalize_name(package))
            if isinstance(rdeps, Mapping) and "required" in rdeps:
                required = " {} required".format(rdeps["required"])
            if version:
                pipfile_version_text = f" ({version} set in Pipfile)"
            else:
                pipfile_version_text = " (Unpinned in Pipfile)"
        click.echo(
            crayons.yellow(
                "Skipped Update of Package {!s}: {!s} installed,{!s}{!s}, "
                "{!s} available.".format(
                    package, old_version, required, pipfile_version_text, new_version
                )
            ),
            err=True,
        )
    if not outdated:
        click.echo(crayons.green("All packages are up to date!", bold=True))
        sys.exit(0)
    for package, new_version, old_version in outdated:
        click.echo(
            "Package {!r} out-of-date: {!r} installed, {!r} available.".format(
                package, old_version, new_version
            )
        )
    sys.exit(bool(outdated))


def do_install(
    project,
    packages=False,
    editable_packages=False,
    index_url=False,
    dev=False,
    three=False,
    python=False,
    pypi_mirror=None,
    system=False,
    lock=True,
    ignore_pipfile=False,
    skip_lock=False,
    requirementstxt=False,
    sequential=False,
    pre=False,
    deploy=False,
    keep_outdated=False,
    selective_upgrade=False,
    site_packages=None,
):
    from .vendor.pip_shims.shims import PipError

    requirements_directory = vistir.path.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    warnings.filterwarnings("default", category=ResourceWarning)
    if selective_upgrade:
        keep_outdated = True
    packages = packages if packages else []
    editable_packages = editable_packages if editable_packages else []
    package_args = [p for p in packages if p] + [p for p in editable_packages if p]
    skip_requirements = False
    # Don't search for requirements.txt files if the user provides one
    if requirementstxt or package_args or project.pipfile_exists:
        skip_requirements = True
    concurrent = not sequential
    # Ensure that virtualenv is available and pipfile are available
    ensure_project(
        project,
        three=three,
        python=python,
        system=system,
        warn=True,
        deploy=deploy,
        skip_requirements=skip_requirements,
        pypi_mirror=pypi_mirror,
        site_packages=site_packages,
    )
    # Don't attempt to install develop and default packages if Pipfile is missing
    if not project.pipfile_exists and not (package_args or dev):
        if not (ignore_pipfile or deploy):
            raise exceptions.PipfileNotFound(project.path_to("Pipfile"))
        elif ((skip_lock and deploy) or ignore_pipfile) and not project.lockfile_exists:
            raise exceptions.LockfileNotFound(project.path_to("Pipfile.lock"))
    # Load the --pre settings from the Pipfile.
    if not pre:
        pre = project.settings.get("allow_prereleases")
    if not keep_outdated:
        keep_outdated = project.settings.get("keep_outdated")
    remote = requirementstxt and is_valid_url(requirementstxt)
    # Warn and exit if --system is used without a pipfile.
    if (system and package_args) and not project.s.PIPENV_VIRTUALENV:
        raise exceptions.SystemUsageError
    # Automatically use an activated virtualenv.
    if project.s.PIPENV_USE_SYSTEM:
        system = True
    if system:
        project.s.PIPENV_USE_SYSTEM = True
        os.environ["PIPENV_USE_SYSTEM"] = "1"
    # Check if the file is remote or not
    if remote:
        click.echo(
            crayons.normal(
                fix_utf8("Remote requirements file provided! Downloading..."), bold=True
            ),
            err=True,
        )
        fd = vistir.path.create_tracked_tempfile(
            prefix="pipenv-", suffix="-requirement.txt", dir=requirements_directory
        )
        temp_reqs = fd.name
        requirements_url = requirementstxt
        # Download requirements file
        try:
            download_file(requirements_url, temp_reqs, project.s.PIPENV_MAX_RETRIES)
        except OSError:
            fd.close()
            os.unlink(temp_reqs)
            click.echo(
                crayons.red(
                    "Unable to find requirements file at {}.".format(
                        crayons.normal(requirements_url)
                    )
                ),
                err=True,
            )
            sys.exit(1)
        finally:
            fd.close()
        # Replace the url with the temporary requirements file
        requirementstxt = temp_reqs
        remote = True
    if requirementstxt:
        error, traceback = None, None
        click.echo(
            crayons.normal(
                fix_utf8("Requirements file provided! Importing into Pipfile..."),
                bold=True,
            ),
            err=True,
        )
        try:
            import_requirements(project, r=project.path_to(requirementstxt), dev=dev)
        except (UnicodeDecodeError, PipError) as e:
            # Don't print the temp file path if remote since it will be deleted.
            req_path = requirements_url if remote else project.path_to(requirementstxt)
            error = (
                "Unexpected syntax in {}. Are you sure this is a "
                "requirements.txt style file?".format(req_path)
            )
            traceback = e
        except AssertionError as e:
            error = (
                "Requirements file doesn't appear to exist. Please ensure the file exists in your "
                "project directory or you provided the correct path."
            )
            traceback = e
        finally:
            # If requirements file was provided by remote url delete the temporary file
            if remote:
                fd.close()  # Close for windows to allow file cleanup.
                os.remove(temp_reqs)
            if error and traceback:
                click.echo(crayons.red(error))
                click.echo(crayons.yellow(str(traceback)), err=True)
                sys.exit(1)

    # Allow more than one package to be provided.
    package_args = [p for p in packages] + [f"-e {pkg}" for pkg in editable_packages]
    # Support for --selective-upgrade.
    # We should do this part first to make sure that we actually do selectively upgrade
    # the items specified
    if selective_upgrade:
        from .vendor.requirementslib.models.requirements import Requirement

        for i, package in enumerate(package_args[:]):
            section = project.packages if not dev else project.dev_packages
            package = Requirement.from_line(package)
            package__name, package__val = package.pipfile_entry
            try:
                if not is_star(section[package__name]) and is_star(package__val):
                    # Support for VCS dependencies.
                    package_args[i] = convert_deps_to_pip(
                        {package__name: section[package__name]}, project=project, r=False
                    )[0]
            except KeyError:
                pass
    # Install all dependencies, if none was provided.
    # This basically ensures that we have a pipfile and lockfile, then it locks and
    # installs from the lockfile
    if not packages and not editable_packages:
        # Update project settings with pre preference.
        if pre:
            project.update_settings({"allow_prereleases": pre})
        do_init(
            project,
            dev=dev,
            allow_global=system,
            ignore_pipfile=ignore_pipfile,
            system=system,
            skip_lock=skip_lock,
            concurrent=concurrent,
            deploy=deploy,
            pre=pre,
            requirements_dir=requirements_directory,
            pypi_mirror=pypi_mirror,
            keep_outdated=keep_outdated,
        )

    # This is for if the user passed in dependencies, then we want to make sure we
    else:
        from .vendor.requirementslib.models.requirements import Requirement

        # make a tuple of (display_name, entry)
        pkg_list = packages + [f"-e {pkg}" for pkg in editable_packages]
        if not system and not project.virtualenv_exists:
            do_init(
                project,
                dev=dev,
                system=system,
                allow_global=system,
                concurrent=concurrent,
                keep_outdated=keep_outdated,
                requirements_dir=requirements_directory,
                deploy=deploy,
                pypi_mirror=pypi_mirror,
                skip_lock=skip_lock,
            )
        pip_shims_module = os.environ.pop("PIP_SHIMS_BASE_MODULE", None)
        for pkg_line in pkg_list:
            click.echo(
                crayons.normal(
                    fix_utf8(f"Installing {crayons.green(pkg_line, bold=True)}..."),
                    bold=True,
                )
            )
            # pip install:
            with vistir.contextmanagers.temp_environ(), create_spinner(
                "Installing...", project.s
            ) as sp:
                if not system:
                    os.environ["PIP_USER"] = "0"
                    if "PYTHONHOME" in os.environ:
                        del os.environ["PYTHONHOME"]
                sp.text = f"Resolving {pkg_line}..."
                try:
                    pkg_requirement = Requirement.from_line(pkg_line)
                except ValueError as e:
                    sp.write_err("{}: {}".format(crayons.red("WARNING"), e))
                    sp.red.fail(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format(
                            "Installation Failed"
                        )
                    )
                    sys.exit(1)
                no_deps = False
                sp.text = "Installing..."
                try:
                    sp.text = f"Installing {pkg_requirement.name}..."
                    if project.s.is_verbose():
                        sp.hide_and_write(
                            f"Installing package: {pkg_requirement.as_line(include_hashes=False)}"
                        )
                    c = pip_install(
                        project,
                        pkg_requirement,
                        ignore_hashes=True,
                        allow_global=system,
                        selective_upgrade=selective_upgrade,
                        no_deps=no_deps,
                        pre=pre,
                        requirements_dir=requirements_directory,
                        index=index_url,
                        pypi_mirror=pypi_mirror,
                    )
                    if c.returncode:
                        sp.write_err(
                            "{} An error occurred while installing {}!".format(
                                crayons.red("Error: ", bold=True), crayons.green(pkg_line)
                            ),
                        )
                        sp.write_err(f"Error text: {c.stdout}")
                        sp.write_err(crayons.cyan(format_pip_error(c.stderr)))
                        if project.s.is_verbose():
                            sp.write_err(crayons.cyan(format_pip_output(c.stdout)))
                        if "setup.py egg_info" in c.stderr:
                            sp.write_err(
                                "This is likely caused by a bug in {}. "
                                "Report this to its maintainers.".format(
                                    crayons.green(pkg_requirement.name)
                                )
                            )
                        sp.red.fail(
                            environments.PIPENV_SPINNER_FAIL_TEXT.format(
                                "Installation Failed"
                            )
                        )
                        sys.exit(1)
                except (ValueError, RuntimeError) as e:
                    sp.write_err("{}: {}".format(crayons.red("WARNING"), e))
                    sp.red.fail(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format(
                            "Installation Failed",
                        )
                    )
                    sys.exit(1)
                # Warn if --editable wasn't passed.
                if (
                    pkg_requirement.is_vcs
                    and not pkg_requirement.editable
                    and not project.s.PIPENV_RESOLVE_VCS
                ):
                    sp.write_err(
                        "{}: You installed a VCS dependency in non-editable mode. "
                        "This will work fine, but sub-dependencies will not be resolved by {}."
                        "\n  To enable this sub-dependency functionality, specify that this dependency is editable."
                        "".format(
                            crayons.red("Warning", bold=True),
                            crayons.yellow("$ pipenv lock"),
                        )
                    )
                sp.write(
                    "{} {} {} {}{}".format(
                        crayons.normal("Adding", bold=True),
                        crayons.green(f"{pkg_requirement.name}", bold=True),
                        crayons.normal("to Pipfile's", bold=True),
                        crayons.yellow(
                            "[dev-packages]" if dev else "[packages]", bold=True
                        ),
                        crayons.normal(fix_utf8("..."), bold=True),
                    )
                )
                # Add the package to the Pipfile.
                if index_url:
                    index_name = project.add_index_to_pipfile(
                        index_url, verify_ssl=index_url.startswith("https:")
                    )
                    pkg_requirement.index = index_name
                try:
                    project.add_package_to_pipfile(pkg_requirement, dev)
                except ValueError:
                    import traceback

                    sp.write_err(
                        "{} {}".format(
                            crayons.red("Error:", bold=True), traceback.format_exc()
                        )
                    )
                    sp.fail(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format(
                            "Failed adding package to Pipfile"
                        )
                    )
                sp.ok(
                    environments.PIPENV_SPINNER_OK_TEXT.format("Installation Succeeded")
                )
            # Update project settings with pre preference.
            if pre:
                project.update_settings({"allow_prereleases": pre})
        if pip_shims_module:
            os.environ["PIP_SHIMS_BASE_MODULE"] = pip_shims_module
        do_init(
            project,
            dev=dev,
            system=system,
            allow_global=system,
            concurrent=concurrent,
            keep_outdated=keep_outdated,
            requirements_dir=requirements_directory,
            deploy=deploy,
            pypi_mirror=pypi_mirror,
            skip_lock=skip_lock,
        )
    sys.exit(0)


def do_uninstall(
    project,
    packages=False,
    editable_packages=False,
    three=None,
    python=False,
    system=False,
    lock=False,
    all_dev=False,
    all=False,
    keep_outdated=False,
    pypi_mirror=None,
    ctx=None,
):
    from .vendor.packaging.utils import canonicalize_name
    from .vendor.requirementslib.models.requirements import Requirement

    # Automatically use an activated virtualenv.
    if project.s.PIPENV_USE_SYSTEM:
        system = True
    # Ensure that virtualenv is available.
    # TODO: We probably shouldn't ensure a project exists if the outcome will be to just
    # install things in order to remove them... maybe tell the user to install first?
    ensure_project(project, three=three, python=python, pypi_mirror=pypi_mirror)
    # Un-install all dependencies, if --all was provided.
    if not any([packages, editable_packages, all_dev, all]):
        raise exceptions.PipenvUsageError("No package provided!", ctx=ctx)
    editable_pkgs = [
        Requirement.from_line(f"-e {p}").name for p in editable_packages if p
    ]
    packages += editable_pkgs
    package_names = {p for p in packages if p}
    package_map = {canonicalize_name(p): p for p in packages if p}
    installed_package_names = project.installed_package_names
    # Intelligently detect if --dev should be used or not.
    lockfile_packages = set()
    if project.lockfile_exists:
        project_pkg_names = project.lockfile_package_names
    else:
        project_pkg_names = project.pipfile_package_names
    pipfile_remove = True
    # Uninstall [dev-packages], if --dev was provided.
    if all_dev:
        if "dev-packages" not in project.parsed_pipfile and not project_pkg_names["dev"]:
            click.echo(
                crayons.normal(
                    "No {} to uninstall.".format(crayons.yellow("[dev-packages]")),
                    bold=True,
                )
            )
            return
        click.echo(
            crayons.normal(
                fix_utf8("Un-installing {}...".format(crayons.yellow("[dev-packages]"))),
                bold=True,
            )
        )
        package_names = set(project_pkg_names["dev"]) - set(project_pkg_names["default"])

    # Remove known "bad packages" from the list.
    bad_pkgs = get_canonical_names(BAD_PACKAGES)
    ignored_packages = bad_pkgs & set(list(package_map.keys()))
    for ignored_pkg in ignored_packages:
        if project.s.is_verbose():
            click.echo(f"Ignoring {ignored_pkg}.", err=True)
        package_names.discard(package_map[ignored_pkg])

    used_packages = project_pkg_names["combined"] & installed_package_names
    failure = False
    if all:
        click.echo(
            crayons.normal(
                fix_utf8(
                    "Un-installing all {} and {}...".format(
                        crayons.yellow("[dev-packages]"),
                        crayons.yellow("[packages]"),
                    )
                ),
                bold=True,
            )
        )
        do_purge(project, bare=False, allow_global=system)
        sys.exit(0)

    selected_pkg_map = {canonicalize_name(p): p for p in package_names}
    packages_to_remove = [
        p
        for normalized, p in selected_pkg_map.items()
        if normalized in (used_packages - bad_pkgs)
    ]
    pip_path = None
    for normalized, package_name in selected_pkg_map.items():
        click.echo(
            crayons.normal(
                fix_utf8(f"Uninstalling {crayons.green(package_name)}..."), bold=True
            )
        )
        # Uninstall the package.
        if package_name in packages_to_remove:
            with project.environment.activated():
                if pip_path is None:
                    pip_path = which_pip(project, allow_global=system)
                cmd = [pip_path, "uninstall", package_name, "-y"]
                c = run_command(cmd, is_verbose=project.s.is_verbose())
                click.echo(crayons.cyan(c.stdout))
                if c.returncode != 0:
                    failure = True
        if not failure and pipfile_remove:
            in_packages = project.get_package_name_in_pipfile(package_name, dev=False)
            in_dev_packages = project.get_package_name_in_pipfile(package_name, dev=True)
            if normalized in lockfile_packages:
                click.echo(
                    "{} {} {} {}".format(
                        crayons.cyan("Removing"),
                        crayons.green(package_name),
                        crayons.cyan("from"),
                        crayons.white(fix_utf8("Pipfile.lock...")),
                    )
                )
                lockfile = project.get_or_create_lockfile()
                if normalized in lockfile.default:
                    del lockfile.default[normalized]
                if normalized in lockfile.develop:
                    del lockfile.develop[normalized]
                lockfile.write()
            if not (in_dev_packages or in_packages):
                if normalized in lockfile_packages:
                    continue
                click.echo(
                    "No package {} to remove from Pipfile.".format(
                        crayons.green(package_name)
                    )
                )
                continue

            click.echo(
                fix_utf8(f"Removing {crayons.green(package_name)} from Pipfile...")
            )
            # Remove package from both packages and dev-packages.
            if in_dev_packages:
                project.remove_package_from_pipfile(package_name, dev=True)
            if in_packages:
                project.remove_package_from_pipfile(package_name, dev=False)
    if lock:
        do_lock(
            project, system=system, keep_outdated=keep_outdated, pypi_mirror=pypi_mirror
        )
    sys.exit(int(failure))


def do_shell(
    project, three=None, python=False, fancy=False, shell_args=None, pypi_mirror=None
):
    # Ensure that virtualenv is available.
    ensure_project(
        project,
        three=three,
        python=python,
        validate=False,
        pypi_mirror=pypi_mirror,
    )

    # Support shell compatibility mode.
    if project.s.PIPENV_SHELL_FANCY:
        fancy = True

    from .shells import choose_shell

    shell = choose_shell(project)
    click.echo(fix_utf8("Launching subshell in virtual environment..."), err=True)

    fork_args = (
        project.virtualenv_location,
        project.project_directory,
        shell_args,
    )

    # Set an environment variable, so we know we're in the environment.
    # Only set PIPENV_ACTIVE after finishing reading virtualenv_location
    # otherwise its value will be changed
    os.environ["PIPENV_ACTIVE"] = "1"

    os.environ.pop("PIP_SHIMS_BASE_MODULE", None)

    if fancy:
        shell.fork(*fork_args)
        return

    try:
        shell.fork_compat(*fork_args)
    except (AttributeError, ImportError):
        click.echo(
            fix_utf8(
                "Compatibility mode not supported. "
                "Trying to continue as well-configured shell..."
            ),
            err=True,
        )
        shell.fork(*fork_args)


def _inline_activate_virtualenv(project):
    try:
        activate_this = project._which("activate_this.py")
        if not activate_this or not os.path.exists(activate_this):
            raise exceptions.VirtualenvActivationException()
        with open(activate_this) as f:
            code = compile(f.read(), activate_this, "exec")
            exec(code, dict(__file__=activate_this))
    # Catch all errors, just in case.
    except Exception:
        click.echo(
            "{}: There was an unexpected error while activating your "
            "virtualenv. Continuing anyway...".format(crayons.red("Warning", bold=True)),
            err=True,
        )


def _inline_activate_venv(project):
    """Built-in venv doesn't have activate_this.py, but doesn't need it anyway.

    As long as we find the correct executable, built-in venv sets up the
    environment automatically.

    See: https://bugs.python.org/issue21496#msg218455
    """
    components = []
    for name in ("bin", "Scripts"):
        bindir = os.path.join(project.virtualenv_location, name)
        if os.path.exists(bindir):
            components.append(bindir)
    if "PATH" in os.environ:
        components.append(os.environ["PATH"])
    os.environ["PATH"] = os.pathsep.join(components)


def inline_activate_virtual_environment(project):
    root = project.virtualenv_location
    if os.path.exists(os.path.join(root, "pyvenv.cfg")):
        _inline_activate_venv(project)
    else:
        _inline_activate_virtualenv(project)
    if "VIRTUAL_ENV" not in os.environ:
        os.environ["VIRTUAL_ENV"] = root


def _launch_windows_subprocess(script, env):
    import subprocess

    path = env.get("PATH", "")
    command = system_which(script.command, path=path)

    options = {"universal_newlines": True, "env": env}
    script.cmd_args[1:] = [expandvars(arg) for arg in script.args]

    # Command not found, maybe this is a shell built-in?
    if not command:
        return subprocess.Popen(script.cmdify(), shell=True, **options)

    # Try to use CreateProcess directly if possible. Specifically catch
    # Windows error 193 "Command is not a valid Win32 application" to handle
    # a "command" that is non-executable. See pypa/pipenv#2727.
    try:
        return subprocess.Popen([command] + script.args, **options)
    except OSError as e:
        if e.winerror != 193:
            raise

    # Try shell mode to use Windows's file association for file launch.
    return subprocess.Popen(script.cmdify(), shell=True, **options)


def do_run_nt(project, script, env):
    p = _launch_windows_subprocess(script, env)
    p.communicate()
    sys.exit(p.returncode)


def do_run_posix(project, script, command, env):
    path = env.get("PATH")
    command_path = system_which(script.command, path=path)
    if not command_path:
        if project.has_script(command):
            click.echo(
                "{}: the command {} (from {}) could not be found within {}."
                "".format(
                    crayons.red("Error", bold=True),
                    crayons.yellow(script.command),
                    crayons.normal(command, bold=True),
                    crayons.normal("PATH", bold=True),
                ),
                err=True,
            )
        else:
            click.echo(
                "{}: the command {} could not be found within {} or Pipfile's {}."
                "".format(
                    crayons.red("Error", bold=True),
                    crayons.yellow(command),
                    crayons.normal("PATH", bold=True),
                    crayons.normal("[scripts]", bold=True),
                ),
                err=True,
            )
        sys.exit(1)
    os.execve(
        command_path,
        [command_path, *(os.path.expandvars(arg) for arg in script.args)],
        env,
    )


def do_run(
    project, command, args, three=None, python=False, pypi_mirror=None, quiet=False
):
    """Attempt to run command either pulling from project or interpreting as executable.

    Args are appended to the command in [scripts] section of project if found.
    """
    from .cmdparse import ScriptEmptyError

    # Ensure that virtualenv is available.
    ensure_project(
        project,
        three=three,
        python=python,
        validate=False,
        pypi_mirror=pypi_mirror,
    )

    load_dot_env(project, quiet=quiet)
    env = os.environ.copy()
    env.pop("PIP_SHIMS_BASE_MODULE", None)

    path = env.get("PATH", "")
    if project.virtualenv_location:
        new_path = os.path.join(
            project.virtualenv_location, "Scripts" if os.name == "nt" else "bin"
        )
        paths = path.split(os.pathsep)
        paths.insert(0, new_path)
        path = os.pathsep.join(paths)
        env["VIRTUAL_ENV"] = project.virtualenv_location
    env["PATH"] = path

    # Set an environment variable, so we know we're in the environment.
    # Only set PIPENV_ACTIVE after finishing reading virtualenv_location
    # such as in inline_activate_virtual_environment
    # otherwise its value will be changed
    env["PIPENV_ACTIVE"] = "1"
    env.pop("PIP_SHIMS_BASE_MODULE", None)

    try:
        script = project.build_script(command, args)
        cmd_string = cmd_list_to_shell([script.command] + script.args)
        if project.s.is_verbose():
            click.echo(crayons.normal(f"$ {cmd_string}"), err=True)
    except ScriptEmptyError:
        click.echo("Can't run script {0!r}-it's empty?", err=True)
    run_args = [project, script]
    run_kwargs = {"env": env}
    # We're using `do_run_nt` on CI (even if we're running on a non-nt machine)
    # as a workaround for https://github.com/pypa/pipenv/issues/4909.
    if os.name == "nt" or environments.PIPENV_IS_CI:
        run_fn = do_run_nt
    else:
        run_fn = do_run_posix
        run_kwargs.update({"command": command})
    run_fn(*run_args, **run_kwargs)


def do_check(
    project,
    three=None,
    python=False,
    system=False,
    db=None,
    ignore=None,
    output="default",
    key=None,
    quiet=False,
    pypi_mirror=None,
):
    import json

    if not system:
        # Ensure that virtualenv is available.
        ensure_project(
            project,
            three=three,
            python=python,
            validate=False,
            warn=False,
            pypi_mirror=pypi_mirror,
        )
    if not quiet and not project.s.is_quiet():
        click.echo(
            crayons.normal(
                decode_for_output("Checking PEP 508 requirements..."), bold=True
            )
        )
    pep508checker_path = pep508checker.__file__.rstrip("cdo")
    safety_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "patched", "safety"
    )
    if not system:
        python = project._which("python")
    else:
        interpreters = [system_which(p) for p in ("python", "python3", "python2")]
        python = interpreters[0] if interpreters else None
    if not python:
        click.echo(crayons.red("The Python interpreter can't be found."), err=True)
        sys.exit(1)
    _cmd = [Path(python).as_posix()]
    # Run the PEP 508 checker in the virtualenv.
    cmd = _cmd + [Path(pep508checker_path).as_posix()]
    c = run_command(cmd, is_verbose=project.s.is_verbose())
    if c.returncode is not None:
        try:
            results = simplejson.loads(c.stdout.strip())
        except json.JSONDecodeError:
            click.echo(
                "{}\n{}\n{}".format(
                    crayons.white(
                        decode_for_output("Failed parsing pep508 results: "), bold=True
                    ),
                    c.stdout.strip(),
                    c.stderr.strip(),
                )
            )
            sys.exit(1)
    # Load the pipfile.
    p = pipfile.Pipfile.load(project.pipfile_location)
    failed = False
    # Assert each specified requirement.
    for marker, specifier in p.data["_meta"]["requires"].items():
        if marker in results:
            try:
                assert results[marker] == specifier
            except AssertionError:
                failed = True
                click.echo(
                    "Specifier {} does not match {} ({})."
                    "".format(
                        crayons.green(marker),
                        crayons.cyan(specifier),
                        crayons.yellow(results[marker]),
                    ),
                    err=True,
                )
    if failed:
        click.echo(crayons.red("Failed!"), err=True)
        sys.exit(1)
    else:
        if not quiet and not project.s.is_quiet():
            click.echo(crayons.green("Passed!"))
    if not quiet and not project.s.is_quiet():
        click.echo(
            crayons.normal(
                decode_for_output("Checking installed package safety..."), bold=True
            )
        )
    if ignore:
        if not isinstance(ignore, (tuple, list)):
            ignore = [ignore]
        ignored = [["--ignore", cve] for cve in ignore]
        if not quiet and not project.s.is_quiet():
            click.echo(
                crayons.normal(
                    "Notice: Ignoring CVE(s) {}".format(crayons.yellow(", ".join(ignore)))
                ),
                err=True,
            )
    else:
        ignored = []

    switch = output
    if output == "default":
        switch = "json"

    cmd = _cmd + [safety_path, "check", f"--{switch}"]
    if db:
        if not quiet and not project.s.is_quiet():
            click.echo(crayons.normal(f"Using local database {db}"))
        cmd.append(f"--db={db}")
    elif key or project.s.PIPENV_PYUP_API_KEY:
        cmd = cmd + [f"--key={key or project.s.PIPENV_PYUP_API_KEY}"]
    if ignored:
        for cve in ignored:
            cmd += cve
    c = run_command(cmd, catch_exceptions=False, is_verbose=project.s.is_verbose())
    if output == "default":
        try:
            results = simplejson.loads(c.stdout)
        except (ValueError, json.JSONDecodeError):
            raise exceptions.JSONParseError(c.stdout, c.stderr)
        except Exception:
            raise exceptions.PipenvCmdError(
                cmd_list_to_shell(c.args), c.stdout, c.stderr, c.returncode
            )
        for (package, resolved, installed, description, vuln, *_) in results:
            click.echo(
                "{}: {} {} resolved ({} installed)!".format(
                    crayons.normal(vuln, bold=True),
                    crayons.green(package),
                    crayons.yellow(resolved, bold=False),
                    crayons.yellow(installed, bold=True),
                )
            )
            click.echo(f"{description}")
            click.echo()
        if c.returncode == 0:
            click.echo(crayons.green("All good!"))
            sys.exit(0)
        else:
            sys.exit(1)
    else:
        click.echo(c.stdout)
        sys.exit(c.returncode)


def do_graph(project, bare=False, json=False, json_tree=False, reverse=False):
    import json as jsonlib

    from pipenv.vendor import pipdeptree

    pipdeptree_path = pipdeptree.__file__.rstrip("cdo")
    try:
        python_path = project._which("python")
    except AttributeError:
        click.echo(
            "{}: {}".format(
                crayons.red("Warning", bold=True),
                "Unable to display currently-installed dependency graph information here. "
                "Please run within a Pipenv project.",
            ),
            err=True,
        )
        sys.exit(1)
    except RuntimeError:
        pass
    else:
        if not os.name == "nt":  # bugfix #4388
            python_path = Path(python_path).as_posix()
            pipdeptree_path = Path(pipdeptree_path).as_posix()

    if reverse and json:
        click.echo(
            "{}: {}".format(
                crayons.red("Warning", bold=True),
                "Using both --reverse and --json together is not supported. "
                "Please select one of the two options.",
            ),
            err=True,
        )
        sys.exit(1)
    if reverse and json_tree:
        click.echo(
            "{}: {}".format(
                crayons.red("Warning", bold=True),
                "Using both --reverse and --json-tree together is not supported. "
                "Please select one of the two options.",
            ),
            err=True,
        )
        sys.exit(1)
    if json and json_tree:
        click.echo(
            "{}: {}".format(
                crayons.red("Warning", bold=True),
                "Using both --json and --json-tree together is not supported. "
                "Please select one of the two options.",
            ),
            err=True,
        )
        sys.exit(1)
    flag = ""
    if json:
        flag = "--json"
    if json_tree:
        flag = "--json-tree"
    if reverse:
        flag = "--reverse"
    if not project.virtualenv_exists:
        click.echo(
            "{}: No virtualenv has been created for this project yet! Consider "
            "running {} first to automatically generate one for you or see "
            "{} for further instructions.".format(
                crayons.red("Warning", bold=True),
                crayons.green("`pipenv install`"),
                crayons.green("`pipenv install --help`"),
            ),
            err=True,
        )
        sys.exit(1)
    cmd_args = [python_path, pipdeptree_path, "-l"]
    if flag:
        cmd_args.append(flag)
    c = run_command(cmd_args, is_verbose=project.s.is_verbose())
    # Run dep-tree.
    if not bare:
        if json:
            data = []
            try:
                parsed = simplejson.loads(c.stdout.strip())
            except jsonlib.JSONDecodeError:
                raise exceptions.JSONParseError(c.stdout, c.stderr)
            else:
                for d in parsed:
                    if d["package"]["key"] not in BAD_PACKAGES:
                        data.append(d)
            click.echo(simplejson.dumps(data, indent=4))
            sys.exit(0)
        elif json_tree:

            def traverse(obj):
                if isinstance(obj, list):
                    return [
                        traverse(package)
                        for package in obj
                        if package["key"] not in BAD_PACKAGES
                    ]
                else:
                    obj["dependencies"] = traverse(obj["dependencies"])
                    return obj

            try:
                parsed = simplejson.loads(c.stdout.strip())
            except jsonlib.JSONDecodeError:
                raise exceptions.JSONParseError(c.stdout, c.stderr)
            else:
                data = traverse(parsed)
                click.echo(simplejson.dumps(data, indent=4))
                sys.exit(0)
        else:
            for line in c.stdout.strip().split("\n"):
                # Ignore bad packages as top level.
                # TODO: This should probably be a "==" in + line.partition
                if line.split("==")[0] in BAD_PACKAGES and not reverse:
                    continue

                # Bold top-level packages.
                if not line.startswith(" "):
                    click.echo(crayons.normal(line, bold=True))
                # Echo the rest.
                else:
                    click.echo(crayons.normal(line, bold=False))
    else:
        click.echo(c.stdout)
    if c.returncode != 0:
        click.echo(
            "{} {}".format(
                crayons.red("ERROR: ", bold=True),
                crayons.white(f"{c.stderr}"),
            ),
            err=True,
        )
    # Return its return code.
    sys.exit(c.returncode)


def do_sync(
    project,
    dev=False,
    three=None,
    python=None,
    bare=False,
    dont_upgrade=False,
    user=False,
    clear=False,
    unused=False,
    sequential=False,
    pypi_mirror=None,
    system=False,
    deploy=False,
):
    # The lock file needs to exist because sync won't write to it.
    if not project.lockfile_exists:
        raise exceptions.LockfileNotFound("Pipfile.lock")

    # Ensure that virtualenv is available if not system.
    ensure_project(
        project,
        three=three,
        python=python,
        validate=False,
        system=system,
        deploy=deploy,
        pypi_mirror=pypi_mirror,
        clear=clear,
    )

    # Install everything.
    requirements_dir = vistir.path.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    if system:
        project.s.PIPENV_USE_SYSTEM = True
        os.environ["PIPENV_USE_SYSTEM"] = "1"
    do_init(
        project,
        dev=dev,
        allow_global=system,
        concurrent=(not sequential),
        requirements_dir=requirements_dir,
        ignore_pipfile=True,  # Don't check if Pipfile and lock match.
        pypi_mirror=pypi_mirror,
        deploy=deploy,
        system=system,
    )
    if not bare:
        click.echo(crayons.green("All dependencies are now up-to-date!"))


def do_clean(
    project,
    three=None,
    python=None,
    dry_run=False,
    bare=False,
    pypi_mirror=None,
    system=False,
):
    # Ensure that virtualenv is available.
    from packaging.utils import canonicalize_name

    ensure_project(
        project, three=three, python=python, validate=False, pypi_mirror=pypi_mirror
    )
    ensure_lockfile(project, pypi_mirror=pypi_mirror)
    # Make sure that the virtualenv's site packages are configured correctly
    # otherwise we may end up removing from the global site packages directory
    installed_package_names = project.installed_package_names.copy()
    # Remove known "bad packages" from the list.
    for bad_package in BAD_PACKAGES:
        if canonicalize_name(bad_package) in installed_package_names:
            if project.s.is_verbose():
                click.echo(f"Ignoring {bad_package}.", err=True)
            installed_package_names.remove(canonicalize_name(bad_package))
    # Intelligently detect if --dev should be used or not.
    locked_packages = {
        canonicalize_name(pkg) for pkg in project.lockfile_package_names["combined"]
    }
    for used_package in locked_packages:
        if used_package in installed_package_names:
            installed_package_names.remove(used_package)
    failure = False
    cmd = [which_pip(project, allow_global=system), "uninstall", "-y", "-qq"]
    for apparent_bad_package in installed_package_names:
        if dry_run and not bare:
            click.echo(apparent_bad_package)
        else:
            if not bare:
                click.echo(
                    crayons.white(
                        fix_utf8(f"Uninstalling {apparent_bad_package}..."), bold=True
                    )
                )
            # Uninstall the package.
            cmd = [which_pip(project), "uninstall", apparent_bad_package, "-y"]
            c = run_command(cmd, is_verbose=project.s.is_verbose())
            if c.returncode != 0:
                failure = True
    sys.exit(int(failure))
