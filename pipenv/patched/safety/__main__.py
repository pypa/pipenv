"""Allow safety to be executable through `python -m safety`."""
from __future__ import absolute_import

from .cli import cli


if __name__ == "__main__":  # pragma: no cover
    cli(prog_name="safety")
