# -*- coding: utf-8 -*-

import sys
import threading
import time
import itertools


class Spinner(object):
    spinner_cycle = itertools.cycle(u'⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏')

    def __init__(self, beep=False, force=False):
        self.beep = beep
        self.force = force
        self.stop_running = None
        self.spin_thread = None

    def start(self):
        if sys.stdout.isatty() or self.force:
            self.stop_running = threading.Event()
            self.spin_thread = threading.Thread(target=self.init_spin)
            self.spin_thread.start()

    def stop(self):
        if self.spin_thread:
            self.stop_running.set()
            self.spin_thread.join()

    def init_spin(self):
        while not self.stop_running.is_set():
            next_val = next(self.spinner_cycle)
            if sys.version_info[0] == 2:
                next_val = next_val.encode('utf-8')
            sys.stdout.write(next_val)
            sys.stdout.flush()
            time.sleep(0.07)
            sys.stdout.write('\b')

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        if self.beep:
            sys.stdout.write('\7')
            sys.stdout.flush()
        return False


def spinner(beep=False, force=False):
    """This function creates a context manager that is used to display a
    spinner on stdout as long as the context has not exited.

    The spinner is created only if stdout is not redirected, or if the spinner
    is forced using the `force` parameter.

    Parameters
    ----------
    beep : bool
        Beep when spinner finishes.
    force : bool
        Force creation of spinner even when stdout is redirected.

    Example
    -------

        with spinner():
            do_something()
            do_something_else()

    """
    return Spinner(beep, force)
