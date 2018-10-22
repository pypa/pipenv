# -*- coding=utf-8 -*-
import os
import signal
import sys

from .termcolors import colored, COLORS
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
    from yaspin.constants import COLOR_MAP

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

    def __getattr__(self, k):
        try:
            retval = super(DummySpinner, self).__getattribute__(k)
        except AttributeError:
            if k in COLOR_MAP.keys() or k.upper() in COLORS:
                return self
            raise
        else:
            return retval

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

    def _register_signal_handlers(self):
        # SIGKILL cannot be caught or ignored, and the receiving
        # process cannot perform any clean-up upon receiving this
        # signal.
        try:
            if signal.SIGKILL in self._sigmap.keys():
                raise ValueError(
                    "Trying to set handler for SIGKILL signal. "
                    "SIGKILL cannot be cought or ignored in POSIX systems."
                )
        except AttributeError:
            pass

        for sig, sig_handler in self._sigmap.items():
            # A handler for a particular signal, once set, remains
            # installed until it is explicitly reset. Store default
            # signal handlers for subsequent reset at cleanup phase.
            dfl_handler = signal.getsignal(sig)
            self._dfl_sigmap[sig] = dfl_handler

            # ``signal.SIG_DFL`` and ``signal.SIG_IGN`` are also valid
            # signal handlers and are not callables.
            if callable(sig_handler):
                # ``signal.signal`` accepts handler function which is
                # called with two arguments: signal number and the
                # interrupted stack frame. ``functools.partial`` solves
                # the problem of passing spinner instance into the handler
                # function.
                sig_handler = functools.partial(sig_handler, spinner=self)

            signal.signal(sig, sig_handler)

    def _reset_signal_handlers(self):
        for sig, sig_handler in self._dfl_sigmap.items():
            signal.signal(sig, sig_handler)

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
