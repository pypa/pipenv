# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import ctypes
import os
import sys

__all__ = ["hide_cursor", "show_cursor"]


class CONSOLE_CURSOR_INFO(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_int), ("bVisible", ctypes.c_int)]


WIN_STDERR_HANDLE_ID = ctypes.c_ulong(-12)
WIN_STDOUT_HANDLE_ID = ctypes.c_ulong(-11)


def get_stream_handle(stream=sys.stdout):
    """
    Get the OS appropriate handle for the corresponding output stream.

    :param str stream: The the stream to get the handle for
    :return: A handle to the appropriate stream, either a ctypes buffer
             or **sys.stdout** or **sys.stderr**.
    """
    handle = stream
    if os.name == "nt":
        from ctypes import windll

        handle_id = WIN_STDOUT_HANDLE_ID
        handle = windll.kernel32.GetStdHandle(handle_id)
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
        from ctypes import windll

        cursor_info = CONSOLE_CURSOR_INFO()
        windll.kernel32.GetConsoleCursorInfo(handle, ctypes.byref(cursor_info))
        cursor_info.visible = False
        windll.kernel32.SetConsoleCursorInfo(handle, ctypes.byref(cursor_info))
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
        from ctypes import windll

        cursor_info = CONSOLE_CURSOR_INFO()
        windll.kernel32.GetConsoleCursorInfo(handle, ctypes.byref(cursor_info))
        cursor_info.visible = True
        windll.kernel32.SetConsoleCursorInfo(handle, ctypes.byref(cursor_info))
    else:
        handle.write("\033[?25h")
        handle.flush()
