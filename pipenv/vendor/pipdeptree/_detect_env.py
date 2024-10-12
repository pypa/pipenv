from __future__ import annotations

import os
import platform
import subprocess  # noqa: S404
import sys
from pathlib import Path
from typing import Callable


def detect_active_interpreter() -> str:
    """
    Attempt to detect a venv, virtualenv, poetry, or conda environment by looking for certain markers.

    If it fails to find any, it will fail with a message.
    """
    detection_funcs: list[Callable[[], Path | None]] = [
        detect_venv_or_virtualenv_interpreter,
        detect_conda_env_interpreter,
        detect_poetry_env_interpreter,
    ]
    for detect in detection_funcs:
        path = detect()
        if not path:
            continue
        if not path.exists():
            break
        return str(path)

    print("Unable to detect virtual environment.", file=sys.stderr)  # noqa: T201
    raise SystemExit(1)


def detect_venv_or_virtualenv_interpreter() -> Path | None:
    # Both virtualenv and venv set this environment variable.
    env_var = os.environ.get("VIRTUAL_ENV")
    if not env_var:
        return None

    path = Path(env_var)
    path /= determine_bin_dir()

    file_name = determine_interpreter_file_name()
    return path / file_name if file_name else None


def determine_bin_dir() -> str:
    return "Scripts" if os.name == "nt" else "bin"


def detect_conda_env_interpreter() -> Path | None:
    # Env var mentioned in https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html#saving-environment-variables.
    env_var = os.environ.get("CONDA_PREFIX")
    if not env_var:
        return None

    path = Path(env_var)

    # On POSIX systems, conda adds the python executable to the /bin directory. On Windows, it resides in the parent
    # directory of /bin (i.e. the root directory).
    # See https://docs.anaconda.com/free/working-with-conda/configurations/python-path/#examples.
    if os.name == "posix":  # pragma: posix cover
        path /= "bin"

    file_name = determine_interpreter_file_name()

    return path / file_name if file_name else None


def detect_poetry_env_interpreter() -> Path | None:
    # poetry doesn't expose an environment variable like other implementations, so we instead use its CLI to snatch the
    # active interpreter.
    # See https://python-poetry.org/docs/managing-environments/#displaying-the-environment-information.
    try:
        result = subprocess.run(  # noqa: S603
            ("poetry", "env", "info", "--executable"),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        return None

    return Path(result.stdout.strip())


def determine_interpreter_file_name() -> str | None:
    impl_name_to_file_name_dict = {"CPython": "python", "PyPy": "pypy"}
    name = impl_name_to_file_name_dict.get(platform.python_implementation())
    if not name:
        return None
    if os.name == "nt":  # pragma: nt cover
        return name + ".exe"
    return name


__all__ = ["detect_active_interpreter"]
