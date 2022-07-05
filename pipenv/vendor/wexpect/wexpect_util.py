"""Wexpect is a Windows variant of pexpect https://pexpect.readthedocs.io.

Wexpect is a Python module for spawning child applications and controlling
them automatically.

wexpect util contains small functions, and classes, which are used in multiple classes.
The command line argument parsers, and the Exceptions placed here.

"""

import re
import traceback
import sys
import os
import logging
import signal

# platform does not define VEOF so assume CTRL-D
EOF_CHAR = b'\x04'

SIGNAL_CHARS = {
    signal.SIGTERM: b'\x011',  # Device control 1
    signal.SIGINT: b'\x012',  # Device control 2
}

SPAM = 5
logging.addLevelName(SPAM, "SPAM")


def str2bool(v):
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:  # pragma: no cover
        raise argparse.ArgumentTypeError('Boolean value expected.')


def spam(self, message, *args, **kws):  # pragma: no cover
    '''Very verbose debug dunction.
    '''
    if self.isEnabledFor(SPAM):
        # Yes, logger takes its '*args' as 'args'.
        self._log(SPAM, message, args, **kws)


logging.Logger.spam = spam


def init_logger(logger=None):  # pragma: no cover
    '''Initializes the logger. I wont measure coverage for this debug method.
    '''
    if logger is None:
        logger = logging.getLogger('wexpect')
    try:
        logger_level = os.environ['WEXPECT_LOGGER_LEVEL']
        try:
            logger_filename = os.environ['WEXPECT_LOGGER_FILENAME']
        except KeyError:
            pid = os.getpid()
            logger_filename = f'./.wlog/wexpect_{pid}'
        logger.setLevel(logger_level)
        logger_filename = f'{logger_filename}.log'
        os.makedirs(os.path.dirname(logger_filename), exist_ok=True)
        fh = logging.FileHandler(logger_filename, 'a', 'utf-8')
        formatter = logging.Formatter(
            '%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except KeyError:
        logger.setLevel(logging.ERROR)


def split_command_line(command_line, escape_char='^'):
    """This splits a command line into a list of arguments. It splits arguments
    on spaces, but handles embedded quotes, doublequotes, and escaped
    characters. It's impossible to do this with a regular expression, so I
    wrote a little state machine to parse the command line. """

    arg_list = []
    arg = ''

    # Constants to name the states we can be in.
    state_basic = 0
    state_esc = 1
    state_singlequote = 2
    state_doublequote = 3
    state_whitespace = 4    # The state of consuming whitespace between commands.
    state = state_basic

    for c in command_line:
        if state == state_basic or state == state_whitespace:
            if c == escape_char:    # Escape the next character
                state = state_esc
            elif c == r"'":     # Handle single quote
                state = state_singlequote
            elif c == r'"':     # Handle double quote
                state = state_doublequote
            elif c.isspace():
                # Add arg to arg_list if we aren't in the middle of whitespace.
                if state == state_whitespace:
                    None    # Do nothing.
                else:
                    arg_list.append(arg)
                    arg = ''
                    state = state_whitespace
            else:
                arg = arg + c
                state = state_basic
        elif state == state_esc:
            arg = arg + c
            state = state_basic
        elif state == state_singlequote:
            if c == r"'":
                state = state_basic
            else:
                arg = arg + c
        elif state == state_doublequote:
            if c == r'"':
                state = state_basic
            else:
                arg = arg + c

    if arg != '':
        arg_list.append(arg)
    return arg_list


def join_args(args):
    """Joins arguments a command line. It quotes all arguments that contain
    spaces or any of the characters ^!$%&()[]{}=;'+,`~"""
    commandline = []
    for arg in args:
        if re.search('[\\^!$%&()[\\]{}=;\'+,`~\\s]', arg):
            arg = '"%s"' % arg
        commandline.append(arg)
    return ' '.join(commandline)


class ExceptionPexpect(Exception):
    """Base class for all exceptions raised by this module.
    """

    def __init__(self, value):

        self.value = value

    def __str__(self):

        return str(self.value)

    def get_trace(self):
        """This returns an abbreviated stack trace with lines that only concern
        the caller. In other words, the stack trace inside the Wexpect module
        is not included. """

        tblist = traceback.extract_tb(sys.exc_info()[2])
        tblist = [item for item in tblist if self.__filter_not_wexpect(item)]
        tblist = traceback.format_list(tblist)
        return ''.join(tblist)

    def __filter_not_wexpect(self, trace_list_item):
        """This returns True if list item 0 the string 'wexpect.py' in it. """

        if trace_list_item[0].find('host.py') == -1:
            return True
        else:
            return False


class EOF(ExceptionPexpect):
    """Raised when EOF is read from a child. This usually means the child has exited.
    The user can wait to EOF, which means he waits the end of the execution of the child process."""


class TIMEOUT(ExceptionPexpect):
    """Raised when a read time exceeds the timeout. """

init_logger()
