# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import io
import json as simplejson
import logging
import os
import sys
import time
import warnings

import click
import six

import delegator
import dotenv
import pipfile
import vistir

from click_completion import init as init_completion

from . import environments, exceptions, pep508checker, progress
from ._compat import decode_for_output, fix_utf8
from .cmdparse import Script
from .environments import (
    PIP_EXISTS_ACTION, PIPENV_CACHE_DIR, PIPENV_COLORBLIND,
    PIPENV_DEFAULT_PYTHON_VERSION, PIPENV_DONT_USE_PYENV, PIPENV_DONT_USE_ASDF,
    PIPENV_HIDE_EMOJIS, PIPENV_MAX_SUBPROCESS, PIPENV_PYUP_API_KEY,
    PIPENV_RESOLVE_VCS, PIPENV_SHELL_FANCY, PIPENV_SKIP_VALIDATION, PIPENV_YES,
    SESSION_IS_INTERACTIVE, is_type_checking
)
from .patched import crayons
from .project import Project
from .utils import (
    convert_deps_to_pip, create_spinner, download_file,
    escape_grouped_arguments, find_python, find_windows_executable,
    get_canonical_names, get_source_list, interrupt_handled_subprocess,
    is_pinned, is_python_command, is_required_version, is_star, is_valid_url,
    parse_indexes, pep423_name, prepare_pip_source_args, proper_case,
    python_version, run_command, venv_resolve_deps
)


if is_type_checking():
    from typing import Dict, List, Optional, Union, Text
    from pipenv.vendor.requirementslib.models.requirements import Requirement
    TSourceDict = Dict[Text, Union[Text, bool]]


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
# Are we using the default Python?
USING_DEFAULT_PYTHON = True
if not PIPENV_HIDE_EMOJIS:
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
# Enable shell completion.
init_completion()
# Disable colors, for the color blind and others who do not prefer colors.
if PIPENV_COLORBLIND:
    crayons.disable()


def which(command, location=None, allow_global=False):
    if not allow_global and location is None:
        if project.virtualenv_exists:
            location = project.virtualenv_location
        else:
            location = os.environ.get("VIRTUAL_ENV", None)
    if not (location and os.path.exists(location)) and not allow_global:
        raise RuntimeError("location not created nor specified")

    version_str = "python{0}".format(".".join([str(v) for v in sys.version_info[:2]]))
    is_python = command in ("python", os.path.basename(sys.executable), version_str)
    if not allow_global:
        if os.name == "nt":
            p = find_windows_executable(os.path.join(location, "Scripts"), command)
        else:
            p = os.path.join(location, "bin", command)
    else:
        if is_python:
            p = sys.executable
    if not os.path.exists(p):
        if is_python:
            p = sys.executable or system_which("python")
        else:
            p = system_which(command)
    return p


project = Project(which=which)


def do_clear():
    click.echo(crayons.white(fix_utf8("Clearing caches…"), bold=True))
    try:
        from pip._internal import locations
    except ImportError:  # pip 9.
        from pip import locations

    try:
        vistir.path.rmtree(PIPENV_CACHE_DIR, onerror=vistir.path.handle_remove_readonly)
        # Other processes may be writing into this directory simultaneously.
        vistir.path.rmtree(
            locations.USER_CACHE_DIR,
            ignore_errors=environments.PIPENV_IS_CI,
            onerror=vistir.path.handle_remove_readonly
        )
    except OSError as e:
        # Ignore FileNotFoundError. This is needed for Python 2.7.
        import errno

        if e.errno == errno.ENOENT:
            pass
        raise


def load_dot_env():
    """Loads .env file into sys.environ."""
    if not environments.PIPENV_DONT_LOAD_ENV:
        # If the project doesn't exist yet, check current directory for a .env file
        project_directory = project.project_directory or "."
        dotenv_file = environments.PIPENV_DOTENV_LOCATION or os.sep.join(
            [project_directory, ".env"]
        )

        if os.path.isfile(dotenv_file):
            click.echo(
                crayons.normal(fix_utf8("Loading .env environment variables…"), bold=True),
                err=True,
            )
        else:
            if environments.PIPENV_DOTENV_LOCATION:
                click.echo(
                    "{0}: file {1}={2} does not exist!!\n{3}".format(
                        crayons.red("Warning", bold=True),
                        crayons.normal("PIPENV_DOTENV_LOCATION", bold=True),
                        crayons.normal(environments.PIPENV_DOTENV_LOCATION, bold=True),
                        crayons.red("Not loading environment variables.", bold=True),
                    ),
                    err=True,
                )
        dotenv.load_dotenv(dotenv_file, override=True)
        six.moves.reload_module(environments)


def add_to_path(p):
    """Adds a given path to the PATH."""
    if p not in os.environ["PATH"]:
        os.environ["PATH"] = "{0}{1}{2}".format(p, os.pathsep, os.environ["PATH"])


def cleanup_virtualenv(bare=True):
    """Removes the virtualenv directory from the system."""
    if not bare:
        click.echo(crayons.red("Environment creation aborted."))
    try:
        # Delete the virtualenv.
        vistir.path.rmtree(project.virtualenv_location)
    except OSError as e:
        click.echo(
            "{0} An error occurred while removing {1}!".format(
                crayons.red("Error: ", bold=True),
                crayons.green(project.virtualenv_location),
            ),
            err=True,
        )
        click.echo(crayons.blue(e), err=True)


def import_requirements(r=None, dev=False):
    from .patched.notpip._vendor import requests as pip_requests
    from .vendor.pip_shims.shims import parse_requirements

    # Parse requirements.txt file with Pip's parser.
    # Pip requires a `PipSession` which is a subclass of requests.Session.
    # Since we're not making any network calls, it's initialized to nothing.
    if r:
        assert os.path.isfile(r)
    # Default path, if none is provided.
    if r is None:
        r = project.requirements_location
    with open(r, "r") as f:
        contents = f.read()
    indexes = []
    trusted_hosts = []
    # Find and add extra indexes.
    for line in contents.split("\n"):
        line_indexes, _trusted_hosts, _ = parse_indexes(line.strip())
        indexes.extend(line_indexes)
        trusted_hosts.extend(_trusted_hosts)
    indexes = sorted(set(indexes))
    trusted_hosts = sorted(set(trusted_hosts))
    reqs = [f for f in parse_requirements(r, session=pip_requests)]
    for package in reqs:
        if package.name not in BAD_PACKAGES:
            if package.link is not None:
                package_string = (
                    "-e {0}".format(package.link)
                    if package.editable
                    else str(package.link)
                )
                project.add_package_to_pipfile(package_string, dev=dev)
            else:
                project.add_package_to_pipfile(str(package.req), dev=dev)
    for index in indexes:
        trusted = index in trusted_hosts
        project.add_index_to_pipfile(index, verify_ssl=trusted)
    project.recase_pipfile()


def ensure_environment():
    # Skip this on Windows…
    if os.name != "nt":
        if "LANG" not in os.environ:
            click.echo(
                "{0}: the environment variable {1} is not set!"
                "\nWe recommend setting this in {2} (or equivalent) for "
                "proper expected behavior.".format(
                    crayons.red("Warning", bold=True),
                    crayons.normal("LANG", bold=True),
                    crayons.green("~/.profile"),
                ),
                err=True,
            )


def import_from_code(path="."):
    from pipreqs import pipreqs

    rs = []
    try:
        for r in pipreqs.get_all_imports(
            path, encoding="utf-8", extra_ignore_dirs=[".venv"]
        ):
            if r not in BAD_PACKAGES:
                rs.append(r)
        pkg_names = pipreqs.get_pkg_names(rs)
        return [proper_case(r) for r in pkg_names]

    except Exception:
        return []


def ensure_pipfile(validate=True, skip_requirements=False, system=False):
    """Creates a Pipfile for the project, if it doesn't exist."""
    from .environments import PIPENV_VIRTUALENV

    # Assert Pipfile exists.
    python = which("python") if not (USING_DEFAULT_PYTHON or system) else None
    if project.pipfile_is_empty:
        # Show an error message and exit if system is passed and no pipfile exists
        if system and not PIPENV_VIRTUALENV:
            raise exceptions.PipenvOptionsError(
                "--system",
                "--system is intended to be used for pre-existing Pipfile "
                "installation, not installation of specific packages. Aborting."
            )
        # If there's a requirements file, but no Pipfile…
        if project.requirements_exists and not skip_requirements:
            click.echo(
                crayons.normal(
                    fix_utf8("requirements.txt found, instead of Pipfile! Converting…"),
                    bold=True,
                )
            )
            # Create a Pipfile…
            project.create_pipfile(python=python)
            with create_spinner("Importing requirements...") as sp:
                # Import requirements.txt.
                try:
                    import_requirements()
                except Exception:
                    sp.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format("Failed..."))
                else:
                    sp.ok(environments.PIPENV_SPINNER_OK_TEXT.format("Success!"))
            # Warn the user of side-effects.
            click.echo(
                u"{0}: Your {1} now contains pinned versions, if your {2} did. \n"
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
                crayons.normal(fix_utf8("Creating a Pipfile for this project…"), bold=True),
                err=True,
            )
            # Create the pipfile if it doesn't exist.
            project.create_pipfile(python=python)
    # Validate the Pipfile's contents.
    if validate and project.virtualenv_exists and not PIPENV_SKIP_VALIDATION:
        # Ensure that Pipfile is using proper casing.
        p = project.parsed_pipfile
        changed = project.ensure_proper_casing()
        # Write changes out to disk.
        if changed:
            click.echo(
                crayons.normal(u"Fixing package names in Pipfile…", bold=True), err=True
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


def ensure_python(three=None, python=None):
    # Runtime import is necessary due to the possibility that the environments module may have been reloaded.
    from .environments import PIPENV_PYTHON, PIPENV_YES

    if PIPENV_PYTHON and python is False and three is None:
        python = PIPENV_PYTHON

    def abort(msg=''):
        click.echo(
            "{0}\nYou can specify specific versions of Python with:\n{1}".format(
                crayons.red(msg),
                crayons.red(
                    "$ pipenv --python {0}".format(
                        os.sep.join(("path", "to", "python"))
                    )
                )
            ),
            err=True,
        )
        sys.exit(1)

    global USING_DEFAULT_PYTHON
    USING_DEFAULT_PYTHON = three is None and not python
    # Find out which python is desired.
    if not python:
        python = convert_three_to_python(three, python)
    if not python:
        python = project.required_python_version
    if not python:
        python = PIPENV_DEFAULT_PYTHON_VERSION
    path_to_python = find_a_system_python(python)
    if environments.is_verbose():
        click.echo(u"Using python: {0}".format(python), err=True)
        click.echo(u"Path to python: {0}".format(path_to_python), err=True)
    if not path_to_python and python is not None:
        # We need to install Python.
        click.echo(
            u"{0}: Python {1} {2}".format(
                crayons.red("Warning", bold=True),
                crayons.blue(python),
                fix_utf8("was not found on your system…"),
            ),
            err=True,
        )
        # check for python installers
        from .installers import Pyenv, Asdf, InstallerError, InstallerNotFound

        # prefer pyenv if both pyenv and asdf are installed as it's
        # dedicated to python installs so probably the preferred
        # method of the user for new python installs.
        installer = None
        if not PIPENV_DONT_USE_PYENV:
            try:
                installer = Pyenv()
            except InstallerNotFound:
                pass
        if installer is None and not PIPENV_DONT_USE_ASDF:
            try:
                installer = Asdf()
            except InstallerNotFound:
                pass

        if not installer:
            abort("Neither 'pyenv' nor 'asdf' could be found to install Python.")
        else:
            if SESSION_IS_INTERACTIVE or PIPENV_YES:
                try:
                    version = installer.find_version_to_install(python)
                except ValueError:
                    abort()
                except InstallerError as e:
                    abort('Something went wrong while installing Python:\n{}'.format(e.err))
                s = "{0} {1} {2}".format(
                    "Would you like us to install",
                    crayons.green("CPython {0}".format(version)),
                    "with {0}?".format(installer),
                )
                # Prompt the user to continue…
                if not (PIPENV_YES or click.confirm(s, default=True)):
                    abort()
                else:
                    # Tell the user we're installing Python.
                    click.echo(
                        u"{0} {1} {2} {3}{4}".format(
                            crayons.normal(u"Installing", bold=True),
                            crayons.green(u"CPython {0}".format(version), bold=True),
                            crayons.normal(u"with {0}".format(installer.cmd), bold=True),
                            crayons.normal(u"(this may take a few minutes)"),
                            crayons.normal(fix_utf8("…"), bold=True),
                        )
                    )
                    with create_spinner("Installing python...") as sp:
                        try:
                            c = installer.install(version)
                        except InstallerError as e:
                            sp.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format(
                                "Failed...")
                            )
                            click.echo(fix_utf8("Something went wrong…"), err=True)
                            click.echo(crayons.blue(e.err), err=True)
                        else:
                            sp.ok(environments.PIPENV_SPINNER_OK_TEXT.format("Success!"))
                            # Print the results, in a beautiful blue…
                            click.echo(crayons.blue(c.out), err=True)
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
                            "{0}: The Python you just installed is not available on your {1}, apparently."
                            "".format(
                                crayons.red("Warning", bold=True),
                                crayons.normal("PATH", bold=True),
                            ),
                            err=True,
                        )
                        sys.exit(1)
    return path_to_python


def ensure_virtualenv(three=None, python=None, site_packages=None, pypi_mirror=None):
    """Creates a virtualenv, if one doesn't exist."""
    from .environments import PIPENV_USE_SYSTEM

    def abort():
        sys.exit(1)

    global USING_DEFAULT_PYTHON
    if not project.virtualenv_exists:
        try:
            # Ensure environment variables are set properly.
            ensure_environment()
            # Ensure Python is available.
            python = ensure_python(three=three, python=python)
            if python is not None and not isinstance(python, six.string_types):
                python = python.path.as_posix()
            # Create the virtualenv.
            # Abort if --system (or running in a virtualenv).
            if PIPENV_USE_SYSTEM:
                click.echo(
                    crayons.red(
                        "You are attempting to re–create a virtualenv that "
                        "Pipenv did not create. Aborting."
                    )
                )
                sys.exit(1)
            do_create_virtualenv(
                python=python, site_packages=site_packages, pypi_mirror=pypi_mirror
            )
        except KeyboardInterrupt:
            # If interrupted, cleanup the virtualenv.
            cleanup_virtualenv(bare=False)
            sys.exit(1)
    # If --three, --two, or --python were passed…
    elif (python) or (three is not None) or (site_packages is not None):
        USING_DEFAULT_PYTHON = False
        # Ensure python is installed before deleting existing virtual env
        python = ensure_python(three=three, python=python)
        if python is not None and not isinstance(python, six.string_types):
            python = python.path.as_posix()

        click.echo(crayons.red("Virtualenv already exists!"), err=True)
        # If VIRTUAL_ENV is set, there is a possibility that we are
        # going to remove the active virtualenv that the user cares
        # about, so confirm first.
        if "VIRTUAL_ENV" in os.environ:
            if not (
                PIPENV_YES or click.confirm("Remove existing virtualenv?", default=True)
            ):
                abort()
        click.echo(
            crayons.normal(fix_utf8("Removing existing virtualenv…"), bold=True), err=True
        )
        # Remove the virtualenv.
        cleanup_virtualenv(bare=True)
        # Call this function again.
        ensure_virtualenv(
            three=three,
            python=python,
            site_packages=site_packages,
            pypi_mirror=pypi_mirror,
        )


def ensure_project(
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
    from .environments import PIPENV_USE_SYSTEM

    # Clear the caches, if appropriate.
    if clear:
        print("clearing")
        sys.exit(1)

    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True
    if not project.pipfile_exists and deploy:
        raise exceptions.PipfileNotFound
    # Skip virtualenv creation when --system was used.
    if not system:
        ensure_virtualenv(
            three=three,
            python=python,
            site_packages=site_packages,
            pypi_mirror=pypi_mirror,
        )
        if warn:
            # Warn users if they are using the wrong version of Python.
            if project.required_python_version:
                path_to_python = which("python") or which("py")
                if path_to_python and project.required_python_version not in (
                    python_version(path_to_python) or ""
                ):
                    click.echo(
                        "{0}: Your Pipfile requires {1} {2}, "
                        "but you are using {3} ({4}).".format(
                            crayons.red("Warning", bold=True),
                            crayons.normal("python_version", bold=True),
                            crayons.blue(project.required_python_version),
                            crayons.blue(python_version(path_to_python) or "unknown"),
                            crayons.green(shorten_path(path_to_python)),
                        ),
                        err=True,
                    )
                    click.echo(
                        "  {0} and rebuilding the virtual environment "
                        "may resolve the issue.".format(crayons.green("$ pipenv --rm")),
                        err=True,
                    )
                    if not deploy:
                        click.echo(
                            "  {0} will surely fail."
                            "".format(crayons.red("$ pipenv check")),
                            err=True,
                        )
                    else:
                        raise exceptions.DeployException
    # Ensure the Pipfile exists.
    ensure_pipfile(
        validate=validate, skip_requirements=skip_requirements, system=system
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
def do_where(virtualenv=False, bare=True):
    """Executes the where functionality."""
    if not virtualenv:
        if not project.pipfile_exists:
            click.echo(
                "No Pipfile present at project home. Consider running "
                "{0} first to automatically generate a Pipfile for you."
                "".format(crayons.green("`pipenv install`")),
                err=True,
            )
            return
        location = project.pipfile_location
        # Shorten the virtual display of the path to the virtualenv.
        if not bare:
            location = shorten_path(location)
            click.echo(
                "Pipfile found at {0}.\n  Considering this to be the project home."
                "".format(crayons.green(location)),
                err=True,
            )
        else:
            click.echo(project.project_directory)
    else:
        location = project.virtualenv_location
        if not bare:
            click.echo(
                "Virtualenv location: {0}".format(crayons.green(location)), err=True
            )
        else:
            click.echo(location)


def _cleanup_procs(procs, failed_deps_queue, retry=True):
    while not procs.empty():
        c = procs.get()
        if not c.blocking:
            c.block()
        failed = False
        if c.return_code != 0:
            failed = True
        if "Ignoring" in c.out:
            click.echo(crayons.yellow(c.out.strip()))
        elif environments.is_verbose():
            click.echo(crayons.blue(c.out.strip() or c.err.strip()))
        # The Installation failed…
        if failed:
            # If there is a mismatch in installed locations or the install fails
            # due to wrongful disabling of pep517, we should allow for
            # additional passes at installation
            if "does not match installed location" in c.err:
                project.environment.expand_egg_links()
                click.echo("{0}".format(
                    crayons.yellow(
                        "Failed initial installation: Failed to overwrite existing "
                        "package, likely due to path aliasing. Expanding and trying "
                        "again!"
                    )
                ))
                dep = c.dep.copy()
                dep.use_pep517 = True
            elif "Disabling PEP 517 processing is invalid" in c.err:
                dep = c.dep.copy()
                dep.use_pep517 = True
            elif not retry:
                # The Installation failed…
                # We echo both c.out and c.err because pip returns error details on out.
                err = c.err.strip().splitlines() if c.err else []
                out = c.out.strip().splitlines() if c.out else []
                err_lines = [line for message in [out, err] for line in message]
                # Return the subprocess' return code.
                raise exceptions.InstallError(c.dep.name, extra=err_lines)
            else:
                # Alert the user.
                dep = c.dep.copy()
                dep.use_pep517 = False
                click.echo(
                    "{0} {1}! Will try again.".format(
                        crayons.red("An error occurred while installing"),
                        crayons.green(dep.as_line()),
                    ), err=True
                )
            # Save the Failed Dependency for later.
            failed_deps_queue.put(dep)


def batch_install(deps_list, procs, failed_deps_queue,
                  requirements_dir, no_deps=True, ignore_hashes=False,
                  allow_global=False, blocking=False, pypi_mirror=None,
                  retry=True, sequential_deps=None):
    from .vendor.requirementslib.models.utils import strip_extras_markers_from_requirement
    if sequential_deps is None:
        sequential_deps = []
    failed = (not retry)
    install_deps = not no_deps
    if not failed:
        label = INSTALL_LABEL if not PIPENV_HIDE_EMOJIS else ""
    else:
        label = INSTALL_LABEL2

    deps_to_install = deps_list[:]
    deps_to_install.extend(sequential_deps)
    deps_to_install = [
        dep for dep in deps_to_install if not project.environment.is_satisfied(dep)
    ]
    sequential_dep_names = [d.name for d in sequential_deps]

    deps_list_bar = progress.bar(
        deps_to_install, width=32,
        label=label
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
        if dep.is_file_or_url and (dep.is_direct_url or any(
            dep.req.uri.endswith(ext) for ext in ["zip", "tar.gz"]
        )):
            is_artifact = True
        elif dep.is_vcs:
            is_artifact = True
        if not PIPENV_RESOLVE_VCS and is_artifact and not dep.editable:
            install_deps = True
            no_deps = False

        with vistir.contextmanagers.temp_environ():
            if not allow_global:
                os.environ["PIP_USER"] = vistir.compat.fs_str("0")
                if "PYTHONHOME" in os.environ:
                    del os.environ["PYTHONHOME"]
            if "GIT_CONFIG" in os.environ and dep.is_vcs:
                del os.environ["GIT_CONFIG"]
            use_pep517 = True
            if failed and not dep.is_vcs:
                use_pep517 = getattr(dep, "use_pep517", False)

            c = pip_install(
                dep,
                ignore_hashes=any([ignore_hashes, dep.editable, dep.is_vcs]),
                allow_global=allow_global,
                no_deps=not install_deps,
                block=any([dep.editable, dep.is_vcs, blocking]),
                index=dep.index,
                requirements_dir=requirements_dir,
                pypi_mirror=pypi_mirror,
                trusted_hosts=trusted_hosts,
                extra_indexes=extra_indexes,
                use_pep517=use_pep517,
            )
            c.dep = dep
            # if dep.is_vcs or dep.editable:
            is_sequential = sequential_deps and dep.name in sequential_dep_names
            if is_sequential:
                c.block()

            procs.put(c)
            if procs.full() or procs.qsize() == len(deps_list) or is_sequential:
                _cleanup_procs(procs, failed_deps_queue, retry=retry)


def do_install_dependencies(
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
    """"
    Executes the install functionality.

    If emit_requirements is True, simply spits out a requirements format to stdout.
    """

    from six.moves import queue
    if emit_requirements:
        bare = True
    # Load the lockfile if it exists, or if dev_only is being used.
    if skip_lock or not project.lockfile_exists:
        if not bare:
            click.echo(
                crayons.normal(fix_utf8("Installing dependencies from Pipfile…"), bold=True)
            )
            # skip_lock should completely bypass the lockfile (broken in 4dac1676)
            lockfile = project.get_or_create_lockfile(from_pipfile=True)
    else:
        lockfile = project.get_or_create_lockfile()
        if not bare:
            click.echo(
                crayons.normal(
                    fix_utf8("Installing dependencies from Pipfile.lock ({0})…".format(
                        lockfile["_meta"].get("hash", {}).get("sha256")[-6:]
                    )),
                    bold=True,
                )
            )
    # Allow pip to resolve dependencies when in skip-lock mode.
    no_deps = not skip_lock  # skip_lock true, no_deps False, pip resolves deps
    dev = dev or dev_only
    deps_list = list(lockfile.get_requirements(dev=dev, only=dev_only))
    if emit_requirements:
        index_args = prepare_pip_source_args(get_source_list(pypi_mirror=pypi_mirror, project=project))
        index_args = " ".join(index_args).replace(" -", "\n-")
        deps = [
            req.as_line(sources=False, include_hashes=False) for req in deps_list
        ]
        click.echo(index_args)
        click.echo(
            "\n".join(sorted(deps))
        )
        sys.exit(0)

    if concurrent:
        nprocs = PIPENV_MAX_SUBPROCESS
    else:
        nprocs = 1
    procs = queue.Queue(maxsize=nprocs)
    failed_deps_queue = queue.Queue()
    if skip_lock:
        ignore_hashes = True
    editable_or_vcs_deps = [dep for dep in deps_list if (dep.editable or dep.vcs)]
    normal_deps = [dep for dep in deps_list if not (dep.editable or dep.vcs)]
    install_kwargs = {
        "no_deps": no_deps, "ignore_hashes": ignore_hashes, "allow_global": allow_global,
        "blocking": not concurrent, "pypi_mirror": pypi_mirror,
        "sequential_deps": editable_or_vcs_deps
    }

    batch_install(
        normal_deps, procs, failed_deps_queue, requirements_dir, **install_kwargs
    )

    if not procs.empty():
        _cleanup_procs(procs, failed_deps_queue)

    # click.echo(crayons.normal(
    #     decode_for_output("Installing editable and vcs dependencies…"), bold=True
    # ))

    # install_kwargs.update({"blocking": True})
    # # XXX: All failed and editable/vcs deps should be installed in sequential mode!
    # procs = queue.Queue(maxsize=1)
    # batch_install(
    #     editable_or_vcs_deps, procs, failed_deps_queue, requirements_dir,
    #     **install_kwargs
    # )

    # Iterate over the hopefully-poorly-packaged dependencies…
    if not failed_deps_queue.empty():
        click.echo(
            crayons.normal(fix_utf8("Installing initially failed dependencies…"), bold=True)
        )
        retry_list = []
        while not failed_deps_queue.empty():
            failed_dep = failed_deps_queue.get()
            retry_list.append(failed_dep)
        install_kwargs.update({"retry": False})
        batch_install(
            retry_list, procs, failed_deps_queue, requirements_dir, **install_kwargs
        )
    if not procs.empty():
        _cleanup_procs(procs, failed_deps_queue, retry=False)


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


def do_create_virtualenv(python=None, site_packages=None, pypi_mirror=None):
    """Creates a virtualenv."""

    click.echo(
        crayons.normal(fix_utf8("Creating a virtualenv for this project…"), bold=True), err=True
    )
    click.echo(
        u"Pipfile: {0}".format(crayons.red(project.pipfile_location, bold=True)),
        err=True,
    )

    # Default to using sys.executable, if Python wasn't provided.
    using_string = u"Using"
    if not python:
        python = sys.executable
        using_string = "Using default python from"
    click.echo(
        u"{0} {1} {3} {2}".format(
            crayons.normal(using_string, bold=True),
            crayons.red(python, bold=True),
            crayons.normal(fix_utf8("to create virtualenv…"), bold=True),
            crayons.green("({0})".format(python_version(python))),
        ),
        err=True,
    )

    cmd = [
        vistir.compat.Path(sys.executable).absolute().as_posix(),
        "-m",
        "virtualenv",
        "--prompt=({0}) ".format(project.name),
        "--python={0}".format(python),
        project.get_location_for_virtualenv(),
    ]

    # Pass site-packages flag to virtualenv, if desired…
    if site_packages:
        click.echo(
            crayons.normal(fix_utf8("Making site-packages available…"), bold=True), err=True
        )
        cmd.append("--system-site-packages")

    if pypi_mirror:
        pip_config = {"PIP_INDEX_URL": vistir.misc.fs_str(pypi_mirror)}
    else:
        pip_config = {}

    # Actually create the virtualenv.
    error = None
    with create_spinner(u"Creating virtual environment...") as sp:
        with interrupt_handled_subprocess(cmd, combine_stderr=False, env=pip_config) as c:
            click.echo(crayons.blue(u"{0}".format(c.out)), err=True)
            if c.returncode != 0:
                error = c.err if environments.is_verbose() else exceptions.prettify_exc(c.err)
                sp.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format(u"Failed creating virtual environment"))
            else:
                sp.green.ok(environments.PIPENV_SPINNER_OK_TEXT.format(u"Successfully created virtual environment!"))
    if error is not None:
        raise exceptions.VirtualenvCreationException(
            extra=crayons.red("{0}".format(error))
        )

    # Associate project directory with the environment.
    # This mimics Pew's "setproject".
    project_file_name = os.path.join(project.virtualenv_location, ".project")
    with open(project_file_name, "w") as f:
        f.write(vistir.misc.fs_str(project.project_directory))
    from .environment import Environment
    sources = project.pipfile_sources
    # project.get_location_for_virtualenv is only for if we are creating a new virtualenv
    # whereas virtualenv_location is for the current path to the runtime
    project._environment = Environment(
        prefix=project.virtualenv_location,
        is_venv=True,
        sources=sources,
        pipfile=project.parsed_pipfile,
        project=project
    )
    project._environment.add_dist("pipenv")
    # Say where the virtualenv is.
    do_where(virtualenv=True, bare=False)


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


def get_downloads_info(names_map, section):
    from .vendor.requirementslib.models.requirements import Requirement

    info = []
    p = project.parsed_pipfile
    for fname in os.listdir(project.download_location):
        # Get name from filename mapping.
        name = Requirement.from_line(names_map[fname]).name
        # Get the version info from the filenames.
        version = parse_download_fname(fname, name)
        # Get the hash of each file.
        cmd = '{0} hash "{1}"'.format(
            escape_grouped_arguments(which_pip()),
            os.sep.join([project.download_location, fname]),
        )
        c = delegator.run(cmd)
        hash = c.out.split("--hash=")[1].strip()
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
                "--keep-outdated", ctx=ctx,
                message="Pipfile.lock must exist to use --keep-outdated!"
            )
        cached_lockfile = project.lockfile_content
    # Create the lockfile.
    lockfile = project._lockfile
    # Cleanup lockfile.
    for section in ("default", "develop"):
        for k, v in lockfile[section].copy().items():
            if not hasattr(v, "keys"):
                del lockfile[section][k]
    # Ensure that develop inherits from default.
    dev_packages = project.dev_packages.copy()
    dev_packages = overwrite_dev(project.packages, dev_packages)
    # Resolve dev-package dependencies, with pip-tools.
    for is_dev in [True, False]:
        pipfile_section = "dev-packages" if is_dev else "packages"
        if project.pipfile_exists:
            packages = project.parsed_pipfile.get(pipfile_section, {})
        else:
            packages = getattr(project, pipfile_section.replace("-", "_"))

        if write:
            # Alert the user of progress.
            click.echo(
                u"{0} {1} {2}".format(
                    crayons.normal(u"Locking"),
                    crayons.red(u"[{0}]".format(pipfile_section.replace("_", "-"))),
                    crayons.normal(fix_utf8("dependencies…")),
                ),
                err=True,
            )

        # Mutates the lockfile
        venv_resolve_deps(
            packages,
            which=which,
            project=project,
            dev=is_dev,
            clear=clear,
            pre=pre,
            allow_global=system,
            pypi_mirror=pypi_mirror,
            pipfile=packages,
            lockfile=lockfile,
            keep_outdated=keep_outdated
        )

    # Support for --keep-outdated…
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
    lockfile["develop"].update(overwrite_dev(lockfile.get("default", {}), lockfile["develop"]))
    if write:
        project.write_lockfile(lockfile)
        click.echo(
            "{0}".format(
                crayons.normal(
                    "Updated Pipfile.lock ({0})!".format(
                        lockfile["_meta"].get("hash", {}).get("sha256")[-6:]
                    ),
                    bold=True,
                )
            ),
            err=True,
        )
    else:
        return lockfile


def do_purge(bare=False, downloads=False, allow_global=False):
    """Executes the purge functionality."""

    if downloads:
        if not bare:
            click.echo(crayons.normal(fix_utf8("Clearing out downloads directory…"), bold=True))
        vistir.path.rmtree(project.download_location)
        return

    # Remove comments from the output, if any.
    installed = set([
        pep423_name(pkg.project_name) for pkg in project.environment.get_installed_packages()
    ])
    bad_pkgs = set([pep423_name(pkg) for pkg in BAD_PACKAGES])
    # Remove setuptools, pip, etc from targets for removal
    to_remove = installed - bad_pkgs

    # Skip purging if there is no packages which needs to be removed
    if not to_remove:
        if not bare:
            click.echo("Found 0 installed package, skip purging.")
            click.echo(crayons.green("Environment now purged and fresh!"))
        return installed

    if not bare:
        click.echo(
            fix_utf8("Found {0} installed package(s), purging…".format(len(to_remove)))
        )

    command = "{0} uninstall {1} -y".format(
        escape_grouped_arguments(which_pip(allow_global=allow_global)),
        " ".join(to_remove),
    )
    if environments.is_verbose():
        click.echo("$ {0}".format(command))
    c = delegator.run(command)
    if c.return_code != 0:
        raise exceptions.UninstallError(installed, command, c.out + c.err, c.return_code)
    if not bare:
        click.echo(crayons.blue(c.out))
        click.echo(crayons.green("Environment now purged and fresh!"))
    return installed


def do_init(
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
    from .environments import (
        PIPENV_VIRTUALENV, PIPENV_DEFAULT_PYTHON_VERSION, PIPENV_PYTHON, PIPENV_USE_SYSTEM
    )
    python = None
    if PIPENV_PYTHON is not None:
        python = PIPENV_PYTHON
    elif PIPENV_DEFAULT_PYTHON_VERSION is not None:
        python = PIPENV_DEFAULT_PYTHON_VERSION

    if not system and not PIPENV_USE_SYSTEM:
        if not project.virtualenv_exists:
            try:
                do_create_virtualenv(python=python, three=None, pypi_mirror=pypi_mirror)
            except KeyboardInterrupt:
                cleanup_virtualenv(bare=False)
                sys.exit(1)
    # Ensure the Pipfile exists.
    if not deploy:
        ensure_pipfile(system=system)
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
                        "Your Pipfile.lock ({0}) is out of date. Expected: ({1}).".format(
                            old_hash[-6:], new_hash[-6:]
                        )
                    )
                )
                raise exceptions.DeployException
                sys.exit(1)
            elif (system or allow_global) and not (PIPENV_VIRTUALENV):
                click.echo(
                    crayons.red(fix_utf8(
                        "Pipfile.lock ({0}) out of date, but installation "
                        "uses {1}… re-building lockfile must happen in "
                        "isolation. Please rebuild lockfile in a virtualenv. "
                        "Continuing anyway…".format(
                            crayons.white(old_hash[-6:]), crayons.white("--system")
                        )),
                        bold=True,
                    ),
                    err=True,
                )
            else:
                if old_hash:
                    msg = fix_utf8("Pipfile.lock ({0}) out of date, updating to ({1})…")
                else:
                    msg = fix_utf8("Pipfile.lock is corrupted, replaced with ({1})…")
                click.echo(
                    crayons.red(msg.format(old_hash[-6:], new_hash[-6:]), bold=True),
                    err=True,
                )
                do_lock(
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
        if (system or allow_global) and not (PIPENV_VIRTUALENV):
            raise exceptions.PipenvOptionsError(
                "--system",
                "--system is intended to be used for Pipfile installation, "
                "not installation of specific packages. Aborting.\n"
                "See also: --deploy flag."
            )
        else:
            click.echo(
                crayons.normal(fix_utf8("Pipfile.lock not found, creating…"), bold=True),
                err=True,
            )
            do_lock(
                system=system,
                pre=pre,
                keep_outdated=keep_outdated,
                write=True,
                pypi_mirror=pypi_mirror,
            )
    do_install_dependencies(
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
            "To activate this project's virtualenv, run {0}.\n"
            "Alternatively, run a command "
            "inside the virtualenv with {1}.".format(
                crayons.red("pipenv shell"), crayons.red("pipenv run")
            )
        )


def get_pip_args(
    pre=False,  # type: bool
    verbose=False,  # type: bool,
    upgrade=False,  # type: bool,
    require_hashes=False,  # type: bool,
    no_build_isolation=False,  # type: bool,
    no_use_pep517=False,  # type: bool,
    no_deps=False,  # type: bool,
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
            "--exists-action={0}".format(PIP_EXISTS_ACTION or "i")
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
    return list(vistir.misc.dedup(arg_set))


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
            requirement.line_instance._wheel_kwargs.update({
                "src_dir": src_dir
            })
        requirement.line_instance.vcsrepo
        line = requirement.line_instance.line
        if requirement.line_instance.markers:
            line = '{0}; {1}'.format(line, requirement.line_instance.markers)
            if not format_for_file:
                line = '"{0}"'.format(line)
        if requirement.editable:
            if not format_for_file:
                return ["-e", line]
            return '-e {0}'.format(line)
        if not format_for_file:
            return [line]
        return line
    return requirement.as_line(include_hashes=include_hashes, as_list=not format_for_file)


def write_requirement_to_file(
    requirement,  # type: Requirement
    requirements_dir=None,  # type: Optional[str]
    src_dir=None,  # type: Optional[str]
    include_hashes=True  # type: bool
):
    # type: (...) -> str
    if not requirements_dir:
        requirements_dir = vistir.path.create_tracked_tempdir(
            prefix="pipenv", suffix="requirements")
    line = requirement.line_instance.get_line(
        with_prefix=True, with_hashes=include_hashes, with_markers=True, as_list=False
    )

    f = vistir.compat.NamedTemporaryFile(
        prefix="pipenv-", suffix="-requirement.txt", dir=requirements_dir,
        delete=False
    )
    if environments.is_verbose():
        click.echo(
            "Writing supplied requirement line to temporary file: {0!r}".format(line),
            err=True
        )
    f.write(vistir.misc.to_bytes(line))
    r = f.name
    f.close()
    return r


def pip_install(
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
    use_pep517=True
):
    piplogger = logging.getLogger("pipenv.patched.notpip._internal.commands.install")
    src_dir = None
    if not trusted_hosts:
        trusted_hosts = []

    trusted_hosts.extend(os.environ.get("PIP_TRUSTED_HOSTS", []))
    if not allow_global:
        src_dir = os.getenv("PIP_SRC", os.getenv("PIP_SRC_DIR", project.virtualenv_src_location))
    else:
        src_dir = os.getenv("PIP_SRC", os.getenv("PIP_SRC_DIR"))
    if requirement:
        if requirement.editable or not requirement.hashes:
            ignore_hashes = True
        elif not (requirement.is_vcs or requirement.editable or requirement.vcs):
            ignore_hashes = False
    line = None
    # Try installing for each source in project.sources.
    if not index and requirement.index:
        index = requirement.index
    if index and not extra_indexes:
        extra_indexes = list(project.sources)
    if requirement and requirement.vcs or requirement.editable:
        requirement.index = None
        # Install dependencies when a package is a non-editable VCS dependency.
        # Don't specify a source directory when using --system.
        if not requirement.editable and no_deps is not True:
            # Leave this off becauase old lockfiles don't have all deps included
            # TODO: When can it be turned back on?
            no_deps = False
        elif requirement.editable and no_deps is None:
            no_deps = True

    r = write_requirement_to_file(
        requirement, requirements_dir=requirements_dir, src_dir=src_dir,
        include_hashes=not ignore_hashes
    )
    sources = get_source_list(
        index, extra_indexes=extra_indexes, trusted_hosts=trusted_hosts,
        pypi_mirror=pypi_mirror
    )
    if r:
        with io.open(r, "r") as fh:
            if "--hash" not in fh.read():
                ignore_hashes = True
    if environments.is_verbose():
        piplogger.setLevel(logging.WARN)
        if requirement:
            click.echo(
                crayons.normal("Installing {0!r}".format(requirement.name), bold=True),
                err=True,
            )

    pip_command = [which_pip(allow_global=allow_global), "install"]
    pip_args = get_pip_args(
        pre=pre, verbose=environments.is_verbose(), upgrade=True,
        selective_upgrade=selective_upgrade, no_use_pep517=not use_pep517,
        no_deps=no_deps, require_hashes=not ignore_hashes,
    )
    pip_command.extend(pip_args)
    if r:
        pip_command.extend(["-r", vistir.path.normalize_path(r)])
    elif line:
        pip_command.extend(line)
    pip_command.extend(prepare_pip_source_args(sources))
    if environments.is_verbose():
        click.echo("$ {0}".format(pip_command), err=True)
    cache_dir = vistir.compat.Path(PIPENV_CACHE_DIR)
    DEFAULT_EXISTS_ACTION = "w"
    if selective_upgrade:
        DEFAULT_EXISTS_ACTION = "i"
    exists_action = vistir.misc.fs_str(PIP_EXISTS_ACTION or DEFAULT_EXISTS_ACTION)
    pip_config = {
        "PIP_CACHE_DIR": vistir.misc.fs_str(cache_dir.as_posix()),
        "PIP_WHEEL_DIR": vistir.misc.fs_str(cache_dir.joinpath("wheels").as_posix()),
        "PIP_DESTINATION_DIR": vistir.misc.fs_str(
            cache_dir.joinpath("pkgs").as_posix()
        ),
        "PIP_EXISTS_ACTION": exists_action,
        "PATH": vistir.misc.fs_str(os.environ.get("PATH")),
    }
    if src_dir:
        if environments.is_verbose():
            click.echo("Using source directory: {0!r}".format(src_dir), err=True)
        pip_config.update(
            {"PIP_SRC": vistir.misc.fs_str(src_dir)}
        )
    cmd = Script.parse(pip_command)
    pip_command = cmd.cmdify()
    c = None
    c = delegator.run(pip_command, block=block, env=pip_config)
    c.env = pip_config
    return c


def pip_download(package_name):
    cache_dir = vistir.compat.Path(PIPENV_CACHE_DIR)
    pip_config = {
        "PIP_CACHE_DIR": vistir.misc.fs_str(cache_dir.as_posix()),
        "PIP_WHEEL_DIR": vistir.misc.fs_str(cache_dir.joinpath("wheels").as_posix()),
        "PIP_DESTINATION_DIR": vistir.misc.fs_str(
            cache_dir.joinpath("pkgs").as_posix()
        ),
    }
    for source in project.sources:
        cmd = '{0} download "{1}" -i {2} -d {3}'.format(
            escape_grouped_arguments(which_pip()),
            package_name,
            source["url"],
            project.download_location,
        )
        c = delegator.run(cmd, env=pip_config)
        if c.return_code == 0:
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
    if not isinstance(command, six.string_types):
        raise TypeError("Provided command must be a string, received {0!r}".format(command))
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


def which_pip(allow_global=False):
    """Returns the location of virtualenv-installed pip."""

    location = None
    if "VIRTUAL_ENV" in os.environ:
        location = os.environ["VIRTUAL_ENV"]
    if allow_global:
        if location:
            pip = which("pip", location=location)
            if pip:
                return pip

        for p in ("pip", "pip3", "pip2"):
            where = system_which(p)
            if where:
                return where

    pip = which("pip")
    if not pip:
        pip = fallback_which("pip", allow_global=allow_global, location=location)
    return pip


def system_which(command, mult=False):
    """Emulates the system's which. Returns None if not found."""
    _which = "which -a" if not os.name == "nt" else "where"
    os.environ.update({
        vistir.compat.fs_str(k): vistir.compat.fs_str(val)
        for k, val in os.environ.items()
    })
    result = None
    try:
        c = delegator.run("{0} {1}".format(_which, command))
        try:
            # Which Not found…
            if c.return_code == 127:
                click.echo(
                    "{}: the {} system utility is required for Pipenv to find Python installations properly."
                    "\n  Please install it.".format(
                        crayons.red("Warning", bold=True), crayons.red(_which)
                    ),
                    err=True,
                )
            assert c.return_code == 0
        except AssertionError:
            result = fallback_which(command, allow_global=True)
    except TypeError:
        if not result:
            result = fallback_which(command, allow_global=True)
    else:
        if not result:
            result = next(iter([c.out, c.err]), "").split("\n")
            result = next(iter(result)) if not mult else result
            return result
        if not result:
            result = fallback_which(command, allow_global=True)
    result = [result] if mult else result
    return result


def format_help(help):
    """Formats the help string."""
    help = help.replace("Options:", str(crayons.normal("Options:", bold=True)))
    help = help.replace(
        "Usage: pipenv", str("Usage: {0}".format(crayons.normal("pipenv", bold=True)))
    )
    help = help.replace("  check", str(crayons.red("  check", bold=True)))
    help = help.replace("  clean", str(crayons.red("  clean", bold=True)))
    help = help.replace("  graph", str(crayons.red("  graph", bold=True)))
    help = help.replace("  install", str(crayons.magenta("  install", bold=True)))
    help = help.replace("  lock", str(crayons.green("  lock", bold=True)))
    help = help.replace("  open", str(crayons.red("  open", bold=True)))
    help = help.replace("  run", str(crayons.yellow("  run", bold=True)))
    help = help.replace("  shell", str(crayons.yellow("  shell", bold=True)))
    help = help.replace("  sync", str(crayons.green("  sync", bold=True)))
    help = help.replace("  uninstall", str(crayons.magenta("  uninstall", bold=True)))
    help = help.replace("  update", str(crayons.green("  update", bold=True)))
    additional_help = """
Usage Examples:
   Create a new project using Python 3.7, specifically:
   $ {1}

   Remove project virtualenv (inferred from current directory):
   $ {9}

   Install all dependencies for a project (including dev):
   $ {2}

   Create a lockfile containing pre-releases:
   $ {6}

   Show a graph of your installed dependencies:
   $ {4}

   Check your installed dependencies for security vulnerabilities:
   $ {7}

   Install a local setup.py into your virtual environment/Pipfile:
   $ {5}

   Use a lower-level pip command:
   $ {8}

Commands:""".format(
        crayons.red("pipenv --three"),
        crayons.red("pipenv --python 3.7"),
        crayons.red("pipenv install --dev"),
        crayons.red("pipenv lock"),
        crayons.red("pipenv graph"),
        crayons.red("pipenv install -e ."),
        crayons.red("pipenv lock --pre"),
        crayons.red("pipenv check"),
        crayons.red("pipenv run pip freeze"),
        crayons.red("pipenv --rm"),
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

    out = "\n".join([l for l in gen(out)])
    return out


def warn_in_virtualenv():
    # Only warn if pipenv isn't already active.
    if environments.is_in_virtualenv() and not environments.is_quiet():
        click.echo(
            "{0}: Pipenv found itself running within a virtual environment, "
            "so it will automatically use that environment, instead of "
            "creating its own for any project. You can set "
            "{1} to force pipenv to ignore that environment and create "
            "its own instead. You can set {2} to suppress this "
            "warning.".format(
                crayons.green("Courtesy Notice"),
                crayons.normal("PIPENV_IGNORE_VIRTUALENVS=1", bold=True),
                crayons.normal("PIPENV_VERBOSITY=-1", bold=True),
            ),
            err=True,
        )


def ensure_lockfile(keep_outdated=False, pypi_mirror=None):
    """Ensures that the lockfile is up-to-date."""
    if not keep_outdated:
        keep_outdated = project.settings.get("keep_outdated")
    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if project.lockfile_exists:
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            click.echo(
                crayons.red(
                    fix_utf8("Pipfile.lock ({0}) out of date, updating to ({1})…".format(
                        old_hash[-6:], new_hash[-6:]
                    )),
                    bold=True,
                ),
                err=True,
            )
            do_lock(keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)
    else:
        do_lock(keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)


def do_py(system=False):
    if not project.virtualenv_exists:
        click.echo(
            "{}({}){}".format(
                crayons.red("No virtualenv has been created for this project "),
                crayons.white(project.project_directory, bold=True),
                crayons.red(" yet!")
            ),
            err=True,
        )
        return

    try:
        click.echo(which("python", allow_global=system))
    except AttributeError:
        click.echo(crayons.red("No project found!"))


def do_outdated(pypi_mirror=None, pre=False, clear=False):
    # TODO: Allow --skip-lock here?
    from .vendor.requirementslib.models.requirements import Requirement
    from .vendor.requirementslib.models.utils import get_version
    from .vendor.packaging.utils import canonicalize_name
    from .vendor.vistir.compat import Mapping
    from collections import namedtuple

    packages = {}
    package_info = namedtuple("PackageInfo", ["name", "installed", "available"])

    installed_packages = project.environment.get_installed_packages()
    outdated_packages = {
        canonicalize_name(pkg.project_name): package_info
        (pkg.project_name, pkg.parsed_version, pkg.latest_version)
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
    lockfile = do_lock(clear=clear, pre=pre, write=False, pypi_mirror=pypi_mirror)
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
                required = " {0} required".format(rdeps["required"])
            if version:
                pipfile_version_text = " ({0} set in Pipfile)".format(version)
            else:
                pipfile_version_text = " (Unpinned in Pipfile)"
        click.echo(
            crayons.yellow(
                "Skipped Update of Package {0!s}: {1!s} installed,{2!s}{3!s}, "
                "{4!s} available.".format(
                    package, old_version, required, pipfile_version_text, new_version
                )
            ), err=True
        )
    if not outdated:
        click.echo(crayons.green("All packages are up to date!", bold=True))
        sys.exit(0)
    for package, new_version, old_version in outdated:
        click.echo(
            "Package {0!r} out-of-date: {1!r} installed, {2!r} available.".format(
                package, old_version, new_version
            )
        )
    sys.exit(bool(outdated))


def do_install(
    packages=False,
    editable_packages=False,
    index_url=False,
    extra_index_url=False,
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
    code=False,
    deploy=False,
    keep_outdated=False,
    selective_upgrade=False,
    site_packages=None,
):
    from .environments import PIPENV_VIRTUALENV, PIPENV_USE_SYSTEM
    from .vendor.pip_shims.shims import PipError

    requirements_directory = vistir.path.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    warnings.filterwarnings("default", category=vistir.compat.ResourceWarning)
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
    if not project.pipfile_exists and not (package_args or dev) and not code:
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
    if (system and package_args) and not (PIPENV_VIRTUALENV):
        raise exceptions.SystemUsageError
    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True
    # Check if the file is remote or not
    if remote:
        click.echo(
            crayons.normal(
                fix_utf8("Remote requirements file provided! Downloading…"), bold=True
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
            download_file(requirements_url, temp_reqs)
        except IOError:
            fd.close()
            os.unlink(temp_reqs)
            click.echo(
                crayons.red(
                    u"Unable to find requirements file at {0}.".format(
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
                fix_utf8("Requirements file provided! Importing into Pipfile…"), bold=True
            ),
            err=True,
        )
        try:
            import_requirements(r=project.path_to(requirementstxt), dev=dev)
        except (UnicodeDecodeError, PipError) as e:
            # Don't print the temp file path if remote since it will be deleted.
            req_path = requirements_url if remote else project.path_to(requirementstxt)
            error = (
                u"Unexpected syntax in {0}. Are you sure this is a "
                "requirements.txt style file?".format(req_path)
            )
            traceback = e
        except AssertionError as e:
            error = (
                u"Requirements file doesn't appear to exist. Please ensure the file exists in your "
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
                click.echo(crayons.blue(str(traceback)), err=True)
                sys.exit(1)
    if code:
        click.echo(
            crayons.normal(fix_utf8("Discovering imports from local codebase…"), bold=True)
        )
        for req in import_from_code(code):
            click.echo("  Found {0}!".format(crayons.green(req)))
            project.add_package_to_pipfile(req)
    # Allow more than one package to be provided.
    package_args = [p for p in packages] + [
        "-e {0}".format(pkg) for pkg in editable_packages
    ]
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
            keep_outdated=keep_outdated
        )

    # This is for if the user passed in dependencies, then we want to make sure we
    else:
        from .vendor.requirementslib.models.requirements import Requirement

        # make a tuple of (display_name, entry)
        pkg_list = packages + ['-e {0}'.format(pkg) for pkg in editable_packages]
        if not system and not project.virtualenv_exists:
            do_init(
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
                    fix_utf8("Installing {0}…".format(crayons.green(pkg_line, bold=True))),
                    bold=True,
                )
            )
            # pip install:
            with vistir.contextmanagers.temp_environ(), create_spinner("Installing...") as sp:
                if not system:
                    os.environ["PIP_USER"] = vistir.compat.fs_str("0")
                    if "PYTHONHOME" in os.environ:
                        del os.environ["PYTHONHOME"]
                sp.text = "Resolving {0}...".format(pkg_line)
                try:
                    pkg_requirement = Requirement.from_line(pkg_line)
                except ValueError as e:
                    sp.write_err(vistir.compat.fs_str("{0}: {1}".format(crayons.red("WARNING"), e)))
                    sp.red.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format("Installation Failed"))
                    sys.exit(1)
                if index_url:
                    pkg_requirement.index = index_url
                no_deps = False
                sp.text = "Installing..."
                try:
                    sp.text = "Installing {0}...".format(pkg_requirement.name)
                    if environments.is_verbose():
                        sp.hide_and_write("Installing package: {0}".format(pkg_requirement.as_line(include_hashes=False)))
                    c = pip_install(
                        pkg_requirement,
                        ignore_hashes=True,
                        allow_global=system,
                        selective_upgrade=selective_upgrade,
                        no_deps=no_deps,
                        pre=pre,
                        requirements_dir=requirements_directory,
                        index=index_url,
                        extra_indexes=extra_index_url,
                        pypi_mirror=pypi_mirror,
                    )
                    if not c.ok:
                        sp.write_err(
                            u"{0} An error occurred while installing {1}!".format(
                                crayons.red(u"Error: ", bold=True), crayons.green(pkg_line)
                            ),
                        )
                        sp.write_err(
                            vistir.compat.fs_str(u"Error text: {0}".format(c.out))
                        )
                        sp.write_err(crayons.blue(vistir.compat.fs_str(format_pip_error(c.err))))
                        if environments.is_verbose():
                            sp.write_err(crayons.blue(vistir.compat.fs_str(format_pip_output(c.out))))
                        if "setup.py egg_info" in c.err:
                            sp.write_err(vistir.compat.fs_str(
                                "This is likely caused by a bug in {0}. "
                                "Report this to its maintainers.".format(
                                    crayons.green(pkg_requirement.name)
                                )
                            ))
                        sp.red.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format("Installation Failed"))
                        sys.exit(1)
                except (ValueError, RuntimeError) as e:
                    sp.write_err(vistir.compat.fs_str(
                        "{0}: {1}".format(crayons.red("WARNING"), e),
                    ))
                    sp.red.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format(
                        "Installation Failed",
                    ))
                    sys.exit(1)
                # Warn if --editable wasn't passed.
                if pkg_requirement.is_vcs and not pkg_requirement.editable and not PIPENV_RESOLVE_VCS:
                    sp.write_err(
                        "{0}: You installed a VCS dependency in non-editable mode. "
                        "This will work fine, but sub-dependencies will not be resolved by {1}."
                        "\n  To enable this sub-dependency functionality, specify that this dependency is editable."
                        "".format(
                            crayons.red("Warning", bold=True),
                            crayons.red("$ pipenv lock"),
                        )
                    )
                sp.write(vistir.compat.fs_str(
                    u"{0} {1} {2} {3}{4}".format(
                        crayons.normal(u"Adding", bold=True),
                        crayons.green(u"{0}".format(pkg_requirement.name), bold=True),
                        crayons.normal(u"to Pipfile's", bold=True),
                        crayons.red(u"[dev-packages]" if dev else u"[packages]", bold=True),
                        crayons.normal(fix_utf8("…"), bold=True),
                    )
                ))
                # Add the package to the Pipfile.
                try:
                    project.add_package_to_pipfile(pkg_requirement, dev)
                except ValueError:
                    import traceback
                    sp.write_err(
                        "{0} {1}".format(
                            crayons.red("Error:", bold=True), traceback.format_exc()
                        )
                    )
                    sp.fail(environments.PIPENV_SPINNER_FAIL_TEXT.format(
                        "Failed adding package to Pipfile"
                    ))
                sp.ok(environments.PIPENV_SPINNER_OK_TEXT.format("Installation Succeeded"))
            # Update project settings with pre preference.
            if pre:
                project.update_settings({"allow_prereleases": pre})
        if pip_shims_module:
            os.environ["PIP_SHIMS_BASE_MODULE"] = pip_shims_module
        do_init(
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
    ctx=None
):
    from .environments import PIPENV_USE_SYSTEM
    from .vendor.requirementslib.models.requirements import Requirement
    from .vendor.packaging.utils import canonicalize_name

    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True
    # Ensure that virtualenv is available.
    # TODO: We probably shouldn't ensure a project exists if the outcome will be to just
    # install things in order to remove them... maybe tell the user to install first?
    ensure_project(three=three, python=python, pypi_mirror=pypi_mirror)
    # Un-install all dependencies, if --all was provided.
    if not any([packages, editable_packages, all_dev, all]):
        raise exceptions.MissingParameter(
            crayons.red("No package provided!"),
            ctx=ctx, param_type="parameter",
        )
    editable_pkgs = [
        Requirement.from_line("-e {0}".format(p)).name for p in editable_packages if p
    ]
    packages = packages + editable_pkgs
    package_names = [p for p in packages if p]
    package_map = {
        canonicalize_name(p): p for p in packages if p
    }
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
                    "No {0} to uninstall.".format(crayons.red("[dev-packages]")),
                    bold=True,
                )
            )
            return
        click.echo(
            crayons.normal(
                fix_utf8("Un-installing {0}…".format(crayons.red("[dev-packages]"))), bold=True
            )
        )
        package_names = project_pkg_names["dev"]

    # Remove known "bad packages" from the list.
    bad_pkgs = get_canonical_names(BAD_PACKAGES)
    ignored_packages = bad_pkgs & set(list(package_map.keys()))
    for ignored_pkg in ignored_packages:
        if environments.is_verbose():
            click.echo("Ignoring {0}.".format(ignored_pkg), err=True)
        pkg_name_index = package_names.index(package_map[ignored_pkg])
        del package_names[pkg_name_index]

    used_packages = project_pkg_names["combined"] & installed_package_names
    failure = False
    packages_to_remove = set()
    if all:
        click.echo(
            crayons.normal(
                fix_utf8("Un-installing all {0} and {1}…".format(
                    crayons.red("[dev-packages]"),
                    crayons.red("[packages]"),
                )), bold=True
            )
        )
        do_purge(bare=False, allow_global=system)
        sys.exit(0)
    if all_dev:
        package_names = project_pkg_names["dev"]
    else:
        package_names = set([pkg_name for pkg_name in package_names])
    selected_pkg_map = {
        canonicalize_name(p): p for p in package_names
    }
    packages_to_remove = [
        p for normalized, p in selected_pkg_map.items()
        if normalized in (used_packages - bad_pkgs)
    ]
    pip_path = None
    for normalized, package_name in selected_pkg_map.items():
        click.echo(
            crayons.white(
                fix_utf8("Uninstalling {0}…".format(package_name)), bold=True
            )
        )
        # Uninstall the package.
        if package_name in packages_to_remove:
            with project.environment.activated():
                if pip_path is None:
                    pip_path = which_pip(allow_global=system)
                cmd = [pip_path, "uninstall", package_name, "-y"]
                c = run_command(cmd)
                click.echo(crayons.blue(c.out))
                if c.return_code != 0:
                    failure = True
        if not failure and pipfile_remove:
            in_packages = project.get_package_name_in_pipfile(package_name, dev=False)
            in_dev_packages = project.get_package_name_in_pipfile(
                package_name, dev=True
            )
            if normalized in lockfile_packages:
                click.echo("{0} {1} {2} {3}".format(
                    crayons.blue("Removing"),
                    crayons.green(package_name),
                    crayons.blue("from"),
                    crayons.white(fix_utf8("Pipfile.lock…")))
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
                    "No package {0} to remove from Pipfile.".format(
                        crayons.green(package_name)
                    )
                )
                continue

            click.echo(
                fix_utf8("Removing {0} from Pipfile…".format(crayons.green(package_name)))
            )
            # Remove package from both packages and dev-packages.
            if in_dev_packages:
                project.remove_package_from_pipfile(package_name, dev=True)
            if in_packages:
                project.remove_package_from_pipfile(package_name, dev=False)
    if lock:
        do_lock(system=system, keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)
    sys.exit(int(failure))


def do_shell(three=None, python=False, fancy=False, shell_args=None, pypi_mirror=None):
    # Ensure that virtualenv is available.
    ensure_project(
        three=three, python=python, validate=False, pypi_mirror=pypi_mirror,
    )

    # Support shell compatibility mode.
    if PIPENV_SHELL_FANCY:
        fancy = True

    from .shells import choose_shell

    shell = choose_shell()
    click.echo(fix_utf8("Launching subshell in virtual environment…"), err=True)

    fork_args = (
        project.virtualenv_location,
        project.project_directory,
        shell_args,
    )

    # Set an environment variable, so we know we're in the environment.
    # Only set PIPENV_ACTIVE after finishing reading virtualenv_location
    # otherwise its value will be changed
    os.environ["PIPENV_ACTIVE"] = vistir.misc.fs_str("1")

    os.environ.pop("PIP_SHIMS_BASE_MODULE", None)

    if fancy:
        shell.fork(*fork_args)
        return

    try:
        shell.fork_compat(*fork_args)
    except (AttributeError, ImportError):
        click.echo(fix_utf8(
            "Compatibility mode not supported. "
            "Trying to continue as well-configured shell…"),
            err=True,
        )
        shell.fork(*fork_args)


def _inline_activate_virtualenv():
    try:
        activate_this = which("activate_this.py")
        if not activate_this or not os.path.exists(activate_this):
            raise exceptions.VirtualenvActivationException()
        with open(activate_this) as f:
            code = compile(f.read(), activate_this, "exec")
            exec(code, dict(__file__=activate_this))
    # Catch all errors, just in case.
    except Exception:
        click.echo(
            u"{0}: There was an unexpected error while activating your "
            u"virtualenv. Continuing anyway...".format(
                crayons.red("Warning", bold=True)
            ),
            err=True,
        )


def _inline_activate_venv():
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


def inline_activate_virtual_environment():
    root = project.virtualenv_location
    if os.path.exists(os.path.join(root, "pyvenv.cfg")):
        _inline_activate_venv()
    else:
        _inline_activate_virtualenv()
    if "VIRTUAL_ENV" not in os.environ:
        os.environ["VIRTUAL_ENV"] = vistir.misc.fs_str(root)


def _launch_windows_subprocess(script):
    import subprocess

    command = system_which(script.command)
    options = {"universal_newlines": True}

    # Command not found, maybe this is a shell built-in?
    if not command:
        return subprocess.Popen(script.cmdify(), shell=True, **options)

    # Try to use CreateProcess directly if possible. Specifically catch
    # Windows error 193 "Command is not a valid Win32 application" to handle
    # a "command" that is non-executable. See pypa/pipenv#2727.
    try:
        return subprocess.Popen([command] + script.args, **options)
    except WindowsError as e:
        if e.winerror != 193:
            raise

    # Try shell mode to use Windows's file association for file launch.
    return subprocess.Popen(script.cmdify(), shell=True, **options)


def do_run_nt(script):
    p = _launch_windows_subprocess(script)
    p.communicate()
    sys.exit(p.returncode)


def do_run_posix(script, command):
    command_path = system_which(script.command)
    if not command_path:
        if project.has_script(command):
            click.echo(
                "{0}: the command {1} (from {2}) could not be found within {3}."
                "".format(
                    crayons.red("Error", bold=True),
                    crayons.red(script.command),
                    crayons.normal(command, bold=True),
                    crayons.normal("PATH", bold=True),
                ),
                err=True,
            )
        else:
            click.echo(
                "{0}: the command {1} could not be found within {2} or Pipfile's {3}."
                "".format(
                    crayons.red("Error", bold=True),
                    crayons.red(command),
                    crayons.normal("PATH", bold=True),
                    crayons.normal("[scripts]", bold=True),
                ),
                err=True,
            )
        sys.exit(1)
    os.execl(
        command_path, command_path, *[os.path.expandvars(arg) for arg in script.args]
    )


def do_run(command, args, three=None, python=False, pypi_mirror=None):
    """Attempt to run command either pulling from project or interpreting as executable.

    Args are appended to the command in [scripts] section of project if found.
    """
    from .cmdparse import ScriptEmptyError

    # Ensure that virtualenv is available.
    ensure_project(
        three=three, python=python, validate=False, pypi_mirror=pypi_mirror,
    )

    load_dot_env()

    previous_pip_shims_module = os.environ.pop("PIP_SHIMS_BASE_MODULE", None)

    # Activate virtualenv under the current interpreter's environment
    inline_activate_virtual_environment()

    # Set an environment variable, so we know we're in the environment.
    # Only set PIPENV_ACTIVE after finishing reading virtualenv_location
    # such as in inline_activate_virtual_environment
    # otherwise its value will be changed
    previous_pipenv_active_value = os.environ.get("PIPENV_ACTIVE")
    os.environ["PIPENV_ACTIVE"] = vistir.misc.fs_str("1")

    os.environ.pop("PIP_SHIMS_BASE_MODULE", None)

    try:
        script = project.build_script(command, args)
        cmd_string = ' '.join([script.command] + script.args)
        if environments.is_verbose():
            click.echo(crayons.normal("$ {0}".format(cmd_string)), err=True)
    except ScriptEmptyError:
        click.echo("Can't run script {0!r}-it's empty?", err=True)
    run_args = [script]
    run_kwargs = {}
    if os.name == "nt":
        run_fn = do_run_nt
    else:
        run_fn = do_run_posix
        run_kwargs = {"command": command}
    try:
        run_fn(*run_args, **run_kwargs)
    finally:
        os.environ.pop("PIPENV_ACTIVE", None)
        if previous_pipenv_active_value is not None:
            os.environ["PIPENV_ACTIVE"] = previous_pipenv_active_value
        if previous_pip_shims_module is not None:
            os.environ["PIP_SHIMS_BASE_MODULE"] = previous_pip_shims_module


def do_check(
    three=None,
    python=False,
    system=False,
    unused=False,
    db=False,
    ignore=None,
    output="default",
    key=None,
    quiet=False,
    args=None,
    pypi_mirror=None
):
    from pipenv.vendor.vistir.compat import JSONDecodeError
    from pipenv.vendor.first import first

    if not system:
        # Ensure that virtualenv is available.
        ensure_project(
            three=three,
            python=python,
            validate=False,
            warn=False,
            pypi_mirror=pypi_mirror,
        )
    if not args:
        args = []
    if unused:
        deps_required = [k.lower() for k in project.packages.keys()]
        deps_needed = [k.lower() for k in import_from_code(unused)]
        for dep in deps_needed:
            try:
                deps_required.remove(dep)
            except ValueError:
                pass
        if deps_required:
            if not quiet and not environments.is_quiet():
                click.echo(
                    crayons.normal(
                        "The following dependencies appear unused, and may be safe for removal:"
                    )
                )
                for dep in deps_required:
                    click.echo("  - {0}".format(crayons.green(dep)))
                sys.exit(1)
        else:
            sys.exit(0)
    if not quiet and not environments.is_quiet():
        click.echo(crayons.normal(decode_for_output("Checking PEP 508 requirements…"), bold=True))
    pep508checker_path = pep508checker.__file__.rstrip("cdo")
    safety_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "patched", "safety"
    )
    if not system:
        python = which("python")
    else:
        python = first(system_which(p) for p in ("python", "python3", "python2"))
    if not python:
        click.echo(crayons.red("The Python interpreter can't be found."), err=True)
        sys.exit(1)
    _cmd = [vistir.compat.Path(python).as_posix()]
    # Run the PEP 508 checker in the virtualenv.
    cmd = _cmd + [vistir.compat.Path(pep508checker_path).as_posix()]
    c = run_command(cmd)
    if c.return_code is not None:
        try:
            results = simplejson.loads(c.out.strip())
        except JSONDecodeError:
            click.echo("{0}\n{1}\n{2}".format(
                crayons.white(decode_for_output("Failed parsing pep508 results: "), bold=True),
                c.out.strip(),
                c.err.strip()
            ))
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
                    "Specifier {0} does not match {1} ({2})."
                    "".format(
                        crayons.green(marker),
                        crayons.blue(specifier),
                        crayons.red(results[marker]),
                    ),
                    err=True,
                )
    if failed:
        click.echo(crayons.red("Failed!"), err=True)
        sys.exit(1)
    else:
        if not quiet and not environments.is_quiet():
            click.echo(crayons.green("Passed!"))
    if not quiet and not environments.is_quiet():
        click.echo(crayons.normal(
            decode_for_output("Checking installed package safety…"), bold=True)
        )
    if ignore:
        if not isinstance(ignore, (tuple, list)):
            ignore = [ignore]
        ignored = [["--ignore", cve] for cve in ignore]
        if not quiet and not environments.is_quiet():
            click.echo(
                crayons.normal(
                    "Notice: Ignoring CVE(s) {0}".format(crayons.yellow(", ".join(ignore)))
                ),
                err=True,
            )
    else:
        ignored = []

    switch = output
    if output == "default":
        switch = "json"

    cmd = _cmd + [safety_path, "check", "--{0}".format(switch)]
    if db:
        if not quiet and not environments.is_quiet():
            click.echo(crayons.normal("Using local database {}".format(db)))
        cmd.append("--db={0}".format(db))
    elif key or PIPENV_PYUP_API_KEY:
        cmd = cmd + ["--key={0}".format(key or PIPENV_PYUP_API_KEY)]
    if ignored:
        for cve in ignored:
            cmd += cve
    c = run_command(cmd, catch_exceptions=False)
    if output == "default":
        try:
            results = simplejson.loads(c.out)
        except (ValueError, JSONDecodeError):
            raise exceptions.JSONParseError(c.out, c.err)
        except Exception:
            raise exceptions.PipenvCmdError(c.cmd, c.out, c.err, c.return_code)
        for (package, resolved, installed, description, vuln) in results:
            click.echo(
                "{0}: {1} {2} resolved ({3} installed)!".format(
                    crayons.normal(vuln, bold=True),
                    crayons.green(package),
                    crayons.red(resolved, bold=False),
                    crayons.red(installed, bold=True),
                )
            )
            click.echo("{0}".format(description))
            click.echo()
        if c.ok:
            click.echo(crayons.green("All good!"))
            sys.exit(0)
        else:
            sys.exit(1)
    else:
        click.echo(c.out)
        sys.exit(c.return_code)


def do_graph(bare=False, json=False, json_tree=False, reverse=False):
    from pipenv.vendor.vistir.compat import JSONDecodeError
    import pipdeptree
    pipdeptree_path = pipdeptree.__file__.rstrip("cdo")
    try:
        python_path = which("python")
    except AttributeError:
        click.echo(
            u"{0}: {1}".format(
                crayons.red("Warning", bold=True),
                u"Unable to display currently-installed dependency graph information here. "
                u"Please run within a Pipenv project.",
            ),
            err=True,
        )
        sys.exit(1)
    except RuntimeError:
        pass
    else:
        python_path = vistir.compat.Path(python_path).as_posix()
        pipdeptree_path = vistir.compat.Path(pipdeptree_path).as_posix()

    if reverse and json:
        click.echo(
            u"{0}: {1}".format(
                crayons.red("Warning", bold=True),
                u"Using both --reverse and --json together is not supported. "
                u"Please select one of the two options.",
            ),
            err=True,
        )
        sys.exit(1)
    if reverse and json_tree:
        click.echo(
            u"{0}: {1}".format(
                crayons.red("Warning", bold=True),
                u"Using both --reverse and --json-tree together is not supported. "
                u"Please select one of the two options.",
            ),
            err=True,
        )
        sys.exit(1)
    if json and json_tree:
        click.echo(
            u"{0}: {1}".format(
                crayons.red("Warning", bold=True),
                u"Using both --json and --json-tree together is not supported. "
                u"Please select one of the two options.",
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
            u"{0}: No virtualenv has been created for this project yet! Consider "
            u"running {1} first to automatically generate one for you or see "
            u"{2} for further instructions.".format(
                crayons.red("Warning", bold=True),
                crayons.green("`pipenv install`"),
                crayons.green("`pipenv install --help`"),
            ),
            err=True,
        )
        sys.exit(1)
    cmd_args = [python_path, pipdeptree_path, flag, "-l"]
    c = run_command(cmd_args)
    # Run dep-tree.
    if not bare:
        if json:
            data = []
            try:
                parsed = simplejson.loads(c.out.strip())
            except JSONDecodeError:
                raise exceptions.JSONParseError(c.out, c.err)
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
                parsed = simplejson.loads(c.out.strip())
            except JSONDecodeError:
                raise exceptions.JSONParseError(c.out, c.err)
            else:
                data = traverse(parsed)
                click.echo(simplejson.dumps(data, indent=4))
                sys.exit(0)
        else:
            for line in c.out.strip().split("\n"):
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
        click.echo(c.out)
    if c.return_code != 0:
        click.echo(
            "{0} {1}".format(
                crayons.red("ERROR: ", bold=True),
                crayons.white("{0}".format(c.err, bold=True)),
            ),
            err=True,
        )
    # Return its return code.
    sys.exit(c.return_code)


def do_sync(
    ctx,
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
        three=three,
        python=python,
        validate=False,
        deploy=deploy,
        pypi_mirror=pypi_mirror,
    )

    # Install everything.
    requirements_dir = vistir.path.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    do_init(
        dev=dev,
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
    ctx, three=None, python=None, dry_run=False, bare=False, pypi_mirror=None,
    system=False
):
    # Ensure that virtualenv is available.
    from packaging.utils import canonicalize_name
    ensure_project(three=three, python=python, validate=False, pypi_mirror=pypi_mirror)
    ensure_lockfile(pypi_mirror=pypi_mirror)
    # Make sure that the virtualenv's site packages are configured correctly
    # otherwise we may end up removing from the global site packages directory
    installed_package_names = project.installed_package_names.copy()
    # Remove known "bad packages" from the list.
    for bad_package in BAD_PACKAGES:
        if canonicalize_name(bad_package) in installed_package_names:
            if environments.is_verbose():
                click.echo("Ignoring {0}.".format(bad_package), err=True)
            installed_package_names.remove(canonicalize_name(bad_package))
    # Intelligently detect if --dev should be used or not.
    locked_packages = {
        canonicalize_name(pkg) for pkg in project.lockfile_package_names["combined"]
    }
    for used_package in locked_packages:
        if used_package in installed_package_names:
            installed_package_names.remove(used_package)
    failure = False
    cmd = [which_pip(allow_global=system), "uninstall", "-y", "-qq"]
    for apparent_bad_package in installed_package_names:
        if dry_run and not bare:
            click.echo(apparent_bad_package)
        else:
            if not bare:
                click.echo(
                    crayons.white(
                        fix_utf8("Uninstalling {0}…".format(apparent_bad_package)), bold=True
                    )
                )
            # Uninstall the package.
            cmd = [which_pip(), "uninstall", apparent_bad_package, "-y"]
            c = run_command(cmd)
            if c.return_code != 0:
                failure = True
    sys.exit(int(failure))
