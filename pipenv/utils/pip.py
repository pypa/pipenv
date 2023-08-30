import os
import tempfile
from pathlib import Path
from typing import List, Optional

from pipenv.patched.pip._internal.build_env import get_runnable_pip
from pipenv.utils import err
from pipenv.utils.fileutils import create_tracked_tempdir, normalize_path
from pipenv.utils.indexes import prepare_pip_source_args
from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import cmd_list_to_shell, project_python


def pip_install_deps(
    project,
    deps,
    sources,
    allow_global=False,
    ignore_hashes=False,
    no_deps=False,
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

    for pip_line in deps:
        ignore_hash = ignore_hashes or "--hash" not in pip_line

        if project.s.is_verbose():
            err.print(
                f"Writing supplied requirement line to temporary file: {pip_line!r}"
            )
        target = editable_requirements if ignore_hash else standard_requirements
        target.write(pip_line.encode())
        target.write(b"\n")

    standard_requirements.close()
    editable_requirements.close()

    cmds = []
    files = []
    for pip_line in deps:
        if "--hash" in pip_line and standard_requirements not in files:
            files.append(standard_requirements)
        elif editable_requirements not in files:
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
            no_use_pep517=not use_pep517,
            no_deps=no_deps,
            extra_pip_args=extra_pip_args,
        )
        pip_command.extend(prepare_pip_source_args(sources))
        pip_command.extend(pip_args)
        pip_command.extend(["-r", normalize_path(file.name)])
        if project.s.is_verbose():
            msg = f"Install Phase: {'Standard Requirements' if file == standard_requirements else 'Editable Requirements'}"
            err.print(msg, style="bold")
            for pip_line in deps:
                err.print(f"Preparing Installation of {pip_line!r}", style="bold")
            err.print(f"$ {cmd_list_to_shell(pip_command)}", style="cyan")
        cache_dir = Path(project.s.PIPENV_CACHE_DIR)
        default_exists_action = "w"
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
                err.print(f"Using source directory: {src_dir!r}")
            pip_config.update({"PIP_SRC": src_dir})
        c = subprocess_run(pip_command, block=False, capture_output=True, env=pip_config)
        c.env = pip_config
        cmds.append(c)
        if project.s.is_verbose():
            while True:
                line = c.stdout.readline()
                if not line:
                    break
                if "Ignoring" in line:
                    err.print(line, style="red")
                elif line:
                    err.print(line, style="yellow")
    return cmds


def get_pip_args(
    project,
    pre: bool = False,
    verbose: bool = False,
    upgrade: bool = False,
    require_hashes: bool = False,
    no_build_isolation: bool = False,
    no_use_pep517: bool = False,
    no_deps: bool = False,
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
        "src_dir": src_dir,
    }
    arg_set = ["--no-input"] if project.settings.get("disable_pip_input", True) else []
    for key in arg_map:
        if key in locals() and locals().get(key):
            arg_set.extend(arg_map.get(key))
    arg_set += extra_pip_args or []
    return list(dict.fromkeys(arg_set))


def get_trusted_hosts():
    try:
        return os.environ.get("PIP_TRUSTED_HOSTS", []).split(" ")
    except AttributeError:
        return []
