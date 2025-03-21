from __future__ import annotations


class InvalidPythonVersion(Exception):
    """Raised when parsing an invalid python version"""

    pass


class PythonNotFound(Exception):
    """Raised when a requested Python version is not found"""

    pass
