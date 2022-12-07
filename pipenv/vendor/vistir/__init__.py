# -*- coding=utf-8 -*-
import importlib

__newpaths = {
    'create_spinner': 'vistir.spin',
    'cd': 'vistir.contextmanagers',
    'atomic_open_for_write': 'vistir.contextmanagers',
    'open_file': 'vistir.contextmanagers',
    'replaced_stream': 'vistir.contextmanagers',
    'replaced_streams': 'vistir.contextmanagers',
    'spinner': 'vistir.contextmanagers',
    'temp_environ': 'vistir.contextmanagers',
    'temp_path': 'vistir.contextmanagers',
    'hide_cursor': 'vistir.cursor',
    'show_cursor': 'vistir.cursor',
    'StreamWrapper': 'vistir.misc',
    'chunked':'vistir.misc',
    'decode_for_output': 'vistir.misc',
    'divide': 'vistir.misc',
    'get_wrapped_stream': 'vistir.misc',
    'load_path': 'vistir.misc',
    'partialclass': 'vistir.misc',
    'run': 'vistir.misc',
    'shell_escape': 'vistir.misc',
    'take': 'vistir.misc',
    'to_bytes': 'vistir.misc',
    'to_text': 'vistir.misc',
    'create_tracked_tempdir': 'vistir.path',
    'create_tracked_tempfile': 'vistir.path',
    'mkdir_p': 'vistir.path',
    'rmtree': 'vistir.path',
}

from warnings import warn

def __getattr__(name):
    warn((f"Importing {name} directly from vistir is deprecated.\nUse 'from {__newpaths[name]} import {name}' instead.\n"
          "This import path will be removed in vistir 0.8"),
         DeprecationWarning)
    return getattr(importlib.import_module(__newpaths[name]), name)

__version__ = "0.7.5"
