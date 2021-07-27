# :copyright: (c) 2021 by Pavlo Dmytrenko.
# :license: MIT, see LICENSE for more details.

"""
yaspin.signal_handlers
~~~~~~~~~~~~~~~~~~~~~~

Callback functions or "signal handlers", that are invoked
when the signal occurs.
"""

import sys


def default_handler(signum, frame, spinner):  # pylint: disable=unused-argument
    """Signal handler, used to gracefully shut down the ``spinner`` instance
    when specified signal is received by the process running the ``spinner``.

    ``signum`` and ``frame`` are mandatory arguments. Check ``signal.signal``
    function for more details.
    """
    spinner.fail()
    spinner.stop()
    sys.exit(0)


def fancy_handler(signum, frame, spinner):  # pylint: disable=unused-argument
    """Signal handler, used to gracefully shut down the ``spinner`` instance
    when specified signal is received by the process running the ``spinner``.

    ``signum`` and ``frame`` are mandatory arguments. Check ``signal.signal``
    function for more details.
    """
    spinner.red.fail("✘")
    spinner.stop()
    sys.exit(0)
