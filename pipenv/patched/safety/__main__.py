"""Allow safety to be executable through `python -m safety`."""
from __future__ import absolute_import

import sys


if __name__ == "__main__":  # pragma: no cover
    yaml_lib = "pipenv.patched.yaml{0}".format(sys.version_info[0])
    locals()[yaml_lib] = __import__(yaml_lib)
    sys.modules["yaml"] = sys.modules[yaml_lib]
    from safety.cli import cli
    cli(prog_name="safety")
