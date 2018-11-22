# -*- coding=utf-8 -*-

import functools
import os
import signal
import sys
import threading
import time

import colorama
import cursor
import six

from .compat import to_native_string
from .termcolors import COLOR_MAP, COLORS, colored, DISABLE_COLORS
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
        super(DummySpinner, self).__init__()
        if DISABLE_COLORS:
            colorama.init()
        from .misc import decode_for_output
        self.text = to_native_string(decode_for_output(text)) if text else ""
        self.stdout = kwargs.get("stdout", sys.stdout)
        self.stderr = kwargs.get("stderr", sys.stderr)
        self.out_buff = StringIO()
        self.write_to_stdout = kwargs.get("write_to_stdout", False)

    def __enter__(self):
        if self.text and self.text != "None":
            if self.write_to_stdout:
                self.write(self.text)
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
            if self.write_to_stdout:
                self.write(decode_for_output(text))
            else:
                self.write_err(decode_for_output(text))
        self._close_output_buffer()

    def ok(self, text="OK"):
        if text and text != "None":
            if self.write_to_stdout:
                self.stdout.write(self.text)
            else:
                self.stderr.write(self.text)
        self._close_output_buffer()
        return 0

    def hide_and_write(self, text, target=None):
        if not target:
            target = self.stdout
        from .misc import decode_for_output
        if text is None or isinstance(text, six.string_types) and text == "None":
            pass
        target.write(decode_for_output("\r"))
        self._hide_cursor(target=target)
        target.write(decode_for_output("{0}\n".format(text)))
        target.write(CLEAR_LINE)
        self._show_cursor(target=target)

    def write(self, text=None):
        if not self.write_to_stdout:
            return self.write_err(text)
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
    def _hide_cursor(target=None):
        pass

    @staticmethod
    def _show_cursor(target=None):
        pass


base_obj = yaspin.core.Yaspin if yaspin is not None else DummySpinner


class VistirSpinner(base_obj):
    "A spinner class for handling spinners on windows and posix."

    def __init__(self, *args, **kwargs):
        """
        Get a spinner object or a dummy spinner to wrap a context.

        Keyword Arguments:
        :param str spinner_name: A spinner type e.g. "dots" or "bouncingBar" (default: {"bouncingBar"})
        :param str start_text: Text to start off the spinner with (default: {None})
        :param dict handler_map: Handler map for signals to be handled gracefully (default: {None})
        :param bool nospin: If true, use the dummy spinner (default: {False})
        :param bool write_to_stdout: Writes to stdout if true, otherwise writes to stderr (default: True)
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
        write_to_stdout = kwargs.pop("write_to_stdout", True)
        self.stdout = kwargs.pop("stdout", sys.stdout)
        self.stderr = kwargs.pop("stderr", sys.stderr)
        self.out_buff = StringIO()
        self.write_to_stdout = write_to_stdout
        self.is_dummy = bool(yaspin is None)
        super(VistirSpinner, self).__init__(*args, **kwargs)

    def ok(self, text="OK", err=False):
        """Set Ok (success) finalizer to a spinner."""
        # Do not display spin text for ok state
        self._text = None

        _text = text if text else "OK"
        err = err or not self.write_to_stdout
        self._freeze(_text, err=err)

    def fail(self, text="FAIL", err=False):
        """Set fail finalizer to a spinner."""
        # Do not display spin text for fail state
        self._text = None

        _text = text if text else "FAIL"
        err = err or not self.write_to_stdout
        self._freeze(_text, err=err)

    def hide_and_write(self, text, target=None):
        if not target:
            target = self.stdout
        from .misc import decode_for_output
        if text is None or isinstance(text, six.string_types) and text == "None":
            pass
        target.write(decode_for_output("\r"))
        self._hide_cursor(target=target)
        target.write(decode_for_output("{0}\n".format(text)))
        target.write(CLEAR_LINE)
        self._show_cursor(target=target)

    def write(self, text):
        if not self.write_to_stdout:
            return self.write_err(text)
        from .misc import to_text
        sys.stdout.write("\r")
        self.stdout.write(CLEAR_LINE)
        if text is None:
            text = ""
        text = to_native_string("{0}\n".format(text))
        self.stdout.write(text)
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

    def start(self):
        if self._sigmap:
            self._register_signal_handlers()

        target = self.stdout if self.write_to_stdout else self.stderr
        if target.isatty():
            self._hide_cursor(target=target)

        self._stop_spin = threading.Event()
        self._hide_spin = threading.Event()
        self._spin_thread = threading.Thread(target=self._spin)
        self._spin_thread.start()

    def stop(self):
        if self._dfl_sigmap:
            # Reset registered signal handlers to default ones
            self._reset_signal_handlers()

        if self._spin_thread:
            self._stop_spin.set()
            self._spin_thread.join()

        target = self.stdout if self.write_to_stdout else self.stderr
        if target.isatty():
            target.write("\r")

        if self.write_to_stdout:
            self._clear_line()
        else:
            self._clear_err()

        if target.isatty():
            self._show_cursor(target=target)
        if self.stderr and self.stderr != sys.stderr:
            self.stderr.close()
        if self.stdout and self.stdout != sys.stdout:
            self.stdout.close()
        self.out_buff.close()

    def _freeze(self, final_text, err=False):
        """Stop spinner, compose last frame and 'freeze' it."""
        if not final_text:
            final_text = ""
        text = to_native_string(final_text)
        self._last_frame = self._compose_out(text, mode="last")

        # Should be stopped here, otherwise prints after
        # self._freeze call will mess up the spinner
        self.stop()
        if err or not self.write_to_stdout:
            self.stderr.write(self._last_frame)
        else:
            self.stdout.write(self._last_frame)

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

    def _spin(self):
        target = self.stdout if self.write_to_stdout else self.stderr
        clear_fn = self._clear_line if self.write_to_stdout else self._clear_err
        while not self._stop_spin.is_set():

            if self._hide_spin.is_set():
                # Wait a bit to avoid wasting cycles
                time.sleep(self._interval)
                continue

            # Compose output
            spin_phase = next(self._cycle)
            out = self._compose_out(spin_phase)

            # Write
            target.write(out)
            clear_fn()
            target.flush()

            # Wait
            time.sleep(self._interval)
            target.write("\b")

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
    def _hide_cursor(target=None):
        if not target:
            target = sys.stdout
        cursor.hide(stream=target)

    @staticmethod
    def _show_cursor(target=None):
        if not target:
            target = sys.stdout
        cursor.show(stream=target)

    @staticmethod
    def _clear_err():
        sys.stderr.write(CLEAR_LINE)

    @staticmethod
    def _clear_line():
        sys.stdout.write(CLEAR_LINE)


def create_spinner(*args, **kwargs):
    nospin = kwargs.pop("nospin", False)
    use_yaspin = kwargs.pop("use_yaspin", not nospin)
    if nospin or not use_yaspin:
        return DummySpinner(*args, **kwargs)
    return VistirSpinner(*args, **kwargs)
