"""Read resources contained within a package."""

import sys

from ._common import (
    as_file, files,
    )

# For compatibility. Ref #88.
# Also requires hook-importlib_resources.py (Ref #101).
__import__('importlib_resources.trees')


__all__ = [
    'Package',
    'Resource',
    'ResourceReader',
    'as_file',
    'contents',
    'files',
    'is_resource',
    'open_binary',
    'open_text',
    'path',
    'read_binary',
    'read_text',
    ]


if sys.version_info >= (3,):
    from importlib_resources._py3 import (
        Package,
        Resource,
        contents,
        is_resource,
        open_binary,
        open_text,
        path,
        read_binary,
        read_text,
        )
    from importlib_resources.abc import ResourceReader
else:
    from importlib_resources._py2 import (
        contents,
        is_resource,
        open_binary,
        open_text,
        path,
        read_binary,
        read_text,
        )
    del __all__[:3]
