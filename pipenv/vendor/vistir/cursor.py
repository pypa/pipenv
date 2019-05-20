# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import os
import sys

__all__ = ["hide_cursor", "show_cursor", "get_stream_handle"]


def get_stream_handle(stream=sys.stdout):
    """
    Get the OS appropriate handle for the corresponding output stream.

    :param str stream: The the stream to get the handle for
    :return: A handle to the appropriate stream, either a ctypes buffer
             or **sys.stdout** or **sys.stderr**.
    """
    handle = stream
    if os.name == "nt":
        from ._winconsole import get_stream_handle as get_win_stream_handle

        return get_win_stream_handle(stream)
    return handle


def hide_cursor(stream=sys.stdout):
    """
    Hide the console cursor on the given stream

    :param stream: The name of the stream to get the handle for
    :return: None
    :rtype: None
    """

    handle = get_stream_handle(stream=stream)
    if os.name == "nt":
        from ._winconsole import hide_cursor

        hide_cursor()
    else:
        handle.write("\033[?25l")
        handle.flush()


def show_cursor(stream=sys.stdout):
    """
    Show the console cursor on the given stream

    :param stream: The name of the stream to get the handle for
    :return: None
    :rtype: None
    """

    handle = get_stream_handle(stream=stream)
    if os.name == "nt":
        from ._winconsole import show_cursor

        show_cursor()
    else:
        handle.write("\033[?25h")
        handle.flush()
