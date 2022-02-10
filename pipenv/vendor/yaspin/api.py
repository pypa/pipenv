# :copyright: (c) 2021 by Pavlo Dmytrenko.
# :license: MIT, see LICENSE for more details.

"""
yaspin.api
~~~~~~~~~~

This module implements the Yaspin API.
"""

import signal

from .core import Yaspin
from .signal_handlers import default_handler


def yaspin(*args, **kwargs):
    """Display spinner in stdout.

    Can be used as a context manager or as a function decorator.

    Arguments:
        spinner (base_spinner.Spinner, optional): Spinner object to use.
        text (str, optional): Text to show along with spinner.
        color (str, optional): Spinner color.
        on_color (str, optional): Color highlight for the spinner.
        attrs (list, optional): Color attributes for the spinner.
        reversal (bool, optional): Reverse spin direction.
        side (str, optional): Place spinner to the right or left end
            of the text string.
        sigmap (dict, optional): Maps POSIX signals to their respective
            handlers.
        timer (bool, optional): Prints a timer showing the elapsed time.

    Returns:
        core.Yaspin: instance of the Yaspin class.

    Raises:
        ValueError: If unsupported ``color`` is specified.
        ValueError: If unsupported ``on_color`` is specified.
        ValueError: If unsupported color attribute in ``attrs``
            is specified.
        ValueError: If trying to register handler for SIGKILL signal.
        ValueError: If unsupported ``side`` is specified.

    Available text colors:
        red, green, yellow, blue, magenta, cyan, white.

    Available text highlights:
        on_red, on_green, on_yellow, on_blue, on_magenta, on_cyan,
        on_white, on_grey.

    Available attributes:
        bold, dark, underline, blink, reverse, concealed.

    Example::

        # Use as a context manager
        with yaspin():
            some_operations()

        # Context manager with text
        with yaspin(text="Processing..."):
            some_operations()

        # Context manager with custom sequence
        with yaspin(Spinner('-\\|/', 150)):
            some_operations()

        # As decorator
        @yaspin(text="Loading...")
        def foo():
            time.sleep(5)

        foo()

    """
    return Yaspin(*args, **kwargs)


def kbi_safe_yaspin(*args, **kwargs):
    kwargs["sigmap"] = {signal.SIGINT: default_handler}
    return Yaspin(*args, **kwargs)


# Handle PYTHONOPTIMIZE=2 case, when docstrings are set to None.
if yaspin.__doc__:
    _kbi_safe_doc = yaspin.__doc__.replace("yaspin", "kbi_safe_yaspin")
    kbi_safe_yaspin.__doc__ = _kbi_safe_doc
