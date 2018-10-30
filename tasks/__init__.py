# -*- coding=utf-8 -*-
# Copyied from pip's vendoring process
# see https://github.com/pypa/pip/blob/95bcf8c5f6394298035a7332c441868f3b0169f4/tasks/__init__.py
import invoke
import re

from . import vendoring, release
from .vendoring import vendor_passa
from pathlib import Path

ROOT = Path(".").parent.parent.absolute()


@invoke.task
def clean_mdchangelog(ctx):
    changelog = ROOT / "CHANGELOG.md"
    content = changelog.read_text()
    content = re.sub(r"([^\n]+)\n?\s+\[[\\]+(#\d+)\]\(https://github\.com/pypa/[\w\-]+/issues/\d+\)", r"\1 \2", content, flags=re.MULTILINE)
    changelog.write_text(content)


ns = invoke.Collection(vendoring, release, clean_mdchangelog, vendor_passa.vendor_passa)
