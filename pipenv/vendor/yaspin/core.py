# :copyright: (c) 2021 by Pavlo Dmytrenko.
# :license: MIT, see LICENSE for more details.

"""
yaspin.yaspin
~~~~~~~~~~~~~

A lightweight terminal spinner.
"""

import contextlib
import datetime
import functools
import itertools
import signal
import sys
import threading
import time
from typing import List, Set, Union

from pipenv.vendor.termcolor import colored
from pipenv.vendor import colorama
from pipenv.vendor.vistir import cursor

from .base_spinner import Spinner, default_spinner
from .constants import COLOR_ATTRS, COLOR_MAP, SPINNER_ATTRS
from .helpers import to_unicode

colorama.init()


class Yaspin:  # pylint: disable=useless-object-inheritance,too-many-instance-attributes
    """Implements a context manager that spawns a thread
    to write spinner frames into a tty (stdout) during
    context execution.
    """

    # When Python finds its output attached to a terminal,
    # it sets the sys.stdout.encoding attribute to the terminal's encoding.
    # The print statement's handler will automatically encode unicode
    # arguments into bytes.

    def __init__(  # pylint: disable=too-many-arguments
        self,
        spinner=None,
        text="",
        color=None,
        on_color=None,
        attrs=None,
        reversal=False,
        side="left",
        sigmap=None,
        timer=False,
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
        self._text = text
        self._side = self._set_side(side)
        self._reversal = reversal
        self._timer = timer
        self._start_time = None
        self._stop_time = None

        # Helper flags
        self._stop_spin = None
        self._hide_spin = None
        self._spin_thread = None
        self._last_frame = None
        self._stdout_lock = threading.Lock()
        self._hidden_level = 0

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
        return "<Yaspin frames={0!s}>".format(self._frames)

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
            from .spinners import Spinners  # pylint: disable=import-outside-toplevel

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
        self._text = txt

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

    @property
    def elapsed_time(self):
        if self._start_time is None:
            return 0

        if self._stop_time is None:
            return time.time() - self._start_time

        return self._stop_time - self._start_time

    #
    # Public
    #
    def start(self):
        if self._sigmap:
            self._register_signal_handlers()

        if sys.stdout.isatty():
            self._hide_cursor()

        self._start_time = time.time()
        self._stop_time = None  # Reset value to properly calculate subsequent spinner starts (if any)  # pylint: disable=line-too-long
        self._stop_spin = threading.Event()
        self._hide_spin = threading.Event()
        self._spin_thread = threading.Thread(target=self._spin)
        self._spin_thread.start()

    def stop(self):
        self._stop_time = time.time()

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
            with self._stdout_lock:
                # set the hidden spinner flag
                self._hide_spin.set()

                # clear the current line
                sys.stdout.write("\r")
                self._clear_line()

                # flush the stdout buffer so the current line
                # can be rewritten to
                sys.stdout.flush()

    @contextlib.contextmanager
    def hidden(self):
        """Hide the spinner within a block, can be nested"""
        if self._hidden_level == 0:
            self.hide()
        self._hidden_level += 1

        try:
            yield
        finally:
            self._hidden_level -= 1
            if self._hidden_level == 0:
                self.show()

    def show(self):
        """Show the hidden spinner."""
        thr_is_alive = self._spin_thread and self._spin_thread.is_alive()

        if thr_is_alive and self._hide_spin.is_set():
            with self._stdout_lock:
                # clear the hidden spinner flag
                self._hide_spin.clear()

                # clear the current line so the spinner is not appended to it
                sys.stdout.write("\r")
                self._clear_line()

    def write(self, text):
        """Write text in the terminal without breaking the spinner."""
        # similar to tqdm.write()
        # https://pypi.python.org/pypi/tqdm#writing-messages
        with self._stdout_lock:
            sys.stdout.write("\r")
            self._clear_line()

            if isinstance(text, (str, bytes)):
                _text = to_unicode(text)
            else:
                _text = str(text)

            # Ensure output is Unicode
            assert isinstance(_text, str)

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
        with self._stdout_lock:
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
            with self._stdout_lock:
                sys.stdout.write(out)
                self._clear_line()
                sys.stdout.flush()

            # Wait
            self._stop_spin.wait(self._interval)

    def _compose_color_func(self):
        return functools.partial(
            colored,
            color=self._color,
            on_color=self._on_color,
            attrs=list(self._attrs),
        )

    def _compose_out(self, frame, mode=None):
        # Ensure Unicode input
        assert isinstance(frame, str)
        assert isinstance(self._text, str)

        text = self._text

        # Colors
        if self._color_func is not None:
            frame = self._color_func(frame)

        # Position
        if self._side == "right":
            frame, text = text, frame

        if self._timer:
            sec, fsec = divmod(round(100 * self.elapsed_time), 100)
            text += " ({}.{:02.0f})".format(datetime.timedelta(seconds=sec), fsec)

        # Mode
        if not mode:
            out = "\r{0} {1}".format(frame, text)
        else:
            out = "{0} {1}\n".format(frame, text)

        # Ensure output is Unicode
        assert isinstance(out, str)

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

    #
    # Static
    #
    @staticmethod
    def _set_color(value: str) -> str:
        available_values = [k for k, v in COLOR_MAP.items() if v == "color"]
        if value not in available_values:
            raise ValueError(
                "'{0}': unsupported color value. Use one of the: {1}".format(
                    value, ", ".join(available_values)
                )
            )
        return value

    @staticmethod
    def _set_on_color(value: str) -> str:
        available_values = [k for k, v in COLOR_MAP.items() if v == "on_color"]
        if value not in available_values:
            raise ValueError(
                "'{0}': unsupported on_color value. "
                "Use one of the: {1}".format(value, ", ".join(available_values))
            )
        return value

    @staticmethod
    def _set_attrs(attrs: List[str]) -> Set[str]:
        available_values = [k for k, v in COLOR_MAP.items() if v == "attrs"]
        for attr in attrs:
            if attr not in available_values:
                raise ValueError(
                    "'{0}': unsupported attribute value. "
                    "Use one of the: {1}".format(attr, ", ".join(available_values))
                )
        return set(attrs)

    @staticmethod
    def _set_spinner(spinner):
        if hasattr(spinner, "frames") and hasattr(spinner, "interval"):
            if not spinner.frames or not spinner.interval:
                sp = default_spinner
            else:
                sp = spinner
        else:
            sp = default_spinner

        return sp

    @staticmethod
    def _set_side(side: str) -> str:
        if side not in ("left", "right"):
            raise ValueError(
                "'{0}': unsupported side value. " "Use either 'left' or 'right'."
            )
        return side

    @staticmethod
    def _set_frames(spinner: Spinner, reversal: bool) -> Union[str, List]:
        uframes = None  # unicode frames
        uframes_seq = None  # sequence of unicode frames

        if isinstance(spinner.frames, str):
            uframes = spinner.frames

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
            raise ValueError("{0!r}: no frames found in spinner".format(spinner))

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
    def _hide_cursor():
        cursor.hide_cursor()

    @staticmethod
    def _show_cursor():
        cursor.show_cursor()

    @staticmethod
    def _clear_line():
        sys.stdout.write("\033[K")
