# Copied from pip's vendoring process
# see https://github.com/pypa/pip/blob/95bcf8c5f6394298035a7332c441868f3b0169f4/tasks/__init__.py
from pathlib import Path

import invoke

from . import release, vendoring

ROOT = Path(".").parent.parent.absolute()

ns = invoke.Collection(vendoring, release, release.clean_mdchangelog)
