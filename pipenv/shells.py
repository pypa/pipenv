import os

from .environments import PIPENV_SHELL_EXPLICIT, PIPENV_SHELL
from .vendor import shellingham


class ShellDetectionFailure(shellingham.ShellDetectionFailure):
    pass


def _build_info(value):
    return (os.path.splitext(os.path.basename(value))[0], value)


def detect_info():
    if PIPENV_SHELL_EXPLICIT:
        return _build_info(PIPENV_SHELL_EXPLICIT)
    try:
        return shellingham.detect_shell()
    except (shellingham.ShellDetectionFailure, TypeError):
        if PIPENV_SHELL:
            return _build_info(PIPENV_SHELL)
    raise ShellDetectionFailure
