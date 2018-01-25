"""
Partial backport of Python 3.6's weakref module:

    finalize (new in Python 3.4)

Backport modifications are marked with "XXX backport".
"""
__all__ = ["finalize"]

from .weakref import finalize
