"""
Partial backport of python 3's shlex module.

Include's only `shlex.quote()` for backwards compatible functionality.
"""

__all__ = ['quote']

from .shlex import quote
