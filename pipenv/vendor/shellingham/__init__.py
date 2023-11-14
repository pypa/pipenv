import importlib
import os

from ._core import ShellDetectionFailure


__version__ = "1.5.3"


def detect_shell(pid=None, max_depth=10):
    name = os.name
    try:
        impl = importlib.import_module(".{}".format(name), __name__)
    except ImportError:
        message = "Shell detection not implemented for {0!r}".format(name)
        raise RuntimeError(message)
    try:
        get_shell = impl.get_shell
    except AttributeError:
        raise RuntimeError("get_shell not implemented for {0!r}".format(name))
    shell = get_shell(pid, max_depth=max_depth)
    if shell:
        return shell
    raise ShellDetectionFailure()
