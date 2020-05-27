# -*- coding=utf-8 -*-
from __future__ import absolute_import, unicode_literals

from .compat import (
    NamedTemporaryFile,
    StringIO,
    TemporaryDirectory,
    partialmethod,
    to_native_string,
)
from .contextmanagers import (
    atomic_open_for_write,
    cd,
    open_file,
    replaced_stream,
    replaced_streams,
    spinner,
    temp_environ,
    temp_path,
)
from .cursor import hide_cursor, show_cursor
from .misc import (
    StreamWrapper,
    chunked,
    decode_for_output,
    divide,
    get_wrapped_stream,
    load_path,
    partialclass,
    run,
    shell_escape,
    take,
    to_bytes,
    to_text,
)
from .path import create_tracked_tempdir, create_tracked_tempfile, mkdir_p, rmtree
from .spin import create_spinner

__version__ = "0.5.2"


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
    "StringIO",
    "get_wrapped_stream",
    "StreamWrapper",
    "replaced_stream",
    "replaced_streams",
    "show_cursor",
    "hide_cursor",
]
