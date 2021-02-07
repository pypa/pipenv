import collections
import contextlib
import os
import re
import signal
import subprocess
import sys

from .environments import PIPENV_EMULATOR, PIPENV_SHELL, PIPENV_SHELL_EXPLICIT
from .vendor import shellingham
from .vendor.vistir.compat import Path, get_terminal_size
from .vendor.vistir.contextmanagers import temp_environ


ShellDetectionFailure = shellingham.ShellDetectionFailure


def _build_info(value):
    return (os.path.splitext(os.path.basename(value))[0], value)


def detect_info():
    if PIPENV_SHELL_EXPLICIT:
        return _build_info(PIPENV_SHELL_EXPLICIT)
    try:
        return shellingham.detect_shell()
    except (shellingham.ShellDetectionFailure, TypeError):
        if PIPENV_SHELL:
            return _build_info(PIPENV_SHELL)
    raise ShellDetectionFailure


def _get_activate_script(cmd, venv):
    """Returns the string to activate a virtualenv.

    This is POSIX-only at the moment since the compat (pexpect-based) shell
    does not work elsewhere anyway.
    """
    # Suffix and source command for other shells.
    # Support for fish shell.
    if "fish" in cmd:
        suffix = ".fish"
        command = "source"
    # Support for csh shell.
    elif "csh" in cmd:
        suffix = ".csh"
        command = "source"
    else:
        suffix = ""
        command = "."
    # Escape any special characters located within the virtualenv path to allow
    # for proper activation.
    venv_location = re.sub(r'([ &$()\[\]])', r"\\\1", str(venv))
    # The leading space can make history cleaner in some shells.
    return " {2} {0}/bin/activate{1}".format(venv_location, suffix, command)


def _handover(cmd, args):
    args = [cmd] + args
    if os.name != "nt":
        os.execvp(cmd, args)
    else:
        sys.exit(subprocess.call(args, shell=True, universal_newlines=True))


class Shell(object):
    def __init__(self, cmd):
        self.cmd = cmd
        self.args = []

    def __repr__(self):
        return '{type}(cmd={cmd!r})'.format(
            type=type(self).__name__,
            cmd=self.cmd,
        )

    @contextlib.contextmanager
    def inject_path(self, venv):
        with temp_environ():
            os.environ["PATH"] = "{0}{1}{2}".format(
                os.pathsep.join(str(p.parent) for p in _iter_python(venv)),
                os.pathsep,
                os.environ["PATH"],
            )
            yield

    def fork(self, venv, cwd, args):
        # FIXME: This isn't necessarily the correct prompt. We should read the
        # actual prompt by peeking into the activation script.
        name = os.path.basename(venv)
        os.environ["VIRTUAL_ENV"] = str(venv)
        if "PROMPT" in os.environ:
            os.environ["PROMPT"] = "({0}) {1}".format(name, os.environ["PROMPT"])
        if "PS1" in os.environ:
            os.environ["PS1"] = "({0}) {1}".format(name, os.environ["PS1"])
        with self.inject_path(venv):
            os.chdir(cwd)
            _handover(self.cmd, self.args + list(args))

    def fork_compat(self, venv, cwd, args):
        from .vendor import pexpect

        # Grab current terminal dimensions to replace the hardcoded default
        # dimensions of pexpect.
        dims = get_terminal_size()
        with temp_environ():
            c = pexpect.spawn(self.cmd, ["-i"], dimensions=(dims.lines, dims.columns))
        c.sendline(_get_activate_script(self.cmd, venv))
        if args:
            c.sendline(" ".join(args))

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


POSSIBLE_ENV_PYTHON = [Path("bin", "python"), Path("Scripts", "python.exe")]


def _iter_python(venv):
    for path in POSSIBLE_ENV_PYTHON:
        full_path = Path(venv, path)
        if full_path.is_file():
            yield full_path


class Bash(Shell):
    def _format_path(self, python):
        return python.parent.as_posix()

    # The usual PATH injection technique does not work with Bash.
    # https://github.com/berdario/pew/issues/58#issuecomment-102182346
    @contextlib.contextmanager
    def inject_path(self, venv):
        from ._compat import NamedTemporaryFile

        bashrc_path = Path.home().joinpath(".bashrc")
        with NamedTemporaryFile("w+") as rcfile:
            if bashrc_path.is_file():
                base_rc_src = 'source "{0}"\n'.format(bashrc_path.as_posix())
                rcfile.write(base_rc_src)

            export_path = 'export PATH="{0}:$PATH"\n'.format(":".join(
                self._format_path(python)
                for python in _iter_python(venv)
            ))
            rcfile.write(export_path)
            rcfile.flush()
            self.args.extend(["--rcfile", rcfile.name])
            yield


class MsysBash(Bash):
    def _format_path(self, python):
        s = super(MsysBash, self)._format_path(python)
        if not python.drive:
            return s
        # Convert "C:/something" to "/c/something".
        return '/{drive}{path}'.format(drive=s[0].lower(), path=s[2:])


class CmderEmulatedShell(Shell):
    def fork(self, venv, cwd, args):
        if cwd:
            os.environ["CMDER_START"] = cwd
        super(CmderEmulatedShell, self).fork(venv, cwd, args)


class CmderCommandPrompt(CmderEmulatedShell):
    def fork(self, venv, cwd, args):
        rc = os.path.expandvars("%CMDER_ROOT%\\vendor\\init.bat")
        if os.path.exists(rc):
            self.args.extend(["/k", rc])
        super(CmderCommandPrompt, self).fork(venv, cwd, args)


class CmderPowershell(Shell):
    def fork(self, venv, cwd, args):
        rc = os.path.expandvars("%CMDER_ROOT%\\vendor\\profile.ps1")
        if os.path.exists(rc):
            self.args.extend(
                [
                    "-ExecutionPolicy",
                    "Bypass",
                    "-NoLogo",
                    "-NoProfile",
                    "-NoExit",
                    "-Command",
                    "Invoke-Expression '. ''{0}'''".format(rc),
                ]
            )
        super(CmderPowershell, self).fork(venv, cwd, args)


# Two dimensional dict. First is the shell type, second is the emulator type.
# Example: SHELL_LOOKUP['powershell']['cmder'] => CmderPowershell.
SHELL_LOOKUP = collections.defaultdict(
    lambda: collections.defaultdict(lambda: Shell),
    {
        "bash": collections.defaultdict(
            lambda: Bash, {"msys": MsysBash},
        ),
        "cmd": collections.defaultdict(
            lambda: Shell, {"cmder": CmderCommandPrompt},
        ),
        "powershell": collections.defaultdict(
            lambda: Shell, {"cmder": CmderPowershell},
        ),
        "pwsh": collections.defaultdict(
            lambda: Shell, {"cmder": CmderPowershell},
        ),
    },
)


def _detect_emulator():
    keys = []
    if os.environ.get("CMDER_ROOT"):
        keys.append("cmder")
    if os.environ.get("MSYSTEM"):
        keys.append("msys")
    return ",".join(keys)


def choose_shell():
    emulator = PIPENV_EMULATOR.lower() or _detect_emulator()
    type_, command = detect_info()
    shell_types = SHELL_LOOKUP[type_]
    for key in emulator.split(","):
        key = key.strip().lower()
        if key in shell_types:
            return shell_types[key](command)
    return shell_types[""](command)
