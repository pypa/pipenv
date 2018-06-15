# -*- coding: utf-8 -*-

"""Supporting functions to work with the user's surrounding shell.
"""

import collections
import contextlib
import importlib
import os
import signal
import subprocess
import sys

from pipenv._compat import NamedTemporaryFile, Path, get_terminal_size
from pipenv.utils import temp_environ
from pipenv.vendor import pexpect

import click


def _handover(cmd, args):
    args = [cmd] + args
    if os.name != 'nt':
        os.execvp(cmd, args)
    else:
        proc = subprocess.run(args, shell=True, universal_newlines=True)
        sys.exit(proc.returncode)


POSSIBLE_ENV_PYTHON = [
    Path('bin', 'python'),
    Path('Scripts', 'python.exe'),
]


def _iter_python(venv):
    for path in POSSIBLE_ENV_PYTHON:
        full_path = venv.joinpath(path)
        if full_path.is_file():
            yield full_path


class Shell:

    def __init__(self, cmd):
        self.cmd = cmd
        self.args = []

    @contextlib.contextmanager
    def inject_path(self, venv):
        yield

    def fork(self, venv, cwd, args):
        click.echo("Launching subshell in virtual environment…", err=True)
        os.environ['VIRTUAL_ENV'] = str(venv)
        if os.name == 'nt':
            os.environ['PROMPT'] = '({0}) {1}'.format(
                str(venv), os.environ['PROMPT'],
            )
        else:
            os.environ['PS1'] = '({0}) {1}'.format(
                str(venv), os.environ['PS1'],
            )
        with self.inject_path(venv):
            os.chdir(cwd)
            _handover(self.cmd, self.args + list(args))

    def fork_compat(self, venv, cwd, args, lines):
        try:
            spawn = pexpect.spawn
        except AttributeError:
            click.echo(
                u'Compatibility mode not supported. '
                u'Trying to continue as well-configured shell…',
                err=True,
            )
            self.fork(venv, cwd, args)
            return

        # Grab current terminal dimensions to replace the hardcoded default
        # dimensions of pexpect
        dims = get_terminal_size()
        with temp_environ():
            c = spawn(self.cmd, ['-i'], dimensions=(dims.lines, dims.columns))
        c.sendline(lines)
        if args:
            c.sendline(' '.join(args))

        # Handler for terminal resizing events
        # Must be defined here to have the shell process in its context, since
        # we can't pass it as an argument
        def sigwinch_passthrough(sig, data):
            dims = get_terminal_size()
            c.setwinsize(dims.lines, dims.columns)

        signal.signal(signal.SIGWINCH, sigwinch_passthrough)

        # Interact with the new shell.
        c.interact(escape_character=None)
        c.close()
        sys.exit(c.exitstatus)


class Bash(Shell):
    # The usual PATH injection technique does not work with Bash.
    # https://github.com/berdario/pew/issues/58#issuecomment-102182346
    @contextlib.contextmanager
    def inject_path(self, venv):
        bashrc_path = Path.home().joinpath('.bashrc')
        with NamedTemporaryFile('w+') as rcfile:
            if bashrc_path.is_file():
                base_rc_src = 'source "{0}"\n'.format(bashrc_path.as_posix())
                rcfile.write(base_rc_src)

            export_path = 'export PATH="{0}:$PATH"\n'.format(':'.join(
                python.parent.as_posix()
                for python in _iter_python(venv)
            ))
            rcfile.write(export_path)
            rcfile.flush()
            self.args.extend(['--rcfile', rcfile.name])
            yield


class CmderEmulatedShell(Shell):
    def fork(self, venv, cwd, args):
        if cwd:
            os.environ['CMDER_START'] = cwd
        super(CmderEmulatedShell, self).fork(venv, cwd, args)


class CmderCommandPrompt(CmderEmulatedShell):
    def fork(self, venv, cwd, args):
        rc = os.path.expandvars('%CMDER_ROOT%\\vendor\\init.bat')
        if os.path.exists(rc):
            self.args.extend(['/k', rc])
        super(CmderCommandPrompt, self).fork(venv, cwd, args)


class CmderPowershell(Shell):
    def fork(self, venv, cwd, args):
        rc = os.path.expandvars('%CMDER_ROOT%\\vendor\\profile.ps1')
        if os.path.exists(rc):
            self.args.extend([
                '-ExecutionPolicy', 'Bypass', '-NoLogo', '-NoProfile',
                '-NoExit', '-Command',
                "Invoke-Expression '. ''{0}'''".format(rc),
            ])
        super(CmderPowershell, self).fork(venv, cwd, args)


# Two dimensional dict. First is the shell type, second is the emulator type.
# Example: SHELL_LOOKUP['powershell']['cmder'] => CmderPowershell.
SHELL_LOOKUP = collections.defaultdict(
    lambda: collections.defaultdict(lambda: Shell),
    {
        'bash': collections.defaultdict(lambda: Bash),
        'cmd': collections.defaultdict(lambda: Shell, {
            'cmder': CmderCommandPrompt,
        }),
        'powershell': collections.defaultdict(lambda: Shell, {
            'cmder': CmderPowershell,
        }),
        'pwsh': collections.defaultdict(lambda: Shell, {
            'cmder': CmderPowershell,
        }),
    },
)


class CannotGuessShell(EnvironmentError):
    pass


def _detect_current_shell(pid=None, max_depth=6):
    name = os.name
    try:
        impl = importlib.import_module('.' + name, 'pipenv.shelltools')
    except ImportError:
        raise RuntimeError(
            'Shell detection not implemented for {0!r}'.format(name),
        )
    try:
        get_shell = impl.get_shell
    except AttributeError:
        raise RuntimeError('get_shell not implemented for {0!r}'.format(name))
    shell = get_shell(pid, max_depth=max_depth)
    if shell:
        return shell
    raise CannotGuessShell()


def _detect_current_emulator():
    if os.environ.get('CMDER_ROOT'):
        return 'cmder'
    return ''


def choose_shell(shell_cmd=None, emulator=None):
    if shell_cmd is None:
        shell_cmd = _detect_current_shell()
    if emulator is None:
        emulator = _detect_current_emulator()
    shell_cls = SHELL_LOOKUP[Path(shell_cmd).stem.lower()][emulator]
    return shell_cls(shell_cmd)
