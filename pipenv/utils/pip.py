import os
import tempfile
from pathlib import Path
from typing import List, Optional

from pipenv.patched.pip._internal.build_env import get_runnable_pip
from pipenv.utils import err
from pipenv.utils.fileutils import create_tracked_tempdir, normalize_path
from pipenv.utils.indexes import prepare_pip_source_args
from pipenv.utils.internet import (
    _strip_credentials_from_url,
    write_credentials_netrc,
)
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

    # Build per-invocation pip config values that are constant across all
    # file-based pip subprocesses.  In particular, write the temporary netrc
    # file *once* here so that concurrent subprocesses (hashed reqs + editable
    # reqs) all read the same stable file rather than racing to rewrite it.
    # See GHSA-8xgg-v3jj-95m2.
    cache_dir = Path(project.s.PIPENV_CACHE_DIR)
    default_exists_action = "w"
    exists_action = project.s.PIP_EXISTS_ACTION or default_exists_action
    # Validate PIP_EXISTS_ACTION — pip only accepts s/i/w/b/a (#5063).
    _valid_exists_actions = {"s", "i", "w", "b", "a"}
    if exists_action not in _valid_exists_actions:
        err.print(
            f"[yellow]Warning:[/yellow] PIP_EXISTS_ACTION=[cyan]{exists_action!r}[/cyan] "
            f"is not a valid pip exists-action. "
            f"Valid values are: {', '.join(sorted(_valid_exists_actions))}. "
            "Falling back to [cyan]'w'[/cyan] (wipe)."
        )
        exists_action = default_exists_action
    # Suppress pip.conf index configuration so that only Pipfile [[source]]
    # entries are used.  This prevents pip.conf extra-index-url (e.g.
    # piwheels) from injecting indexes at install time that were not
    # declared in the Pipfile, which would bypass pipenv's index safety
    # model and cause hash-mismatch errors.
    # Users who need a custom index (e.g. piwheels) should declare it as a
    # [[source]] in their Pipfile.
    base_pip_config = {
        "PIP_CACHE_DIR": cache_dir.as_posix(),
        "PIP_WHEEL_DIR": cache_dir.joinpath("wheels").as_posix(),
        "PIP_DESTINATION_DIR": cache_dir.joinpath("pkgs").as_posix(),
        "PIP_EXISTS_ACTION": exists_action,
        "PIP_CONFIG_FILE": os.devnull,
        "PATH": os.environ.get("PATH"),
    }
    # Pass through keyring provider so that credential managers
    # (e.g. Windows Credential Manager) work during install.
    # See https://github.com/pypa/pipenv/issues/5715
    keyring_provider = project.s.PIPENV_KEYRING_PROVIDER or os.environ.get(
        "PIP_KEYRING_PROVIDER"
    )
    if keyring_provider:
        base_pip_config["PIP_KEYRING_PROVIDER"] = keyring_provider
    # When installing to the system (--system), pass through PIP_BREAK_SYSTEM_PACKAGES
    # to support PEP 668 externally-managed environments (e.g. Ubuntu 23.04+, Debian 12+).
    # This can be enabled via PIPENV_BREAK_SYSTEM_PACKAGES=1 or PIP_BREAK_SYSTEM_PACKAGES=1.
    if allow_global:
        break_system = project.s.PIPENV_BREAK_SYSTEM_PACKAGES or os.environ.get(
            "PIP_BREAK_SYSTEM_PACKAGES"
        )
        if break_system:
            base_pip_config["PIP_BREAK_SYSTEM_PACKAGES"] = "1"
        # Pass through PIP_IGNORE_INSTALLED and PIP_USER if set in the environment
        for env_key in ("PIP_IGNORE_INSTALLED", "PIP_USER"):
            env_val = os.environ.get(env_key)
            if env_val:
                base_pip_config[env_key] = env_val
    if sources:
        # Strip embedded credentials from index URLs we expose via
        # environment variables.  PIP_INDEX_URL / PIP_EXTRA_INDEX_URL
        # are still passed for parity with the CLI args, but the actual
        # credentials are delivered out-of-band through the temporary
        # netrc written below.  See GHSA-8xgg-v3jj-95m2.
        primary_url, _ = _strip_credentials_from_url(sources[0].get("url", ""))
        base_pip_config["PIP_INDEX_URL"] = primary_url or ""
        if len(sources) > 1:
            base_pip_config["PIP_EXTRA_INDEX_URL"] = " ".join(
                (_strip_credentials_from_url(s.get("url", ""))[0] or "")
                for s in sources[1:]
            )
        netrc_path = write_credentials_netrc(sources, requirements_dir)
        if netrc_path:
            base_pip_config["NETRC"] = netrc_path
    if src_dir:
        if project.s.is_verbose():
            err.print(f"Using source directory: {src_dir!r}")
        base_pip_config.update({"PIP_SRC": src_dir})

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
        pip_config = dict(base_pip_config)
        c = subprocess_run(pip_command, block=False, capture_output=True, env=pip_config)
        c.env = pip_config
        # Attach the deps to this subprocess results
        # when pip commands fails, `_cleanup_procs()` raises `InstallError`
        # and tries to include which dependecies/requirements were being installed
        # `_cleanup_procs()` reads `c.deps`, but previously `c.deps` was never set
        # so the error message often lacked useful context
        # This allows us to show clear "Couldn't install package(s): ......." message
        c.deps = list(deps)

        # Optional: we can do "pretty" msgs for display purposes
        # (e.g., strip whitespaces)
        # c.deps_pretty = [d.strip() for d in deps if d and d.strip()]

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
    return os.environ.get("PIP_TRUSTED_HOSTS", "").split(" ")
