# -*- coding=utf-8 -*-
import contextlib
import logging
import os
import sys
import shutil
import time
import tempfile
import json as simplejson
import click
import click_completion
import crayons
import dotenv
import delegator
import pipfile
from blindspin import spinner
import vistir
import six

from .cmdparse import Script
from .project import Project, SourceNotFound
from .utils import (
    convert_deps_to_pip,
    is_required_version,
    proper_case,
    pep423_name,
    split_file,
    merge_deps,
    venv_resolve_deps,
    escape_grouped_arguments,
    python_version,
    find_windows_executable,
    prepare_pip_source_args,
    is_valid_url,
    is_pypi_url,
    create_mirror_source,
    download_file,
    is_pinned,
    is_star,
    rmtree,
    clean_resolved_dep,
    parse_indexes,
    escape_cmd
)
from . import environments, pep508checker, progress
from .environments import (
    PIPENV_COLORBLIND,
    PIPENV_NOSPIN,
    PIPENV_SHELL_FANCY,
    PIPENV_TIMEOUT,
    PIPENV_SKIP_VALIDATION,
    PIPENV_HIDE_EMOJIS,
    PIPENV_YES,
    PIPENV_DEFAULT_PYTHON_VERSION,
    PIPENV_MAX_SUBPROCESS,
    PIPENV_DONT_USE_PYENV,
    SESSION_IS_INTERACTIVE,
    PIPENV_CACHE_DIR,
)

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
click_completion.init()
# Disable colors, for the color blind and others who do not prefer colors.
if PIPENV_COLORBLIND:
    crayons.disable()
# Disable spinner, for cleaner build logs (the unworthy).
if PIPENV_NOSPIN:

    @contextlib.contextmanager  # noqa: F811
    def spinner():
        yield


def which(command, location=None, allow_global=False):
    if not allow_global and location is None:
        if project.virtualenv_exists:
            location = project.virtualenv_location
        else:
            location = os.environ.get("VIRTUAL_ENV", None)
    if not (location and os.path.exists(location)) and not allow_global:
        raise RuntimeError("location not created nor specified")
    if not allow_global:
        if os.name == "nt":
            p = find_windows_executable(os.path.join(location, "Scripts"), command)
        else:
            p = os.path.join(location, "bin", command)
    else:
        if command == "python":
            p = sys.executable
    if not os.path.exists(p):
        if command == "python":
            p = sys.executable or system_which("python")
        else:
            p = system_which(command)
    return p


project = Project(which=which)


def do_clear():
    click.echo(crayons.white("Clearing caches…", bold=True))
    try:
        from pip._internal import locations
    except ImportError:  # pip 9.
        from pip import locations

    try:
        shutil.rmtree(PIPENV_CACHE_DIR)
        shutil.rmtree(locations.USER_CACHE_DIR)
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
                crayons.normal("Loading .env environment variables…", bold=True),
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
        rmtree(project.virtualenv_location)
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
    from .patched.notpip._internal.req.req_file import parse_requirements

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
        for r in pipreqs.get_all_imports(path):
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
            click.echo(
                "{0}: --system is intended to be used for pre-existing Pipfile "
                "installation, not installation of specific packages. Aborting.".format(
                    crayons.red("Warning", bold=True)
                ),
                err=True,
            )
            sys.exit(1)
        # If there's a requirements file, but no Pipfile…
        if project.requirements_exists and not skip_requirements:
            click.echo(
                crayons.normal(
                    u"requirements.txt found, instead of Pipfile! Converting…",
                    bold=True,
                )
            )
            # Create a Pipfile…
            project.create_pipfile(python=python)
            with spinner():
                # Import requirements.txt.
                import_requirements()
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
                crayons.normal(u"Creating a Pipfile for this project…", bold=True),
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
    if not line:
        return None
    if os.path.isabs(line):
        return line
    from .vendor.pythonfinder import Finder

    finder = Finder(system=False, global_search=True)
    if (line.startswith("py ") or line.startswith("py.exe ")) and os.name == "nt":
        line = line.split(" ", 1)[1].lstrip("-")
    elif line.startswith("py"):
        python_entry = finder.which(line)
        if python_entry:
            return python_entry.path.as_posix()
        return None
    python_entry = finder.find_python_version(line)
    if not python_entry:
        python_entry = finder.which("python{0}".format(line))
    if python_entry:
        return python_entry.path.as_posix()
    return None


def ensure_python(three=None, python=None):
    # Support for the PIPENV_PYTHON environment variable.
    from .environments import PIPENV_PYTHON

    if PIPENV_PYTHON and python is False and three is None:
        python = PIPENV_PYTHON

    def abort():
        click.echo(
            "You can specify specific versions of Python with:\n  {0}".format(
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
    if not path_to_python and python is not None:
        # We need to install Python.
        click.echo(
            u"{0}: Python {1} {2}".format(
                crayons.red("Warning", bold=True),
                crayons.blue(python),
                u"was not found on your system…",
            ),
            err=True,
        )
        # Pyenv is installed
        from .vendor.pythonfinder.environment import PYENV_INSTALLED

        if not PYENV_INSTALLED:
            abort()
        else:
            if (not PIPENV_DONT_USE_PYENV) and (SESSION_IS_INTERACTIVE or PIPENV_YES):
                from .pyenv import Runner, PyenvError

                pyenv = Runner("pyenv")
                try:
                    version = pyenv.find_version_to_install(python)
                except ValueError:
                    abort()
                except PyenvError as e:
                    click.echo(u"Something went wrong…")
                    click.echo(crayons.blue(e.err), err=True)
                    abort()
                s = "{0} {1} {2}".format(
                    "Would you like us to install",
                    crayons.green("CPython {0}".format(version)),
                    "with pyenv?",
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
                            crayons.normal(u"with pyenv", bold=True),
                            crayons.normal(u"(this may take a few minutes)"),
                            crayons.normal(u"…", bold=True),
                        )
                    )
                    with spinner():
                        try:
                            c = pyenv.install(version)
                        except PyenvError as e:
                            click.echo(u"Something went wrong…")
                            click.echo(crayons.blue(e.err), err=True)
                        # Print the results, in a beautiful blue…
                        click.echo(crayons.blue(c.out), err=True)
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


def ensure_virtualenv(three=None, python=None, site_packages=False, pypi_mirror=None):
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
    elif (python) or (three is not None) or (site_packages is not False):
        USING_DEFAULT_PYTHON = False
        # Ensure python is installed before deleting existing virtual env
        ensure_python(three=three, python=python)
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
            crayons.normal(u"Removing existing virtualenv…", bold=True), err=True
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
    site_packages=False,
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
    if not project.pipfile_exists and not deploy:
        project.touch_pipfile()
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
                            crayons.blue(python_version(path_to_python)),
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
                        click.echo(crayons.red("Deploy aborted."), err=True)
                        sys.exit(1)
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
        location = project.pipfile_location
        # Shorten the virtual display of the path to the virtualenv.
        if not bare:
            location = shorten_path(location)
        if not location:
            click.echo(
                "No Pipfile present at project home. Consider running "
                "{0} first to automatically generate a Pipfile for you."
                "".format(crayons.green("`pipenv install`")),
                err=True,
            )
        elif not bare:
            click.echo(
                "Pipfile found at {0}.\n  Considering this to be the project home."
                "".format(crayons.green(location)),
                err=True,
            )
            pass
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


def do_install_dependencies(
    dev=False,
    only=False,
    bare=False,
    requirements=False,
    allow_global=False,
    ignore_hashes=False,
    skip_lock=False,
    concurrent=True,
    requirements_dir=None,
    pypi_mirror=False,
):
    """"Executes the install functionality.

    If requirements is True, simply spits out a requirements format to stdout.
    """
    from .vendor.requirementslib.models.requirements import Requirement

    def cleanup_procs(procs, concurrent):
        for c in procs:
            if concurrent:
                c.block()
            if "Ignoring" in c.out:
                click.echo(crayons.yellow(c.out.strip()))
            elif environments.is_verbose():
                click.echo(crayons.blue(c.out or c.err))
            # The Installation failed…
            if c.return_code != 0:
                # Save the Failed Dependency for later.
                failed_deps_list.append((c.dep, c.ignore_hash))
                # Alert the user.
                click.echo(
                    "{0} {1}! Will try again.".format(
                        crayons.red("An error occurred while installing"),
                        crayons.green(c.dep.as_line()),
                    )
                )

    if requirements:
        bare = True
    blocking = not concurrent
    # Load the lockfile if it exists, or if only is being used (e.g. lock is being used).
    if skip_lock or only or not project.lockfile_exists:
        if not bare:
            click.echo(
                crayons.normal(u"Installing dependencies from Pipfile…", bold=True)
            )
            lockfile = split_file(project._lockfile)
    else:
        with open(project.lockfile_location) as f:
            lockfile = split_file(simplejson.load(f))
        if not bare:
            click.echo(
                crayons.normal(
                    u"Installing dependencies from Pipfile.lock ({0})…".format(
                        lockfile["_meta"].get("hash", {}).get("sha256")[-6:]
                    ),
                    bold=True,
                )
            )
    # Allow pip to resolve dependencies when in skip-lock mode.
    no_deps = not skip_lock
    deps_list, dev_deps_list = merge_deps(
        lockfile,
        project,
        dev=dev,
        requirements=requirements,
        ignore_hashes=ignore_hashes,
        blocking=blocking,
        only=only,
    )
    failed_deps_list = []
    if requirements:
        index_args = prepare_pip_source_args(project.sources)
        index_args = " ".join(index_args).replace(" -", "\n-")
        deps_list = [dep for dep, ignore_hash, block in deps_list]
        dev_deps_list = [dep for dep, ignore_hash, block in dev_deps_list]
        # Output only default dependencies
        click.echo(index_args)
        if not dev:
            click.echo(
                "\n".join(d.partition("--hash")[0].strip() for d in sorted(deps_list))
            )
            sys.exit(0)
        # Output only dev dependencies
        if dev:
            click.echo(
                "\n".join(
                    d.partition("--hash")[0].strip() for d in sorted(dev_deps_list)
                )
            )
            sys.exit(0)
    procs = []
    deps_list_bar = progress.bar(
        deps_list, label=INSTALL_LABEL if os.name != "nt" else ""
    )
    for dep, ignore_hash, block in deps_list_bar:
        if len(procs) < PIPENV_MAX_SUBPROCESS:
            # Use a specific index, if specified.
            indexes, trusted_hosts, dep = parse_indexes(dep)
            index = None
            extra_indexes = []
            if indexes:
                index = indexes[0]
                if len(indexes) > 0:
                    extra_indexes = indexes[1:]
            dep = Requirement.from_line(" ".join(dep))
            if index:
                _index = None
                try:
                    _index = project.find_source(index).get("name")
                except SourceNotFound:
                    _index = None
                dep.index = _index
                dep._index = index
                dep.extra_indexes = extra_indexes
            # Install the module.
            prev_no_deps_setting = no_deps
            if dep.is_file_or_url and any(
                dep.req.uri.endswith(ext) for ext in ["zip", "tar.gz"]
            ):
                no_deps = False
            c = pip_install(
                dep,
                ignore_hashes=ignore_hash,
                allow_global=allow_global,
                no_deps=no_deps,
                block=block,
                index=index,
                requirements_dir=requirements_dir,
                extra_indexes=extra_indexes,
                pypi_mirror=pypi_mirror,
                trusted_hosts=trusted_hosts
            )
            c.dep = dep
            c.ignore_hash = ignore_hash
            c.index = index
            c.extra_indexes = extra_indexes
            procs.append(c)
            no_deps = prev_no_deps_setting
        if len(procs) >= PIPENV_MAX_SUBPROCESS or len(procs) == len(deps_list):
            cleanup_procs(procs, concurrent)
            procs = []
    cleanup_procs(procs, concurrent)
    # Iterate over the hopefully-poorly-packaged dependencies…
    if failed_deps_list:
        click.echo(
            crayons.normal(u"Installing initially failed dependencies…", bold=True)
        )
        for dep, ignore_hash in progress.bar(failed_deps_list, label=INSTALL_LABEL2):
            # Use a specific index, if specified.
            # Install the module.
            prev_no_deps_setting = no_deps
            if dep.is_file_or_url and any(
                dep.req.uri.endswith(ext) for ext in ["zip", "tar.gz"]
            ):
                no_deps = False
            c = pip_install(
                dep,
                ignore_hashes=ignore_hash,
                allow_global=allow_global,
                no_deps=no_deps,
                index=getattr(dep, "_index", None),
                requirements_dir=requirements_dir,
                extra_indexes=getattr(dep, "extra_indexes", None),
            )
            no_deps = prev_no_deps_setting
            # The Installation failed…
            if c.return_code != 0:
                # We echo both c.out and c.err because pip returns error details on out.
                click.echo(crayons.blue(format_pip_output(c.out)))
                click.echo(crayons.blue(format_pip_error(c.err)), err=True)
                # Return the subprocess' return code.
                sys.exit(c.return_code)
            else:
                click.echo(
                    "{0} {1}{2}".format(
                        crayons.green("Success installing"),
                        crayons.green(dep.name),
                        crayons.green("!"),
                    )
                )


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


def do_create_virtualenv(python=None, site_packages=False, pypi_mirror=None):
    """Creates a virtualenv."""
    click.echo(
        crayons.normal(u"Creating a virtualenv for this project…", bold=True), err=True
    )
    click.echo(
        u"Pipfile: {0}".format(crayons.red(project.pipfile_location, bold=True)),
        err=True,
    )

    # Default to using sys.executable, if Python wasn't provided.
    if not python:
        python = sys.executable
    click.echo(
        u"{0} {1} {3} {2}".format(
            crayons.normal("Using", bold=True),
            crayons.red(python, bold=True),
            crayons.normal(u"to create virtualenv…", bold=True),
            crayons.green("({0})".format(python_version(python))),
        ),
        err=True,
    )

    cmd = [
        sys.executable,
        "-m",
        "virtualenv",
        "--prompt=({0}) ".format(project.name),
        "--python={0}".format(python),
        project.get_location_for_virtualenv(),
    ]

    # Pass site-packages flag to virtualenv, if desired…
    if site_packages:
        click.echo(
            crayons.normal(u"Making site-packages available…", bold=True), err=True
        )
        cmd.append("--system-site-packages")

    if pypi_mirror:
        pip_config = {"PIP_INDEX_URL": vistir.misc.fs_str(pypi_mirror)}
    else:
        pip_config = {}

    # Actually create the virtualenv.
    with spinner():
        c = delegator.run(cmd, block=False, timeout=PIPENV_TIMEOUT, env=pip_config)
        c.block()
    click.echo(crayons.blue("{0}".format(c.out)), err=True)
    if c.return_code != 0:
        click.echo(crayons.blue("{0}".format(c.err)), err=True)
        click.echo(
            u"{0}: Failed to create virtual environment.".format(
                crayons.red("Warning", bold=True)
            ),
            err=True,
        )
        sys.exit(1)

    # Associate project directory with the environment.
    # This mimics Pew's "setproject".
    project_file_name = os.path.join(project.virtualenv_location, ".project")
    with open(project_file_name, "w") as f:
        f.write(vistir.misc.fs_str(project.project_directory))

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


def do_lock(
    system=False,
    clear=False,
    pre=False,
    keep_outdated=False,
    write=True,
    pypi_mirror=None,
):
    """Executes the freeze functionality."""
    from .utils import get_vcs_deps

    cached_lockfile = {}
    if not pre:
        pre = project.settings.get("allow_prereleases")
    if keep_outdated:
        if not project.lockfile_exists:
            click.echo(
                "{0}: Pipfile.lock must exist to use --keep-outdated!".format(
                    crayons.red("Warning", bold=True)
                )
            )
            sys.exit(1)
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
    for dev_package in project.dev_packages:
        if dev_package in project.packages:
            dev_packages[dev_package] = project.packages[dev_package]
    # Resolve dev-package dependencies, with pip-tools.
    pip_freeze = delegator.run(
        "{0} freeze".format(escape_grouped_arguments(which_pip(allow_global=system)))
    ).out
    sections = {
        "dev": {
            "packages": project.dev_packages,
            "vcs": project.vcs_dev_packages,
            "pipfile_key": "dev_packages",
            "lockfile_key": "develop",
            "log_string": "dev-packages",
            "dev": True,
        },
        "default": {
            "packages": project.packages,
            "vcs": project.vcs_packages,
            "pipfile_key": "packages",
            "lockfile_key": "default",
            "log_string": "packages",
            "dev": False,
        },
    }
    for section_name in ["dev", "default"]:
        settings = sections[section_name]
        if write:
            # Alert the user of progress.
            click.echo(
                u"{0} {1} {2}".format(
                    crayons.normal("Locking"),
                    crayons.red("[{0}]".format(settings["log_string"])),
                    crayons.normal("dependencies…"),
                ),
                err=True,
            )

        deps = convert_deps_to_pip(
            settings["packages"], project, r=False, include_index=True
        )
        results = venv_resolve_deps(
            deps,
            which=which,
            project=project,
            clear=clear,
            pre=pre,
            allow_global=system,
            pypi_mirror=pypi_mirror,
        )
        # Add dependencies to lockfile.
        for dep in results:
            is_top_level = dep["name"] in settings["packages"]
            pipfile_entry = settings["packages"][dep["name"]] if is_top_level else None
            dep_lockfile = clean_resolved_dep(
                dep, is_top_level=is_top_level, pipfile_entry=pipfile_entry
            )
            lockfile[settings["lockfile_key"]].update(dep_lockfile)
        # Add refs for VCS installs.
        # TODO: be smarter about this.
        vcs_reqs, vcs_lockfile = get_vcs_deps(
            project,
            pip_freeze,
            which=which,
            clear=clear,
            pre=pre,
            allow_global=system,
            dev=settings["dev"],
        )
        vcs_lines = [req.as_line() for req in vcs_reqs if req.editable]
        vcs_results = venv_resolve_deps(
            vcs_lines,
            which=which,
            project=project,
            clear=clear,
            pre=pre,
            allow_global=system,
            pypi_mirror=pypi_mirror,
        )
        for dep in vcs_results:
            normalized = pep423_name(dep["name"])
            if not hasattr(dep, "keys") or not hasattr(dep["name"], "keys"):
                continue
            is_top_level = dep["name"] in vcs_lockfile or normalized in vcs_lockfile
            if is_top_level:
                try:
                    pipfile_entry = vcs_lockfile[dep["name"]]
                except KeyError:
                    pipfile_entry = vcs_lockfile[normalized]
            else:
                pipfile_entry = None
            dep_lockfile = clean_resolved_dep(
                dep, is_top_level=is_top_level, pipfile_entry=pipfile_entry
            )
            vcs_lockfile.update(dep_lockfile)
        lockfile[settings["lockfile_key"]].update(vcs_lockfile)

    # Support for --keep-outdated…
    if keep_outdated:
        for section_name, section in (
            ("default", project.packages),
            ("develop", project.dev_packages),
        ):
            for package_specified in section:
                norm_name = pep423_name(package_specified)
                if not is_pinned(section[package_specified]):
                    if norm_name in cached_lockfile[section_name]:
                        lockfile[section_name][norm_name] = cached_lockfile[
                            section_name
                        ][norm_name]
    # Overwrite any develop packages with default packages.
    for default_package in lockfile["default"]:
        if default_package in lockfile["develop"]:
            lockfile["develop"][default_package] = lockfile["default"][default_package]
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
    from .vendor.requirementslib.models.requirements import Requirement

    if downloads:
        if not bare:
            click.echo(crayons.normal(u"Clearing out downloads directory…", bold=True))
        shutil.rmtree(project.download_location)
        return

    freeze = delegator.run(
        "{0} freeze".format(
            escape_grouped_arguments(which_pip(allow_global=allow_global))
        )
    ).out
    # Remove comments from the output, if any.
    installed = [
        line for line in freeze.splitlines() if not line.lstrip().startswith("#")
    ]
    # Remove setuptools and friends from installed, if present.
    for package_name in BAD_PACKAGES:
        for i, package in enumerate(installed):
            if package.startswith(package_name):
                del installed[i]
    actually_installed = []
    for package in installed:
        try:
            dep = Requirement.from_line(package)
        except AssertionError:
            dep = None
        if dep and not dep.is_vcs and not dep.editable:
            dep = dep.name
            actually_installed.append(dep)
    if not bare:
        click.echo(
            u"Found {0} installed package(s), purging…".format(len(actually_installed))
        )
    command = "{0} uninstall {1} -y".format(
        escape_grouped_arguments(which_pip(allow_global=allow_global)),
        " ".join(actually_installed),
    )
    if environments.is_verbose():
        click.echo("$ {0}".format(command))
    c = delegator.run(command)
    if not bare:
        click.echo(crayons.blue(c.out))
        click.echo(crayons.green("Environment now purged and fresh!"))


def do_init(
    dev=False,
    requirements=False,
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
    from .environments import PIPENV_VIRTUALENV

    cleanup_reqdir = False
    if not system:
        if not project.virtualenv_exists:
            try:
                do_create_virtualenv(pypi_mirror=pypi_mirror)
            except KeyboardInterrupt:
                cleanup_virtualenv(bare=False)
                sys.exit(1)
    # Ensure the Pipfile exists.
    if not deploy:
        ensure_pipfile(system=system)
    if not requirements_dir:
        cleanup_reqdir = True
        requirements_dir = vistir.compat.TemporaryDirectory(
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
                click.echo(crayons.normal("Aborting deploy.", bold=True), err=True)
                requirements_dir.cleanup()
                sys.exit(1)
            elif (system or allow_global) and not (PIPENV_VIRTUALENV):
                click.echo(
                    crayons.red(
                        u"Pipfile.lock ({0}) out of date, but installation "
                        u"uses {1}… re-building lockfile must happen in "
                        u"isolation. Please rebuild lockfile in a virtualenv. "
                        u"Continuing anyway…".format(
                            crayons.white(old_hash[-6:]), crayons.white("--system")
                        ),
                        bold=True,
                    ),
                    err=True,
                )
            else:
                if old_hash:
                    msg = u"Pipfile.lock ({1}) out of date, updating to ({0})…"
                else:
                    msg = u"Pipfile.lock is corrupted, replaced with ({0})…"
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
            click.echo(
                "{0}: --system is intended to be used for Pipfile installation, "
                "not installation of specific packages. Aborting.".format(
                    crayons.red("Warning", bold=True)
                ),
                err=True,
            )
            click.echo("See also: --deploy flag.", err=True)
            requirements_dir.cleanup()
            sys.exit(1)
        else:
            click.echo(
                crayons.normal(u"Pipfile.lock not found, creating…", bold=True),
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
        requirements=requirements,
        allow_global=allow_global,
        skip_lock=skip_lock,
        concurrent=concurrent,
        requirements_dir=requirements_dir.name,
        pypi_mirror=pypi_mirror,
    )
    if cleanup_reqdir:
        requirements_dir.cleanup()

    # Hint the user what to do to activate the virtualenv.
    if not allow_global and not deploy and "PIPENV_ACTIVE" not in os.environ:
        click.echo(
            "To activate this project's virtualenv, run {0}.\n"
            "Alternatively, run a command "
            "inside the virtualenv with {1}.".format(
                crayons.red("pipenv shell"), crayons.red("pipenv run")
            )
        )


def pip_install(
    requirement=None,
    r=None,
    allow_global=False,
    ignore_hashes=False,
    no_deps=True,
    block=True,
    index=None,
    pre=False,
    selective_upgrade=False,
    requirements_dir=None,
    extra_indexes=None,
    pypi_mirror=None,
    trusted_hosts=None
):
    from notpip._internal import logger as piplogger
    from .vendor.urllib3.util import parse_url

    src = []
    write_to_tmpfile = False
    if requirement:
        editable_with_markers = requirement.editable and requirement.markers
        needs_hashes = not requirement.editable and not ignore_hashes and r is None
        write_to_tmpfile = needs_hashes or editable_with_markers

    if not trusted_hosts:
        trusted_hosts = []
    trusted_hosts.extend(os.environ.get("PIP_TRUSTED_HOSTS", []))
    if environments.is_verbose():
        piplogger.setLevel(logging.INFO)
        if requirement:
            click.echo(
                crayons.normal("Installing {0!r}".format(requirement.name), bold=True),
                err=True,
            )
    # Create files for hash mode.
    if write_to_tmpfile:
        with vistir.compat.NamedTemporaryFile(
            prefix="pipenv-", suffix="-requirement.txt", dir=requirements_dir,
            delete=False
        ) as f:
            f.write(vistir.misc.to_bytes(requirement.as_line()))
            r = f.name
    # Install dependencies when a package is a VCS dependency.
    if requirement and requirement.vcs:
        no_deps = False
        # Don't specify a source directory when using --system.
        if not allow_global and ("PIP_SRC" not in os.environ):
            src.extend(["--src", "{0}".format(project.virtualenv_src_location)])

    # Try installing for each source in project.sources.
    if index:
        try:
            index_source = project.find_source(index)
            index_source = index_source.copy()
        except SourceNotFound:
            src_name = project.src_name_from_url(index)
            index_url = parse_url(index)
            verify_ssl = index_url.host not in trusted_hosts
            index_source = {"url": index, "verify_ssl": verify_ssl, "name": src_name}
        sources = [index_source.copy(),]
        if extra_indexes:
            if isinstance(extra_indexes, six.string_types):
                extra_indexes = [extra_indexes,]
            for idx in extra_indexes:
                try:
                    extra_src = project.find_source(idx)
                except SourceNotFound:
                    src_name = project.src_name_from_url(idx)
                    src_url = parse_url(idx)
                    verify_ssl = src_url.host not in trusted_hosts
                    extra_src = {"url": idx, "verify_ssl": verify_ssl, "name": extra_src}
                if extra_src["url"] != index_source["url"]:
                    sources.append(extra_src)
        else:
            for idx in project.pipfile_sources:
                if idx["url"] != sources[0]["url"]:
                    sources.append(idx)
    else:
        sources = project.pipfile_sources
    if pypi_mirror:
        sources = [
            create_mirror_source(pypi_mirror) if is_pypi_url(source["url"]) else source
            for source in sources
        ]
    if (requirement and requirement.editable) and not r:
        install_reqs = requirement.as_line(as_list=True)
        if requirement.editable and install_reqs[0].startswith("-e "):
            req, install_reqs = install_reqs[0], install_reqs[1:]
            editable_opt, req = req.split(" ", 1)
            install_reqs = [editable_opt, req] + install_reqs
        if not any(item.startswith("--hash") for item in install_reqs):
            ignore_hashes = True
    elif r:
        install_reqs = ["-r", r]
        with open(r) as f:
            if "--hash" not in f.read():
                ignore_hashes = True
    else:
        ignore_hashes = True if not requirement.hashes else False
        install_reqs = requirement.as_line(as_list=True)
    pip_command = [which_pip(allow_global=allow_global), "install"]
    if pre:
        pip_command.append("--pre")
    if src:
        pip_command.extend(src)
    if environments.is_verbose():
        pip_command.append("--verbose")
    pip_command.append("--upgrade")
    if selective_upgrade:
        pip_command.append("--upgrade-strategy=only-if-needed")
    if no_deps:
        pip_command.append("--no-deps")
    install_reqs = [escape_cmd(req) for req in install_reqs]
    pip_command.extend(install_reqs)
    pip_command.extend(prepare_pip_source_args(sources))
    if not ignore_hashes:
        pip_command.append("--require-hashes")

    if environments.is_verbose():
        click.echo("$ {0}".format(pip_command), err=True)
    cache_dir = vistir.compat.Path(PIPENV_CACHE_DIR)
    pip_config = {
        "PIP_CACHE_DIR": vistir.misc.fs_str(cache_dir.as_posix()),
        "PIP_WHEEL_DIR": vistir.misc.fs_str(cache_dir.joinpath("wheels").as_posix()),
        "PIP_DESTINATION_DIR": vistir.misc.fs_str(
            cache_dir.joinpath("pkgs").as_posix()
        ),
        "PIP_EXISTS_ACTION": vistir.misc.fs_str("w"),
        "PATH": vistir.misc.fs_str(os.environ.get("PATH")),
    }
    if src:
        pip_config.update(
            {"PIP_SRC": vistir.misc.fs_str(project.virtualenv_src_location)}
        )
    pip_command = Script.parse(pip_command).cmdify()
    c = delegator.run(pip_command, block=block, env=pip_config)
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


def which_pip(allow_global=False):
    """Returns the location of virtualenv-installed pip."""
    if allow_global:
        if "VIRTUAL_ENV" in os.environ:
            return which("pip", location=os.environ["VIRTUAL_ENV"])

        for p in ("pip", "pip3", "pip2"):
            where = system_which(p)
            if where:
                return where

    return which("pip")


def system_which(command, mult=False):
    """Emulates the system's which. Returns None if not found."""
    _which = "which -a" if not os.name == "nt" else "where"
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
        return None if not mult else []

    result = c.out.strip() or c.err.strip()
    if mult:
        return result.split("\n")

    else:
        return result.split("\n")[0]


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
    pipenv_active = os.environ.get("PIPENV_ACTIVE")
    if (environments.PIPENV_USE_SYSTEM or environments.PIPENV_VIRTUALENV) and not (
        pipenv_active or environments.is_quiet()
    ):
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
                    u"Pipfile.lock ({0}) out of date, updating to ({1})…".format(
                        old_hash[-6:], new_hash[-6:]
                    ),
                    bold=True,
                ),
                err=True,
            )
            do_lock(keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)
    else:
        do_lock(keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)


def do_py(system=False):
    try:
        click.echo(which("python", allow_global=system))
    except AttributeError:
        click.echo(crayons.red("No project found!"))


def do_outdated(pypi_mirror=None):
    from .vendor.requirementslib.models.requirements import Requirement

    packages = {}
    results = delegator.run("{0} freeze".format(which("pip"))).out.strip().split("\n")
    results = filter(bool, results)
    for result in results:
        dep = Requirement.from_line(result)
        packages.update(dep.as_pipfile())
    updated_packages = {}
    lockfile = do_lock(write=False, pypi_mirror=pypi_mirror)
    for section in ("develop", "default"):
        for package in lockfile[section]:
            try:
                updated_packages[package] = lockfile[section][package]["version"]
            except KeyError:
                pass
    outdated = []
    for package in packages:
        norm_name = pep423_name(package)
        if norm_name in updated_packages:
            if updated_packages[norm_name] != packages[package]:
                outdated.append(
                    (package, updated_packages[norm_name], packages[package])
                )
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
    requirements=False,
    sequential=False,
    pre=False,
    code=False,
    deploy=False,
    keep_outdated=False,
    selective_upgrade=False,
):
    from .environments import PIPENV_VIRTUALENV, PIPENV_USE_SYSTEM
    from notpip._internal.exceptions import PipError

    requirements_directory = vistir.compat.TemporaryDirectory(
        suffix="-requirements", prefix="pipenv-"
    )
    if selective_upgrade:
        keep_outdated = True
    packages = packages if packages else []
    editable_packages = editable_packages if editable_packages else []
    package_args = [p for p in packages if p] + [p for p in editable_packages if p]
    skip_requirements = False
    # Don't search for requirements.txt files if the user provides one
    if requirements or package_args or project.pipfile_exists:
        skip_requirements = True
    concurrent = not sequential
    # Ensure that virtualenv is available.
    ensure_project(
        three=three,
        python=python,
        system=system,
        warn=True,
        deploy=deploy,
        skip_requirements=skip_requirements,
        pypi_mirror=pypi_mirror,
    )
    # Load the --pre settings from the Pipfile.
    if not pre:
        pre = project.settings.get("allow_prereleases")
    if not keep_outdated:
        keep_outdated = project.settings.get("keep_outdated")
    remote = requirements and is_valid_url(requirements)
    # Warn and exit if --system is used without a pipfile.
    if (system and package_args) and not (PIPENV_VIRTUALENV):
        click.echo(
            "{0}: --system is intended to be used for Pipfile installation, "
            "not installation of specific packages. Aborting.".format(
                crayons.red("Warning", bold=True)
            ),
            err=True,
        )
        click.echo("See also: --deploy flag.", err=True)
        requirements_directory.cleanup()
        sys.exit(1)
    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True
    # Check if the file is remote or not
    if remote:
        fd, temp_reqs = tempfile.mkstemp(
            prefix="pipenv-", suffix="-requirement.txt", dir=requirements_directory.name
        )
        requirements_url = requirements
        # Download requirements file
        click.echo(
            crayons.normal(
                u"Remote requirements file provided! Downloading…", bold=True
            ),
            err=True,
        )
        try:
            download_file(requirements, temp_reqs)
        except IOError:
            click.echo(
                crayons.red(
                    u"Unable to find requirements file at {0}.".format(
                        crayons.normal(requirements)
                    )
                ),
                err=True,
            )
            requirements_directory.cleanup()
            sys.exit(1)
        # Replace the url with the temporary requirements file
        requirements = temp_reqs
        remote = True
    if requirements:
        error, traceback = None, None
        click.echo(
            crayons.normal(
                u"Requirements file provided! Importing into Pipfile…", bold=True
            ),
            err=True,
        )
        try:
            import_requirements(r=project.path_to(requirements), dev=dev)
        except (UnicodeDecodeError, PipError) as e:
            # Don't print the temp file path if remote since it will be deleted.
            req_path = requirements_url if remote else project.path_to(requirements)
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
                os.close(fd)  # Close for windows to allow file cleanup.
                os.remove(project.path_to(temp_reqs))
            if error and traceback:
                click.echo(crayons.red(error))
                click.echo(crayons.blue(str(traceback)), err=True)
                requirements_directory.cleanup()
                sys.exit(1)
    if code:
        click.echo(
            crayons.normal(u"Discovering imports from local codebase…", bold=True)
        )
        for req in import_from_code(code):
            click.echo("  Found {0}!".format(crayons.green(req)))
            project.add_package_to_pipfile(req)
    # Install editable local packages before locking - this gives us access to dist-info
    if project.pipfile_exists and (
        # double negatives are for english readability, leave them alone.
        (not project.lockfile_exists and not deploy)
        or (not project.virtualenv_exists and not system)
    ):
        section = (
            project.editable_packages if not dev else project.editable_dev_packages
        )
        for package in section.keys():
            req = convert_deps_to_pip(
                {package: section[package]}, project=project, r=False
            )
            if req:
                req = req[0]
                req = req[len("-e ") :] if req.startswith("-e ") else req
                if not editable_packages:
                    editable_packages = [req]
                else:
                    editable_packages.extend([req])
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
                        {packages: section[package__name]}, project=project, r=False
                    )[0]
            except KeyError:
                pass
    # Install all dependencies, if none was provided.
    # This basically ensures that we have a pipfile and lockfile, then it locks and
    # installs from the lockfile
    if packages is False and editable_packages is False:
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
        )

    # This is for if the user passed in dependencies, then we want to maek sure we
    else:
        from .vendor.requirementslib import Requirement

        # make a tuple of (display_name, entry)
        pkg_list = packages + ["-e {0}".format(pkg) for pkg in editable_packages]

        for pkg_line in pkg_list:
            click.echo(
                crayons.normal(
                    u"Installing {0}…".format(crayons.green(pkg_line, bold=True)),
                    bold=True,
                )
            )
            # pip install:
            with spinner():
                try:
                    pkg_requirement = Requirement.from_line(pkg_line)
                except ValueError as e:
                    click.echo("{0}: {1}".format(crayons.red("WARNING"), e))
                    requirements_directory.cleanup()
                    sys.exit(1)
                if index_url:
                    pkg_requirement.index = index_url
                c = pip_install(
                    pkg_requirement,
                    ignore_hashes=True,
                    allow_global=system,
                    selective_upgrade=selective_upgrade,
                    no_deps=False,
                    pre=pre,
                    requirements_dir=requirements_directory.name,
                    index=index_url,
                    extra_indexes=extra_index_url,
                    pypi_mirror=pypi_mirror,
                )
                # Warn if --editable wasn't passed.
                if pkg_requirement.is_vcs and not pkg_requirement.editable:
                    click.echo(
                        "{0}: You installed a VCS dependency in non-editable mode. "
                        "This will work fine, but sub-dependencies will not be resolved by {1}."
                        "\n  To enable this sub-dependency functionality, specify that this dependency is editable."
                        "".format(
                            crayons.red("Warning", bold=True),
                            crayons.red("$ pipenv lock"),
                        )
                    )
            click.echo(crayons.blue(format_pip_output(c.out)))
            # Ensure that package was successfully installed.
            try:
                assert c.return_code == 0
            except AssertionError:
                click.echo(
                    "{0} An error occurred while installing {1}!".format(
                        crayons.red("Error: ", bold=True), crayons.green(pkg_line)
                    ),
                    err=True,
                )
                click.echo(crayons.blue(format_pip_error(c.err)), err=True)
                if "setup.py egg_info" in c.err:
                    click.echo(
                        "This is likely caused by a bug in {0}. "
                        "Report this to its maintainers.".format(
                            crayons.green(pkg_requirement.name)
                        ),
                        err=True,
                    )
                requirements_directory.cleanup()
                sys.exit(1)
            click.echo(
                "{0} {1} {2} {3}{4}".format(
                    crayons.normal("Adding", bold=True),
                    crayons.green(pkg_requirement.name, bold=True),
                    crayons.normal("to Pipfile's", bold=True),
                    crayons.red("[dev-packages]" if dev else "[packages]", bold=True),
                    crayons.normal("…", bold=True),
                )
            )
            # Add the package to the Pipfile.
            try:
                project.add_package_to_pipfile(pkg_requirement, dev)
            except ValueError as e:
                click.echo(
                    "{0} {1}".format(crayons.red("ERROR (PACKAGE NOT INSTALLED):"), e)
                )
            # Update project settings with pre preference.
            if pre:
                project.update_settings({"allow_prereleases": pre})
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
    requirements_directory.cleanup()
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
):
    from .environments import PIPENV_USE_SYSTEM
    from .vendor.requirementslib.models.requirements import Requirement

    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True
    # Ensure that virtualenv is available.
    # TODO: We probably shouldn't ensure a project exists if the outcome will be to just
    # install things in order to remove them... maybe tell the user to install first?
    ensure_project(three=three, python=python, pypi_mirror=pypi_mirror)
    editable_pkgs = [
        Requirement.from_line("-e {0}".format(p)).name for p in editable_packages if p
    ]
    package_names = [p for p in packages if p] + editable_pkgs
    pipfile_remove = True
    # Un-install all dependencies, if --all was provided.
    if all is True:
        click.echo(
            crayons.normal(u"Un-installing all packages from virtualenv…", bold=True)
        )
        do_purge(allow_global=system)
        return
    # Uninstall [dev-packages], if --dev was provided.
    if all_dev:
        if "dev-packages" not in project.parsed_pipfile:
            click.echo(
                crayons.normal(
                    "No {0} to uninstall.".format(crayons.red("[dev-packages]")),
                    bold=True,
                )
            )
            return
        click.echo(
            crayons.normal(
                u"Un-installing {0}…".format(crayons.red("[dev-packages]")), bold=True
            )
        )
        package_names = project.dev_packages.keys()
    if packages is False and editable_packages is False and not all_dev:
        click.echo(crayons.red("No package provided!"), err=True)
        return 1
    for package_name in package_names:
        click.echo(u"Un-installing {0}…".format(crayons.green(package_name)))
        cmd = "{0} uninstall {1} -y".format(
            escape_grouped_arguments(which_pip(allow_global=system)), package_name
        )
        if environments.is_verbose():
            click.echo("$ {0}".format(cmd))
        c = delegator.run(cmd)
        click.echo(crayons.blue(c.out))
        if pipfile_remove:
            in_packages = project.get_package_name_in_pipfile(package_name, dev=False)
            in_dev_packages = project.get_package_name_in_pipfile(
                package_name, dev=True
            )
            if not in_dev_packages and not in_packages:
                click.echo(
                    "No package {0} to remove from Pipfile.".format(
                        crayons.green(package_name)
                    )
                )
                continue

            click.echo(
                u"Removing {0} from Pipfile…".format(crayons.green(package_name))
            )
            # Remove package from both packages and dev-packages.
            project.remove_package_from_pipfile(package_name, dev=True)
            project.remove_package_from_pipfile(package_name, dev=False)
    if lock:
        do_lock(system=system, keep_outdated=keep_outdated, pypi_mirror=pypi_mirror)


def do_shell(three=None, python=False, fancy=False, shell_args=None, pypi_mirror=None):
    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False, pypi_mirror=pypi_mirror)
    # Set an environment variable, so we know we're in the environment.
    os.environ["PIPENV_ACTIVE"] = vistir.misc.fs_str("1")
    # Support shell compatibility mode.
    if PIPENV_SHELL_FANCY:
        fancy = True

    from .shells import choose_shell

    shell = choose_shell()
    click.echo("Launching subshell in virtual environment…", err=True)

    fork_args = (project.virtualenv_location, project.project_directory, shell_args)

    if fancy:
        shell.fork(*fork_args)
        return

    try:
        shell.fork_compat(*fork_args)
    except (AttributeError, ImportError):
        click.echo(
            u"Compatibility mode not supported. "
            u"Trying to continue as well-configured shell…",
            err=True,
        )
        shell.fork(*fork_args)


def _inline_activate_virtualenv():
    try:
        activate_this = which("activate_this.py")
        if not activate_this or not os.path.exists(activate_this):
            click.echo(
                u"{0}: activate_this.py not found. Your environment is most "
                u"certainly not activated. Continuing anyway…"
                u"".format(crayons.red("Warning", bold=True)),
                err=True,
            )
            return
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
    os.execl(command_path, command_path, *script.args)


def do_run(command, args, three=None, python=False, pypi_mirror=None):
    """Attempt to run command either pulling from project or interpreting as executable.

    Args are appended to the command in [scripts] section of project if found.
    """
    from .cmdparse import ScriptEmptyError

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False, pypi_mirror=pypi_mirror)
    load_dot_env()
    # Activate virtualenv under the current interpreter's environment
    inline_activate_virtual_environment()
    try:
        script = project.build_script(command, args)
    except ScriptEmptyError:
        click.echo("Can't run script {0!r}-it's empty?", err=True)
    if os.name == "nt":
        do_run_nt(script)
    else:
        do_run_posix(script, command=command)


def do_check(
    three=None,
    python=False,
    system=False,
    unused=False,
    ignore=None,
    args=None,
    pypi_mirror=None,
):
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
        deps_required = [k for k in project.packages.keys()]
        deps_needed = import_from_code(unused)
        for dep in deps_needed:
            try:
                deps_required.remove(dep)
            except ValueError:
                pass
        if deps_required:
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
    click.echo(crayons.normal(u"Checking PEP 508 requirements…", bold=True))
    if system:
        python = system_which("python")
    else:
        python = which("python")
    # Run the PEP 508 checker in the virtualenv.
    c = delegator.run(
        '"{0}" {1}'.format(
            python, escape_grouped_arguments(pep508checker.__file__.rstrip("cdo"))
        )
    )
    results = simplejson.loads(c.out)
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
        click.echo(crayons.green("Passed!"))
    click.echo(crayons.normal(u"Checking installed package safety…", bold=True))
    path = pep508checker.__file__.rstrip("cdo")
    path = os.sep.join(__file__.split(os.sep)[:-1] + ["patched", "safety.zip"])
    if not system:
        python = which("python")
    else:
        python = system_which("python")
    if ignore:
        ignored = "--ignore {0}".format(" --ignore ".join(ignore))
        click.echo(
            crayons.normal(
                "Notice: Ignoring CVE(s) {0}".format(crayons.yellow(", ".join(ignore)))
            ),
            err=True,
        )
    else:
        ignored = ""
    c = delegator.run(
        '"{0}" {1} check --json --key=1ab8d58f-5122e025-83674263-bc1e79e0 {2}'.format(
            python, escape_grouped_arguments(path), ignored
        )
    )
    try:
        results = simplejson.loads(c.out)
    except ValueError:
        click.echo("An error occurred:", err=True)
        click.echo(c.err, err=True)
        sys.exit(1)
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
    if not results:
        click.echo(crayons.green("All good!"))
    else:
        sys.exit(1)


def do_graph(bare=False, json=False, json_tree=False, reverse=False):
    import pipdeptree
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
            u"running {1} first to automatically generate one for you or see"
            u"{2} for further instructions.".format(
                crayons.red("Warning", bold=True),
                crayons.green("`pipenv install`"),
                crayons.green("`pipenv install --help`"),
            ),
            err=True,
        )
        sys.exit(1)
    cmd = '"{0}" {1} {2} -l'.format(
        python_path, escape_grouped_arguments(pipdeptree.__file__.rstrip("cdo")), flag
    )
    # Run dep-tree.
    c = delegator.run(cmd)
    if not bare:
        if json:
            data = []
            for d in simplejson.loads(c.out):
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

            data = traverse(simplejson.loads(c.out))
            click.echo(simplejson.dumps(data, indent=4))
            sys.exit(0)
        else:
            for line in c.out.split("\n"):
                # Ignore bad packages as top level.
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
        click.echo(
            "{0}: Pipfile.lock is missing! You need to run {1} first.".format(
                crayons.red("Error", bold=True), crayons.red("$ pipenv lock", bold=True)
            ),
            err=True,
        )
        return 1

    # Ensure that virtualenv is available if not system.
    ensure_project(
        three=three,
        python=python,
        validate=False,
        deploy=deploy,
        pypi_mirror=pypi_mirror,
    )

    # Install everything.
    requirements_dir = vistir.compat.TemporaryDirectory(
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
    requirements_dir.cleanup()
    click.echo(crayons.green("All dependencies are now up-to-date!"))


def do_clean(ctx, three=None, python=None, dry_run=False, bare=False, pypi_mirror=None):
    # Ensure that virtualenv is available.
    from packaging.utils import canonicalize_name
    ensure_project(three=three, python=python, validate=False, pypi_mirror=pypi_mirror)
    ensure_lockfile(pypi_mirror=pypi_mirror)
    installed_package_names = [
        canonicalize_name(pkg.project_name) for pkg in project.get_installed_packages()
    ]
    # Remove known "bad packages" from the list.
    for bad_package in BAD_PACKAGES:
        if canonicalize_name(bad_package) in installed_package_names:
            if environments.is_verbose():
                click.echo("Ignoring {0}.".format(repr(bad_package)), err=True)
            del installed_package_names[installed_package_names.index(
                canonicalize_name(bad_package)
            )]
    # Intelligently detect if --dev should be used or not.
    develop = [canonicalize_name(k) for k in project.lockfile_content["develop"].keys()]
    default = [canonicalize_name(k) for k in project.lockfile_content["default"].keys()]
    for used_package in set(develop + default):
        if used_package in installed_package_names:
            del installed_package_names[installed_package_names.index(
                canonicalize_name(used_package)
            )]
    failure = False
    for apparent_bad_package in installed_package_names:
        if dry_run:
            click.echo(apparent_bad_package)
        else:
            click.echo(
                crayons.white(
                    "Uninstalling {0}…".format(repr(apparent_bad_package)), bold=True
                )
            )
            # Uninstall the package.
            c = delegator.run(
                "{0} uninstall {1} -y".format(which_pip(), apparent_bad_package)
            )
            if c.return_code != 0:
                failure = True
    sys.exit(int(failure))
