# -*- coding=utf-8 -*-

import functools
import os
import signal
import sys

import colorama
import cursor
import six

from .compat import to_native_string
from .termcolors import COLOR_MAP, COLORS, colored
from io import StringIO

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
        colorama.init()
        from .misc import decode_for_output
        self.text = to_native_string(decode_for_output(text))
        self.stdout = kwargs.get("stdout", sys.stdout)
        self.stderr = kwargs.get("stderr", sys.stderr)
        self.out_buff = StringIO()

    def __enter__(self):
        if self.text and self.text != "None":
            self.write_err(self.text)
        return self

    def __exit__(self, exc_type, exc_val, traceback):
        if exc_type:
            import traceback
            from .misc import decode_for_output
            self.write_err(decode_for_output(traceback.format_exception(*sys.exc_info())))
        self._close_output_buffer()
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

    def _close_output_buffer(self):
        if self.out_buff and not self.out_buff.closed:
            try:
                self.out_buff.close()
            except Exception:
                pass

    def fail(self, exitcode=1, text="FAIL"):
        from .misc import decode_for_output
        if text and text != "None":
            self.write_err(decode_for_output(text))
        self._close_output_buffer()

    def ok(self, text="OK"):
        if text and text != "None":
            self.stderr.write(self.text)
        self._close_output_buffer()
        return 0

    def write(self, text=None):
        from .misc import decode_for_output
        if text is None or isinstance(text, six.string_types) and text == "None":
            pass
        text = decode_for_output(text)
        self.stdout.write(decode_for_output("\r"))
        line = decode_for_output("{0}\n".format(text))
        self.stdout.write(line)
        self.stdout.write(CLEAR_LINE)

    def write_err(self, text=None):
        from .misc import decode_for_output
        if text is None or isinstance(text, six.string_types) and text == "None":
            pass
        text = decode_for_output(text)
        self.stderr.write(decode_for_output("\r"))
        line = decode_for_output("{0}\n".format(text))
        self.stderr.write(line)
        self.stderr.write(CLEAR_LINE)

    @staticmethod
    def _hide_cursor():
        pass

    @staticmethod
    def _show_cursor():
        pass


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
        colorama.init()
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
        start_text = kwargs.pop("start_text", None)
        _text = kwargs.pop("text", "Running...")
        kwargs["text"] = start_text if start_text is not None else _text
        kwargs["sigmap"] = sigmap
        kwargs["spinner"] = getattr(Spinners, spinner_name, "")
        self.stdout = kwargs.pop("stdout", sys.stdout)
        self.stderr = kwargs.pop("stderr", sys.stderr)
        self.out_buff = StringIO()
        super(VistirSpinner, self).__init__(*args, **kwargs)
        self.is_dummy = bool(yaspin is None)

    def ok(self, text="OK"):
        """Set Ok (success) finalizer to a spinner."""
        self._text = None

        _text = text if text else "OK"
        self._freeze(_text)

    def fail(self, text="FAIL"):
        """Set fail finalizer to a spinner."""
        self._text = None

        _text = text if text else "FAIL"
        self._freeze(_text)

    def write(self, text):
        from .misc import to_text
        sys.stdout.write("\r")
        self.stdout.write(CLEAR_LINE)
        if text is None:
            text = ""
        text = to_native_string("{0}\n".format(text))
        sys.stdout.write(text)
        self.out_buff.write(to_text(text))

    def write_err(self, text):
        """Write error text in the terminal without breaking the spinner."""
        from .misc import to_text

        self.stderr.write("\r")
        self.stderr.write(CLEAR_LINE)
        if text is None:
            text = ""
        text = to_native_string("{0}\n".format(text))
        self.stderr.write(text)
        self.out_buff.write(to_text(text))

    def _freeze(self, final_text):
        """Stop spinner, compose last frame and 'freeze' it."""
        if not final_text:
            final_text = ""
        text = to_native_string(final_text)
        self._last_frame = self._compose_out(text, mode="last")

        # Should be stopped here, otherwise prints after
        # self._freeze call will mess up the spinner
        self.stop()
        self.stdout.write(self._last_frame)

    def stop(self, *args, **kwargs):
        if self.stderr and self.stderr != sys.stderr:
            self.stderr.close()
        if self.stdout and self.stdout != sys.stdout:
            self.stdout.close()
        self.out_buff.close()
        super(VistirSpinner, self).stop(*args, **kwargs)

    def _compose_color_func(self):
        fn = functools.partial(
            colored,
            color=self._color,
            on_color=self._on_color,
            attrs=list(self._attrs),
        )
        return fn

    def _compose_out(self, frame, mode=None):
        # Ensure Unicode input

        frame = to_native_string(frame)
        if self._text is None:
            self._text = ""
        text = to_native_string(self._text)
        if self._color_func is not None:
            frame = self._color_func(frame)
        if self._side == "right":
            frame, text = text, frame
        # Mode
        if not mode:
            out = to_native_string("\r{0} {1}".format(frame, text))
        else:
            out = to_native_string("{0} {1}\n".format(frame, text))
        return out

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
    use_yaspin = kwargs.pop("use_yaspin", nospin)
    if nospin:
        return DummySpinner(*args, **kwargs)
    return VistirSpinner(*args, **kwargs)
