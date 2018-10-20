# -*- coding=utf-8 -*-
import os
import signal
import sys

from .termcolors import colored
from .compat import fs_str

import cursor
import functools
try:
    import yaspin
except ImportError:
    yaspin = None
    Spinners = None
else:
    from yaspin.spinners import Spinners

handler = None
if yaspin and os.name == "nt":
    handler = yaspin.signal_handlers.default_handler
elif yaspin and os.name != "nt":
    handler = yaspin.signal_handlers.fancy_handler

CLEAR_LINE = chr(27) + "[K"


class DummySpinner(object):
    def __init__(self, text="", **kwargs):
        self.text = text

    def __enter__(self):
        if self.text:
            self.write(self.text)
        return self

    def __exit__(self, exc_type, exc_val, traceback):
        if not exc_type:
            self.ok()
        else:
            self.write_err(traceback)
        return False

    def fail(self, exitcode=1, text=None):
        if text:
            self.write_err(text)
        raise SystemExit(exitcode, text)

    def ok(self, text=None):
        if text:
            self.write(self.text)
        return 0

    def write(self, text=None):
        if text:
            line = fs_str("{0}\n".format(text))
            sys.stdout.write(line)

    def write_err(self, text=None):
        if text:
            line = fs_str("{0}\n".format(text))
            sys.stderr.write(line)


base_obj = yaspin.core.Yaspin if yaspin is not None else DummySpinner


class VistirSpinner(base_obj):
    def __init__(self, *args, **kwargs):
        """Get a spinner object or a dummy spinner to wrap a context.

        Keyword Arguments:
        :param str spinner_name: A spinner type e.g. "dots" or "bouncingBar" (default: {"bouncingBar"})
        :param str start_text: Text to start off the spinner with (default: {None})
        :param dict handler_map: Handler map for signals to be handled gracefully (default: {None})
        :param bool nospin: If true, use the dummy spinner (default: {False})
        """

        self.handler = handler
        sigmap = {}
        if handler:
            sigmap.update({
                signal.SIGINT: handler,
                signal.SIGTERM: handler
            })
        handler_map = kwargs.pop("handler_map", {})
        if os.name == "nt":
            sigmap[signal.SIGBREAK] = handler
        else:
            sigmap[signal.SIGALRM] = handler
        if handler_map:
            sigmap.update(handler_map)
        spinner_name = kwargs.pop("spinner_name", "bouncingBar")
        text = kwargs.pop("start_text", "") + " " + kwargs.pop("text", "")
        if not text:
            text = "Running..."
        kwargs["sigmap"] = sigmap
        kwargs["spinner"] = getattr(Spinners, spinner_name, Spinners.bouncingBar)
        super(VistirSpinner, self).__init__(*args, **kwargs)
        self.is_dummy = bool(yaspin is None)

    def fail(self, exitcode=1, *args, **kwargs):
        super(VistirSpinner, self).fail(**kwargs)

    def ok(self, *args, **kwargs):
        super(VistirSpinner, self).ok(*args, **kwargs)

    def write(self, *args, **kwargs):
        super(VistirSpinner, self).write(*args, **kwargs)

    def write_err(self, text):
        """Write error text in the terminal without breaking the spinner."""

        sys.stderr.write("\r")
        self._clear_err()
        text = fs_str("{0}\n".format(text))
        sys.stderr.write(text)

    def _compose_color_func(self):
        fn = functools.partial(
            colored,
            color=self._color,
            on_color=self._on_color,
            attrs=list(self._attrs),
        )
        return fn

    @staticmethod
    def _hide_cursor():
        cursor.hide()

    @staticmethod
    def _show_cursor():
        cursor.show()

    @staticmethod
    def _clear_err():
        sys.stderr.write(CLEAR_LINE)

    @staticmethod
    def _clear_line():
        sys.stdout.write(CLEAR_LINE)


def create_spinner(*args, **kwargs):
    nospin = kwargs.pop("nospin", False)
    if nospin:
        return DummySpinner(*args, **kwargs)
    return VistirSpinner(*args, **kwargs)
