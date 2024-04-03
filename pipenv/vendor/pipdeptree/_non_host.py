from __future__ import annotations

import os
import sys
from inspect import getsourcefile
from pathlib import Path
from shutil import copytree
from subprocess import call  # noqa: S404
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._cli import Options


def handle_non_host_target(args: Options) -> int | None:
    # if target is not current python re-invoke it under the actual host
    py_path = Path(args.python).absolute()
    if py_path != Path(sys.executable).absolute():
        # there's no way to guarantee that graphviz is available, so refuse
        if args.output_format:
            print(  # noqa: T201
                "graphviz functionality is not supported when querying non-host python",
                file=sys.stderr,
            )
            raise SystemExit(1)
        argv = sys.argv[1:]  # remove current python executable
        for py_at, value in enumerate(argv):
            if value == "--python":
                del argv[py_at]
                del argv[py_at]
            elif value.startswith("--python"):
                del argv[py_at]

        src = getsourcefile(sys.modules[__name__])
        assert src is not None
        our_root = Path(src).parent

        with TemporaryDirectory() as project:
            dest = Path(project)
            copytree(our_root, dest / "pipdeptree")
            # invoke from an empty folder to avoid cwd altering sys.path
            env = os.environ.copy()
            env["PYTHONPATH"] = project
            cmd = [str(py_path), "-m", "pipdeptree", *argv]
            return call(cmd, cwd=project, env=env)  # noqa: S603
    return None


__all__ = [
    "handle_non_host_target",
]
