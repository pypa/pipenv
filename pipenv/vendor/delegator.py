import os
import subprocess
import shlex

from pexpect.popen_spawn import PopenSpawn

# Enable Python subprocesses to work with expect functionality.
os.environ['PYTHONUNBUFFERED'] = '1'

class Command(object):
    def __init__(self, cmd):
        super(Command, self).__init__()
        self.cmd = cmd
        self.subprocess = None
        self.blocking = None
        self.was_run = False
        self.__out = None

    def __repr__(self):
        return '<Commmand {!r}>'.format(self.cmd)

    @property
    def _popen_args(self):
        return self.cmd

    @property
    def _default_popen_kwargs(self):
        return {
            'env': os.environ.copy(),
            'stdin': subprocess.PIPE,
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'shell': True,
            'universal_newlines': True,
            'bufsize': 0,
        }

    @property
    def _default_pexpect_kwargs(self):
        return {
            'env': os.environ.copy(),
        }

    @property
    def _uses_subprocess(self):
        return isinstance(self.subprocess, subprocess.Popen)

    @property
    def _uses_pexpect(self):
        return isinstance(self.subprocess, PopenSpawn)

    @property
    def std_out(self):
        return self.subprocess.stdout

    @property
    def _pexpect_out(self):
        result = ''

        if self.subprocess.before:
            result += self.subprocess.before

        if isinstance(self.subprocess.after, str):
            result += self.subprocess.after

        result += self.subprocess.read().decode('utf-8')
        return result

    @property
    def out(self):
        """Std/out output (cached), as well as stderr for non-blocking runs."""
        if self.__out:
            return self.__out

        if self._uses_subprocess:
            self.__out = self.std_out.read()
        else:
            self.__out = self._pexpect_out

        return self.__out

    @property
    def std_err(self):
        return self.subprocess.stderr

    @property
    def err(self):
        if self._uses_subprocess:
            return self.std_err.read()
        else:
            return self._pexpect_out

    @property
    def pid(self):
        """The process' PID."""
        # Support for pexpect's functionality.
        if hasattr(self.subprocess, 'proc'):
            return self.subprocess.proc.pid
        # Standard subprocess method.
        return self.subprocess.pid

    @property
    def return_code(self):
        return self.subprocess.returncode

    @property
    def std_in(self):
        return self.subprocess.stdin

    def run(self, block=True):
        """Runs the given command, with or without pexpect functionality enabled."""
        self.blocking = block

        # Use subprocess.
        if self.blocking:
            s = subprocess.Popen(self._popen_args, **self._default_popen_kwargs)

        # Otherwise, use pexpect.
        else:
            s = PopenSpawn(self._popen_args, **self._default_pexpect_kwargs)
        self.subprocess = s
        self.was_run = True

    def expect(self, pattern, timeout=-1):
        """Waits on the given pattern to appear in std_out"""

        if self.blocking:
            raise RuntimeError('expect can only be used on non-blocking commands.')

        self.subprocess.expect(pattern=pattern, timeout=timeout)

    def send(self, s, end=os.linesep, signal=False):
        """Sends the given string or signal to std_in."""

        if self.blocking:
            raise RuntimeError('send can only be used on non-blocking commands.')

        if not signal:
            if self._uses_subprocess:
                return self.subprocess.communicate(s + end)
            else:
                return self.subprocess.send(s + end)
        else:
            self.subprocess.send_signal(s)

    def terminate(self):
        self.subprocess.terminate()

    def kill(self):
        self.subprocess.kill()

    def block(self):
        """Blocks until process is complete."""
        self.subprocess.wait()

    def pipe(self, command):
        """Runs the current command and passes its output to the next
        given process.
        """
        if not self.was_run:
            self.run(block=False)

        data = self.out

        c = Command(command)
        c.run(block=False)
        if data:
            c.send(data)
            c.subprocess.sendeof()
        c.block()
        return c


def _expand_args(command):
    """Parses command strings and returns a Popen-ready list."""

    # Prepare arguments.
    if isinstance(command, (str, unicode)):
        splitter = shlex.shlex(command.encode('utf-8'))
        splitter.whitespace = '|'
        splitter.whitespace_split = True
        command = []

        while True:
            token = splitter.get_token()
            if token:
                command.append(token)
            else:
                break

        command = list(map(shlex.split, command))

    return command


def chain(command):
    commands = _expand_args(command)
    data = None

    for command in commands:

        c = run(command, block=False)

        if data:
            c.send(data)
            c.subprocess.sendeof()

        data = c.out

    return c


def run(command, block=True):
    c = Command(command)
    c.run(block=block)

    if block:
        c.block()

    return c
