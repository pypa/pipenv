# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

from .compat import (
    NamedTemporaryFile,
    TemporaryDirectory,
    partialmethod,
    to_native_string,
)
from .contextmanagers import (
    atomic_open_for_write,
    cd,
    open_file,
    temp_environ,
    temp_path,
    spinner,
)
from .misc import (
    load_path,
    partialclass,
    run,
    shell_escape,
    decode_for_output,
    to_text,
    to_bytes,
    take,
    chunked,
    divide,
)
from .path import mkdir_p, rmtree, create_tracked_tempdir, create_tracked_tempfile
from .spin import VistirSpinner, create_spinner


__version__ = "0.2.4"


__all__ = [
    "shell_escape",
    "load_path",
    "run",
    "partialclass",
    "temp_environ",
    "temp_path",
    "cd",
    "atomic_open_for_write",
    "open_file",
    "rmtree",
    "mkdir_p",
    "TemporaryDirectory",
    "NamedTemporaryFile",
    "partialmethod",
    "spinner",
    "VistirSpinner",
    "create_spinner",
    "create_tracked_tempdir",
    "create_tracked_tempfile",
    "to_native_string",
    "decode_for_output",
    "to_text",
    "to_bytes",
    "take",
    "chunked",
    "divide",
]
