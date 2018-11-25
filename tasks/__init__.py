# -*- coding=utf-8 -*-
# Copyied from pip's vendoring process
# see https://github.com/pypa/pip/blob/95bcf8c5f6394298035a7332c441868f3b0169f4/tasks/__init__.py
import invoke
import re

from . import vendoring, release
from .vendoring import vendor_passa
from pathlib import Path

ROOT = Path(".").parent.parent.absolute()


ns = invoke.Collection(vendoring, release, release.clean_mdchangelog, vendor_passa.vendor_passa)
