import logging
import os
import tempfile
from pathlib import Path
from typing import List, Optional

from pipenv.patched.pip._internal.build_env import get_runnable_pip
from pipenv.project import Project
from pipenv.utils.dependencies import get_constraints_from_deps, prepare_constraint_file
from pipenv.utils.indexes import get_source_list, prepare_pip_source_args
from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import cmd_list_to_shell, project_python
from pipenv.vendor import click
from pipenv.vendor.requirementslib import Requirement
from pipenv.vendor.requirementslib.fileutils import create_tracked_tempdir, normalize_path


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


def format_pip_error(error):
    error = error.replace("Expected", str(click.style("Expected", fg="green", bold=True)))
    error = error.replace("Got", str(click.style("Got", fg="red", bold=True)))
    error = error.replace(
        "THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE",
        str(
            click.style(
                "THESE PACKAGES DO NOT MATCH THE HASHES FROM Pipfile.lock!",
                fg="red",
                bold=True,
            )
        ),
    )
    error = error.replace(
        "someone may have tampered with them",
        str(click.style("someone may have tampered with them", fg="red")),
    )
    error = error.replace("option to pip install", "option to 'pipenv install'")
    return error


def pip_download(project, package_name):
    cache_dir = Path(project.s.PIPENV_CACHE_DIR)
    pip_config = {
        "PIP_CACHE_DIR": cache_dir.as_posix(),
        "PIP_WHEEL_DIR": cache_dir.joinpath("wheels").as_posix(),
        "PIP_DESTINATION_DIR": cache_dir.joinpath("pkgs").as_posix(),
    }
    for source in project.sources:
        cmd = [
            project_python(project),
            get_runnable_pip(),
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


def pip_install_deps(
    project,
    deps,
    sources,
    allow_global=False,
    ignore_hashes=False,
    no_deps=False,
    selective_upgrade=False,
    requirements_dir=None,
    use_pep517=True,
    extra_pip_args: Optional[List] = None,
):
    if not allow_global:
        src_dir = os.getenv(
            "PIP_SRC", os.getenv("PIP_SRC_DIR", project.virtualenv_src_location)
        )
    else:
        src_dir = os.getenv("PIP_SRC", os.getenv("PIP_SRC_DIR"))
    if not requirements_dir:
        requirements_dir = create_tracked_tempdir(prefix="pipenv", suffix="requirements")

    standard_requirements = tempfile.NamedTemporaryFile(
        prefix="pipenv-", suffix="-hashed-reqs.txt", dir=requirements_dir, delete=False
    )
    editable_requirements = tempfile.NamedTemporaryFile(
        prefix="pipenv-", suffix="-reqs.txt", dir=requirements_dir, delete=False
    )
    for requirement in deps:
        ignore_hash = ignore_hashes
        vcs_or_editable = (
            requirement.is_vcs
            or requirement.vcs
            or requirement.editable
            or (requirement.is_file_or_url and not requirement.hashes)
        )
        if vcs_or_editable:
            ignore_hash = True
        if requirement and vcs_or_editable:
            requirement.index = None

        line = requirement.line_instance.get_line(
            with_prefix=True,
            with_hashes=not ignore_hash,
            with_markers=True,
            as_list=False,
        )
        if project.s.is_verbose():
            click.echo(
                f"Writing supplied requirement line to temporary file: {line!r}",
                err=True,
            )
        target = editable_requirements if vcs_or_editable else standard_requirements
        target.write(line.encode())
        target.write(b"\n")
    standard_requirements.close()
    editable_requirements.close()

    cmds = []
    files = []
    standard_deps = list(
        filter(
            lambda d: not (
                d.is_vcs or d.vcs or d.editable or (d.is_file_or_url and not d.hashes)
            ),
            deps,
        )
    )
    if standard_deps:
        files.append(standard_requirements)
    editable_deps = list(
        filter(
            lambda d: d.is_vcs
            or d.vcs
            or d.editable
            or (d.is_file_or_url and not d.hashes),
            deps,
        )
    )
    if editable_deps:
        files.append(editable_requirements)
    for file in files:
        pip_command = [
            project_python(project, system=allow_global),
            get_runnable_pip(),
            "install",
        ]
        pip_args = get_pip_args(
            project,
            pre=project.settings.get("allow_prereleases", False),
            verbose=False,  # When True, the subprocess fails to recognize the EOF when reading stdout.
            upgrade=True,
            selective_upgrade=False,
            no_use_pep517=not use_pep517,
            no_deps=no_deps,
            extra_pip_args=extra_pip_args,
        )
        pip_command.extend(prepare_pip_source_args(sources))
        pip_command.extend(pip_args)
        pip_command.extend(["-r", normalize_path(file.name)])
        if project.s.is_verbose():
            msg = f"Install Phase: {'Standard Requirements' if file == standard_requirements else 'Editable Requirements'}"
            click.echo(
                click.style(msg, bold=True),
                err=True,
            )
            for requirement in (
                standard_deps if file == standard_requirements else editable_deps
            ):
                click.echo(
                    click.style(
                        f"Preparing Installation of {requirement.name!r}", bold=True
                    ),
                    err=True,
                )
            click.secho(f"$ {cmd_list_to_shell(pip_command)}", fg="cyan", err=True)
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
        c = subprocess_run(pip_command, block=False, capture_output=True, env=pip_config)
        if file == standard_requirements:
            c.deps = standard_deps
        else:
            c.deps = editable_deps
        c.env = pip_config
        cmds.append(c)
        if project.s.is_verbose():
            while True:
                line = c.stdout.readline()
                if not line:
                    break
                if "Ignoring" in line:
                    click.secho(line, fg="red", err=True)
                elif line:
                    click.secho(line, fg="yellow", err=True)
    return cmds


def pip_install(
    project,
    requirement=None,
    r=None,
    allow_global=False,
    ignore_hashes=False,
    no_deps=False,
    block=True,
    index=None,
    pre=False,
    dev=False,
    selective_upgrade=False,
    requirements_dir=None,
    extra_indexes=None,
    pypi_mirror=None,
    use_pep517=True,
    use_constraint=False,
    extra_pip_args: Optional[List] = None,
):
    piplogger = logging.getLogger("pipenv.patched.pip._internal.commands.install")
    trusted_hosts = get_trusted_hosts()
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

    r = write_requirement_to_file(
        project,
        requirement,
        requirements_dir=requirements_dir,
        include_hashes=not ignore_hashes,
    )
    sources = get_source_list(
        project,
        index,
        extra_indexes=extra_indexes,
        trusted_hosts=trusted_hosts,
        pypi_mirror=pypi_mirror,
    )
    source_names = {src.get("name") for src in sources}
    if not search_all_sources and requirement.index in source_names:
        sources = list(filter(lambda d: d.get("name") == requirement.index, sources))
    if r:
        with open(r, "r") as fh:
            if "--hash" not in fh.read():
                ignore_hashes = True
    if project.s.is_verbose():
        piplogger.setLevel(logging.WARN)
        if requirement:
            click.echo(
                click.style(f"Installing {requirement.name!r}", bold=True),
                err=True,
            )

    pip_command = [
        project_python(project, system=allow_global),
        get_runnable_pip(),
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
        extra_pip_args=extra_pip_args,
    )
    pip_command.extend(pip_args)
    if r:
        pip_command.extend(["-r", normalize_path(r)])
    elif line:
        pip_command.extend(line)
    if dev and use_constraint:
        default_constraints = get_constraints_from_deps(project.packages)
        constraint_filename = prepare_constraint_file(
            default_constraints,
            directory=requirements_dir,
            sources=None,
            pip_args=None,
        )
        pip_command.extend(["-c", normalize_path(constraint_filename)])
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


def get_pip_args(
    project,
    pre: bool = False,
    verbose: bool = False,
    upgrade: bool = False,
    require_hashes: bool = False,
    no_build_isolation: bool = False,
    no_use_pep517: bool = False,
    no_deps: bool = False,
    selective_upgrade: bool = False,
    src_dir: Optional[str] = None,
    extra_pip_args: Optional[List] = None,
) -> List[str]:
    arg_map = {
        "pre": ["--pre"],
        "verbose": ["--verbose"],
        "upgrade": ["--upgrade"],
        "require_hashes": ["--require-hashes"],
        "no_build_isolation": ["--no-build-isolation"],
        "no_use_pep517": ["--no-use-pep517"],
        "no_deps": ["--no-deps"],
        "selective_upgrade": [
            "--upgrade-strategy=only-if-needed",
            "--exists-action={}".format(project.s.PIP_EXISTS_ACTION or "i"),
        ],
        "src_dir": src_dir,
    }
    arg_set = ["--no-input"] if project.settings.get("disable_pip_input", True) else []
    for key in arg_map.keys():
        if key in locals() and locals().get(key):
            arg_set.extend(arg_map.get(key))
        elif key == "selective_upgrade" and not locals().get(key):
            arg_set.append("--exists-action=i")
    for extra_pip_arg in extra_pip_args:
        arg_set.append(extra_pip_arg)
    return list(dict.fromkeys(arg_set))


def get_trusted_hosts():
    try:
        return os.environ.get("PIP_TRUSTED_HOSTS", []).split(" ")
    except AttributeError:
        return []


def write_requirement_to_file(
    project: Project,
    requirement: Requirement,
    requirements_dir: Optional[str] = None,
    include_hashes: bool = True,
) -> str:
    if not requirements_dir:
        requirements_dir = create_tracked_tempdir(prefix="pipenv", suffix="requirements")
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
    f.write(line.encode())
    r = f.name
    f.close()
    return r
