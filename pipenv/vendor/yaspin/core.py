# -*- coding: utf-8 -*-

"""
yaspin.yaspin
~~~~~~~~~~~~~

A lightweight terminal spinner.
"""

from __future__ import absolute_import

import functools
import itertools
import signal
import sys
import threading
import time

import colorama
import cursor

from .base_spinner import default_spinner
from .compat import PY2, basestring, builtin_str, bytes, iteritems, str
from .constants import COLOR_ATTRS, COLOR_MAP, ENCODING, SPINNER_ATTRS
from .helpers import to_unicode
from .termcolor import colored


colorama.init()


class Yaspin(object):
    """Implements a context manager that spawns a thread
    to write spinner frames into a tty (stdout) during
    context execution.
    """

    # When Python finds its output attached to a terminal,
    # it sets the sys.stdout.encoding attribute to the terminal's encoding.
    # The print statement's handler will automatically encode unicode
    # arguments into bytes.
    #
    # In Py2 when piping or redirecting output, Python does not detect
    # the desired character set of the output, it sets sys.stdout.encoding
    # to None, and print will invoke the default "ascii" codec.
    #
    # Py3 invokes "UTF-8" codec by default.
    #
    # Thats why in Py2, output should be encoded manually with desired
    # encoding in order to support pipes and redirects.

    def __init__(
        self,
        spinner=None,
        text="",
        color=None,
        on_color=None,
        attrs=None,
        reversal=False,
        side="left",
        sigmap=None,
    ):
        # Spinner
        self._spinner = self._set_spinner(spinner)
        self._frames = self._set_frames(self._spinner, reversal)
        self._interval = self._set_interval(self._spinner)
        self._cycle = self._set_cycle(self._frames)

        # Color Specification
        self._color = self._set_color(color) if color else color
        self._on_color = self._set_on_color(on_color) if on_color else on_color
        self._attrs = self._set_attrs(attrs) if attrs else set()
        self._color_func = self._compose_color_func()

        # Other
        self._text = self._set_text(text)
        self._side = self._set_side(side)
        self._reversal = reversal

        # Helper flags
        self._stop_spin = None
        self._hide_spin = None
        self._spin_thread = None
        self._last_frame = None

        # Signals

        # In Python 2 signal.SIG* are of type int.
        # In Python 3 signal.SIG* are enums.
        #
        # Signal     = Union[enum.Enum, int]
        # SigHandler = Union[enum.Enum, Callable]
        self._sigmap = sigmap if sigmap else {}  # Dict[Signal, SigHandler]
        # Maps signals to their default handlers in order to reset
        # custom handlers set by ``sigmap`` at the cleanup phase.
        self._dfl_sigmap = {}  # Dict[Signal, SigHandler]

    #
    # Dunders
    #
    def __repr__(self):
        repr_ = u"<Yaspin frames={0!s}>".format(self._frames)
        if PY2:
            return repr_.encode(ENCODING)
        return repr_

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, traceback):
        # Avoid stop() execution for the 2nd time
        if self._spin_thread.is_alive():
            self.stop()
        return False  # nothing is handled

    def __call__(self, fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            with self:
                return fn(*args, **kwargs)

        return inner

    def __getattr__(self, name):
        # CLI spinners
        if name in SPINNER_ATTRS:
            from .spinners import Spinners

            sp = getattr(Spinners, name)
            self.spinner = sp
        # Color Attributes: "color", "on_color", "attrs"
        elif name in COLOR_ATTRS:
            attr_type = COLOR_MAP[name]
            # Call appropriate property setters;
            # _color_func is updated automatically by setters.
            if attr_type == "attrs":
                self.attrs = [name]  # calls property setter
            if attr_type in ("color", "on_color"):
                setattr(self, attr_type, name)  # calls property setter
        # Side: "left" or "right"
        elif name in ("left", "right"):
            self.side = name  # calls property setter
        # Common error for unsupported attributes
        else:
            raise AttributeError(
                "'{0}' object has no attribute: '{1}'".format(
                    self.__class__.__name__, name
                )
            )
        return self

    #
    # Properties
    #
    @property
    def spinner(self):
        return self._spinner

    @spinner.setter
    def spinner(self, sp):
        self._spinner = self._set_spinner(sp)
        self._frames = self._set_frames(self._spinner, self._reversal)
        self._interval = self._set_interval(self._spinner)
        self._cycle = self._set_cycle(self._frames)

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, txt):
        self._text = self._set_text(txt)

    @property
    def color(self):
        return self._color

    @color.setter
    def color(self, value):
        self._color = self._set_color(value) if value else value
        self._color_func = self._compose_color_func()  # update

    @property
    def on_color(self):
        return self._on_color

    @on_color.setter
    def on_color(self, value):
        self._on_color = self._set_on_color(value) if value else value
        self._color_func = self._compose_color_func()  # update

    @property
    def attrs(self):
        return list(self._attrs)

    @attrs.setter
    def attrs(self, value):
        new_attrs = self._set_attrs(value) if value else set()
        self._attrs = self._attrs.union(new_attrs)
        self._color_func = self._compose_color_func()  # update

    @property
    def side(self):
        return self._side

    @side.setter
    def side(self, value):
        self._side = self._set_side(value)

    @property
    def reversal(self):
        return self._reversal

    @reversal.setter
    def reversal(self, value):
        self._reversal = value
        self._frames = self._set_frames(self._spinner, self._reversal)
        self._cycle = self._set_cycle(self._frames)

    #
    # Public
    #
    def start(self):
        if self._sigmap:
            self._register_signal_handlers()

        if sys.stdout.isatty():
            self._hide_cursor()

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

        sys.stdout.write("\r")
        self._clear_line()

        if sys.stdout.isatty():
            self._show_cursor()

    def hide(self):
        """Hide the spinner to allow for custom writing to the terminal."""
        thr_is_alive = self._spin_thread and self._spin_thread.is_alive()

        if thr_is_alive and not self._hide_spin.is_set():
            # set the hidden spinner flag
            self._hide_spin.set()

            # clear the current line
            sys.stdout.write("\r")
            self._clear_line()

            # flush the stdout buffer so the current line can be rewritten to
            sys.stdout.flush()

    def show(self):
        """Show the hidden spinner."""
        thr_is_alive = self._spin_thread and self._spin_thread.is_alive()

        if thr_is_alive and self._hide_spin.is_set():
            # clear the hidden spinner flag
            self._hide_spin.clear()

            # clear the current line so the spinner is not appended to it
            sys.stdout.write("\r")
            self._clear_line()

    def write(self, text):
        """Write text in the terminal without breaking the spinner."""
        # similar to tqdm.write()
        # https://pypi.python.org/pypi/tqdm#writing-messages
        sys.stdout.write("\r")
        self._clear_line()

        _text = to_unicode(text)
        if PY2:
            _text = _text.encode(ENCODING)

        # Ensure output is bytes for Py2 and Unicode for Py3
        assert isinstance(_text, builtin_str)

        sys.stdout.write("{0}\n".format(_text))

    def ok(self, text="OK"):
        """Set Ok (success) finalizer to a spinner."""
        _text = text if text else "OK"
        self._freeze(_text)

    def fail(self, text="FAIL"):
        """Set fail finalizer to a spinner."""
        _text = text if text else "FAIL"
        self._freeze(_text)

    #
    # Protected
    #
    def _freeze(self, final_text):
        """Stop spinner, compose last frame and 'freeze' it."""
        text = to_unicode(final_text)
        self._last_frame = self._compose_out(text, mode="last")

        # Should be stopped here, otherwise prints after
        # self._freeze call will mess up the spinner
        self.stop()
        sys.stdout.write(self._last_frame)

    def _spin(self):
        while not self._stop_spin.is_set():

            if self._hide_spin.is_set():
                # Wait a bit to avoid wasting cycles
                time.sleep(self._interval)
                continue

            # Compose output
            spin_phase = next(self._cycle)
            out = self._compose_out(spin_phase)

            # Write
            sys.stdout.write(out)
            self._clear_line()
            sys.stdout.flush()

            # Wait
            time.sleep(self._interval)
            sys.stdout.write("\b")

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
        assert isinstance(frame, str)
        assert isinstance(self._text, str)

        frame = frame.encode(ENCODING) if PY2 else frame
        text = self._text.encode(ENCODING) if PY2 else self._text

        # Colors
        if self._color_func is not None:
            frame = self._color_func(frame)

        # Position
        if self._side == "right":
            frame, text = text, frame

        # Mode
        if not mode:
            out = "\r{0} {1}".format(frame, text)
        else:
            out = "{0} {1}\n".format(frame, text)

        # Ensure output is bytes for Py2 and Unicode for Py3
        assert isinstance(out, builtin_str)

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

        for sig, sig_handler in iteritems(self._sigmap):
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
        for sig, sig_handler in iteritems(self._dfl_sigmap):
            signal.signal(sig, sig_handler)

    #
    # Static
    #
    @staticmethod
    def _set_color(value):
        # type: (str) -> str
        available_values = [k for k, v in iteritems(COLOR_MAP) if v == "color"]

        if value not in available_values:
            raise ValueError(
                "'{0}': unsupported color value. Use one of the: {1}".format(
                    value, ", ".join(available_values)
                )
            )
        return value

    @staticmethod
    def _set_on_color(value):
        # type: (str) -> str
        available_values = [
            k for k, v in iteritems(COLOR_MAP) if v == "on_color"
        ]
        if value not in available_values:
            raise ValueError(
                "'{0}': unsupported on_color value. "
                "Use one of the: {1}".format(
                    value, ", ".join(available_values)
                )
            )
        return value

    @staticmethod
    def _set_attrs(attrs):
        # type: (List[str]) -> Set[str]
        available_values = [k for k, v in iteritems(COLOR_MAP) if v == "attrs"]

        for attr in attrs:
            if attr not in available_values:
                raise ValueError(
                    "'{0}': unsupported attribute value. "
                    "Use one of the: {1}".format(
                        attr, ", ".join(available_values)
                    )
                )
        return set(attrs)

    @staticmethod
    def _set_spinner(spinner):
        if not spinner:
            sp = default_spinner

        if hasattr(spinner, "frames") and hasattr(spinner, "interval"):
            if not spinner.frames or not spinner.interval:
                sp = default_spinner
            else:
                sp = spinner
        else:
            sp = default_spinner

        return sp

    @staticmethod
    def _set_side(side):
        # type: (str) -> str
        if side not in ("left", "right"):
            raise ValueError(
                "'{0}': unsupported side value. "
                "Use either 'left' or 'right'."
            )
        return side

    @staticmethod
    def _set_frames(spinner, reversal):
        # type: (base_spinner.Spinner, bool) -> Union[str, List]
        uframes = None  # unicode frames
        uframes_seq = None  # sequence of unicode frames

        if isinstance(spinner.frames, basestring):
            uframes = to_unicode(spinner.frames) if PY2 else spinner.frames

        # TODO (pavdmyt): support any type that implements iterable
        if isinstance(spinner.frames, (list, tuple)):

            # Empty ``spinner.frames`` is handled by ``Yaspin._set_spinner``
            if spinner.frames and isinstance(spinner.frames[0], bytes):
                uframes_seq = [to_unicode(frame) for frame in spinner.frames]
            else:
                uframes_seq = spinner.frames

        _frames = uframes or uframes_seq
        if not _frames:
            # Empty ``spinner.frames`` is handled by ``Yaspin._set_spinner``.
            # This code is very unlikely to be executed. However, it's still
            # here to be on a safe side.
            raise ValueError(
                "{0!r}: no frames found in spinner".format(spinner)
            )

        # Builtin ``reversed`` returns reverse iterator,
        # which adds unnecessary difficulty for returning
        # unicode value;
        # Hence using [::-1] syntax
        frames = _frames[::-1] if reversal else _frames

        return frames

    @staticmethod
    def _set_interval(spinner):
        # Milliseconds to Seconds
        return spinner.interval * 0.001

    @staticmethod
    def _set_cycle(frames):
        return itertools.cycle(frames)

    @staticmethod
    def _set_text(text):
        if PY2:
            return to_unicode(text)
        return text

    @staticmethod
    def _hide_cursor():
        cursor.hide()

    @staticmethod
    def _show_cursor():
        cursor.show()

    @staticmethod
    def _clear_line():
        sys.stdout.write(chr(27) + "[K")
