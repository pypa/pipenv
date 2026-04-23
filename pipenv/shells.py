import collections
import contextlib
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from shutil import get_terminal_size

from pipenv.utils.shell import temp_environ
from pipenv.vendor import shellingham

ShellDetectionFailure = shellingham.ShellDetectionFailure


def _build_info(value):
    path = Path(value)
    return (path.stem, value)


def detect_info(project):
    if project.s.PIPENV_SHELL_EXPLICIT:
        return _build_info(project.s.PIPENV_SHELL_EXPLICIT)
    # On Windows, prefer $SHELL over shellingham process-tree detection.
    # shellingham walks the process tree and can be confused by cmd.exe shims
    # (e.g. pyenv), returning 'cmd' even when the user is in bash or powershell.
    # $SHELL is set by POSIX-like environments (Git Bash, MSYS2, WSL) to the
    # correct interactive shell.
    if os.name == "nt" and project.s.PIPENV_SHELL:
        return _build_info(project.s.PIPENV_SHELL)
    try:
        return shellingham.detect_shell()
    except (shellingham.ShellDetectionFailure, TypeError):
        if project.s.PIPENV_SHELL:
            return _build_info(project.s.PIPENV_SHELL)
    raise ShellDetectionFailure


def _get_activate_script(cmd, venv):
    """Returns the string to activate a virtualenv.

    This is POSIX-only at the moment since the compat (pexpect-based) shell
    does not work elsewhere anyway.
    """
    # Suffix and source command for various shells.
    command = "source"

    # Extract the shell executable name from the path, handling both POSIX
    # forward-slash paths and Windows backslash paths on any host OS.
    # e.g. "C:\Program Files\PowerShell\7\pwsh.exe" -> "pwsh"
    #      "/usr/bin/zsh"                            -> "zsh"
    # See: https://github.com/pypa/pipenv/issues/6532
    shell_name = re.split(r"[\\/]", cmd)[-1].split(".")[0].lower()

    if shell_name == "fish":
        suffix = ".fish"
    elif shell_name in ("csh", "tcsh"):
        suffix = ".csh"
    elif shell_name == "xonsh":
        suffix = ".xsh"
    elif shell_name == "nu":
        suffix = ".nu"
        command = "overlay use"
    elif shell_name in ("pwsh", "powershell"):
        suffix = ".ps1"
        command = "."
    elif shell_name in ("sh", "bash", "zsh", "dash", "ash", "ksh"):
        suffix = ""
    else:
        sys.exit(f"unknown shell {cmd}")

    # Escape any special characters located within the virtualenv path to allow
    # for proper activation.
    venv_location = re.sub(r"([ &$()\[\]])", r"\\\1", str(venv))

    if suffix == "nu":
        return f"overlay use {venv_location}"
    elif suffix == ".ps1" and os.name == "nt":
        return f". {venv_location}\\Scripts\\Activate{suffix}"

    # The leading space can make history cleaner in some shells.
    return f" {command} {venv_location}/bin/activate{suffix}"


def _get_deactivate_wrapper_script(cmd):
    """Returns a script to wrap the deactivate function to also unset PIPENV_ACTIVE.

    This ensures that when a user runs 'deactivate' in a pipenv shell, the
    PIPENV_ACTIVE environment variable is also cleared, allowing subsequent
    'pipenv shell' commands to work without the 'already activated' error.
    """
    # Extract the shell executable name from the path, handling both POSIX
    # forward-slash paths and Windows backslash paths on any host OS.
    # e.g. "C:\Program Files\PowerShell\7\pwsh.exe" -> "pwsh"
    #      "/usr/bin/zsh"                            -> "zsh"
    # See: https://github.com/pypa/pipenv/issues/6532
    shell_name = re.split(r"[\\/]", cmd)[-1].split(".")[0].lower()

    if shell_name == "fish":
        # Fish shell uses 'functions' and 'set -e' to unset variables
        return (
            "functions -c deactivate _pipenv_old_deactivate; "
            "function deactivate; _pipenv_old_deactivate; set -e PIPENV_ACTIVE; end"
        )
    elif shell_name in ("csh", "tcsh"):
        # C shell uses 'unsetenv'
        return (
            "alias _pipenv_old_deactivate deactivate; "
            "alias deactivate '_pipenv_old_deactivate; unsetenv PIPENV_ACTIVE'"
        )
    elif shell_name == "xonsh":
        # Xonsh uses Python-like syntax
        return (
            "_pipenv_old_deactivate = deactivate; "
            "def deactivate(): _pipenv_old_deactivate(); del $PIPENV_ACTIVE"
        )
    elif shell_name == "nu":
        # Nushell - deactivate is typically handled differently
        # For now, return empty as nu has different paradigm
        return ""
    elif shell_name in ("pwsh", "powershell"):
        # PowerShell
        return (
            "$_pipenv_old_deactivate = $function:deactivate; "
            "function deactivate { & $_pipenv_old_deactivate; "
            "Remove-Item Env:PIPENV_ACTIVE -ErrorAction SilentlyContinue }"
        )
    elif shell_name == "zsh":
        # Zsh uses 'functions -c' to copy function definitions
        return (
            "functions -c deactivate _pipenv_old_deactivate; "
            "deactivate() { _pipenv_old_deactivate; unset PIPENV_ACTIVE; }"
        )
    elif shell_name == "bash":
        # Bash uses 'declare -f' to copy function definitions
        return (
            'eval "_pipenv_old_deactivate() { $(declare -f deactivate | tail -n +2) }"; '
            "deactivate() { _pipenv_old_deactivate; unset PIPENV_ACTIVE; }"
        )
    elif shell_name in ("sh", "dash", "ash", "ksh"):
        # Plain POSIX sh doesn't have 'declare -f', use a simpler approach
        # Just redefine deactivate to call the original via sourcing and add unset
        return "deactivate() { command deactivate 2>/dev/null; unset PIPENV_ACTIVE; }"
    else:
        # Unknown shell - return empty string
        return ""


def _handover(cmd, args):
    args = [cmd] + args
    if os.name != "nt":
        os.execvp(cmd, args)
    else:
        sys.exit(subprocess.call(args, universal_newlines=True))


class Shell:
    def __init__(self, cmd):
        self.cmd = cmd
        self.args = []

    def __repr__(self):
        return f"{type(self).__name__}(cmd={repr(self.cmd)}, args={repr(self.args)})"

    @contextlib.contextmanager
    def inject_path(self, venv):
        venv_path = Path(venv)
        with temp_environ():
            os.environ["PATH"] = (
                f"{os.pathsep.join(str(p.parent) for p in _iter_python(venv_path))}{os.pathsep}{os.environ['PATH']}"
            )
            yield

    def fork(self, venv, cwd, args):
        # FIXME: This isn't necessarily the correct prompt. We should read the
        # actual prompt by peeking into the activation script.
        venv_path = Path(venv)
        name = venv_path.name
        os.environ["VIRTUAL_ENV"] = str(venv_path)
        if "PROMPT" in os.environ:
            os.environ["PROMPT"] = f"({name}) {os.environ['PROMPT']}"
        if "PS1" in os.environ:
            os.environ["PS1"] = f"({name}) {os.environ['PS1']}"
        with self.inject_path(venv):
            os.chdir(str(cwd) if isinstance(cwd, Path) else cwd)
            _handover(self.cmd, self.args + list(args))

    def fork_compat(self, venv, cwd, args, quiet=False):
        from .vendor import pexpect

        # Grab current terminal dimensions to replace the hardcoded default
        # dimensions of pexpect.
        dims = get_terminal_size()
        with temp_environ():
            # Unset COLUMNS and LINES so the spawned shell can manage them.
            # When these are exported, Bash treats them as read-only inherited
            # values and doesn't update them on terminal resize, even with
            # checkwinsize enabled. See: https://github.com/pypa/pipenv/issues/6169
            os.environ.pop("COLUMNS", None)
            os.environ.pop("LINES", None)
            c = pexpect.spawn(self.cmd, ["-i"], dimensions=(dims.lines, dims.columns))

        # NOTE ON TERMINAL ECHO (GH-6633):
        # Previous versions of this function toggled ``c.setecho(False)`` /
        # ``setecho(True)`` around the setup commands to hide them from the
        # user.  This was fundamentally unsound:
        #
        # * ``setecho(True)`` at the end re-enables kernel pty ECHO *after*
        #   the shell's readline has already set stty -echo for its own line
        #   editing.  Because readline does its own echo, the user then sees
        #   every keystroke twice (the kernel echo + readline's echo) — hence
        #   the "1234 -> 11223344" and "^C -> ^C^C" symptoms in #6633.
        # * ``setecho(False)`` before readline initialises causes readline to
        #   save echo-off as its baseline termios state, so every new prompt
        #   permanently disables echo.
        #
        # The correct approach is to leave the pty's termios completely alone
        # and rely on pexpect's expect() calls to drain the setup commands
        # from the buffer before handing the pty over to ``interact()``.  The
        # sentinel must be consumed *twice* in that drain: once for the shell
        # echoing back the command it received (readline or kernel echo), and
        # once for the command's actual output.

        # Prefix every internal command with a leading space so that shells
        # configured with HISTCONTROL=ignorespace (the default on most
        # distributions) do not record them in the command history.
        # See: https://github.com/pypa/pipenv/issues/6627
        _STARTUP_SENTINEL = "__PIPENV_STARTUP_READY__"
        _SENTINEL = "__PIPENV_SHELL_READY__"

        # Wait for the shell to finish its startup (including any
        # interactive prompts such as oh-my-zsh's update dialogue) before
        # sending the activate script.  Without this, the activate command
        # is consumed by whatever prompt appears first, and the virtualenv
        # never gets activated.  See: https://github.com/pypa/pipenv/issues/3615
        c.sendline(f" echo {_STARTUP_SENTINEL}")
        try:
            c.expect(_STARTUP_SENTINEL, timeout=30)
        except Exception:
            pass  # best-effort: continue even if the sentinel is not seen

        c.sendline(_get_activate_script(self.cmd, venv))

        # Wrap the deactivate function to also unset PIPENV_ACTIVE.
        deactivate_wrapper = _get_deactivate_wrapper_script(self.cmd)
        if deactivate_wrapper:
            c.sendline(f" {deactivate_wrapper}")

        if args:
            c.sendline(" ".join(args))

        # Final synchronisation and buffer drain before interact() takes over.
        #
        # Each ``sendline`` causes the shell to echo the typed command back
        # into the pty stream (once), then later produce the command's
        # actual output (for ``echo``, that's a second copy of the
        # sentinel).  ``expect()`` consumes output up to and including the
        # *first* match — so we must expect the sentinel twice to consume
        # both the echoed-command line and the echoed-output line.  Without
        # this, ``__PIPENV_SHELL_READY__`` is left in the pexpect buffer and
        # leaks to the user's terminal when ``interact()`` flushes it.
        c.sendline(f" echo {_SENTINEL}")
        try:
            c.expect(_SENTINEL, timeout=10)
            c.expect(_SENTINEL, timeout=10)
        except Exception:
            pass  # pattern-not-found or timeout: best-effort, continue

        # Handler for terminal resizing events
        # Must be defined here to have the shell process in its context, since
        # we can't pass it as an argument
        def sigwinch_passthrough(sig, data):
            dims = get_terminal_size()
            c.setwinsize(dims.lines, dims.columns)

        signal.signal(signal.SIGWINCH, sigwinch_passthrough)

        # Handle job-control signals (Ctrl+Z / suspend) so that the pipenv
        # process properly suspends itself when the child shell is stopped,
        # and resumes the child when pipenv is continued.
        # Without this, pexpect's interact() loop keeps the pipenv process
        # in the foreground and the parent shell never regains control.
        # See: https://github.com/pypa/pipenv/issues/5359
        if os.name != "nt" and hasattr(signal, "SIGTSTP"):

            def sigtstp_handler(sig, frame):
                # Stop the child shell process group
                if c.isalive():
                    os.kill(c.pid, signal.SIGSTOP)
                # Restore default SIGTSTP handling and re-raise so the
                # OS stops the pipenv process itself.
                signal.signal(signal.SIGTSTP, signal.SIG_DFL)
                os.kill(os.getpid(), signal.SIGTSTP)

            def sigcont_handler(sig, frame):
                # Re-install our custom SIGTSTP handler after being resumed
                signal.signal(signal.SIGTSTP, sigtstp_handler)
                # Resume the child shell process
                if c.isalive():
                    os.kill(c.pid, signal.SIGCONT)

            signal.signal(signal.SIGTSTP, sigtstp_handler)
            signal.signal(signal.SIGCONT, sigcont_handler)

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
        from tempfile import NamedTemporaryFile

        bashrc_path = Path.home().joinpath(".bashrc")
        with NamedTemporaryFile("w+") as rcfile:
            if bashrc_path.is_file():
                base_rc_src = f'source "{bashrc_path.as_posix()}"\n'
                rcfile.write(base_rc_src)

            export_path = 'export PATH="{}:$PATH"\n'.format(
                ":".join(self._format_path(python) for python in _iter_python(venv))
            )
            rcfile.write(export_path)
            rcfile.flush()
            self.args.extend(["--rcfile", rcfile.name])
            yield


class MsysBash(Bash):
    def _format_path(self, python):
        s = super()._format_path(python)
        if not python.drive:
            return s
        # Convert "C:/something" to "/c/something".
        return f"/{s[0].lower()}{s[2:]}"


class CmderEmulatedShell(Shell):
    def fork(self, venv, cwd, args):
        if cwd:
            os.environ["CMDER_START"] = cwd
        super().fork(venv, cwd, args)


class CmderCommandPrompt(CmderEmulatedShell):
    def fork(self, venv, cwd, args):
        rc_path = Path(os.path.expandvars("%CMDER_ROOT%\\vendor\\init.bat"))
        if rc_path.exists():
            self.args.extend(["/k", str(rc_path)])
        super().fork(venv, cwd, args)


class CmderPowershell(Shell):
    def fork(self, venv, cwd, args):
        rc_path = Path(os.path.expandvars("%CMDER_ROOT%\\vendor\\profile.ps1"))
        if rc_path.exists():
            self.args.extend(
                [
                    "-ExecutionPolicy",
                    "Bypass",
                    "-NoLogo",
                    "-NoProfile",
                    "-NoExit",
                    "-Command",
                    f"Invoke-Expression '. ''{rc_path}'''",
                ]
            )
        super().fork(venv, cwd, args)


# Two dimensional dict. First is the shell type, second is the emulator type.
# Example: SHELL_LOOKUP['powershell']['cmder'] => CmderPowershell.
SHELL_LOOKUP = collections.defaultdict(
    lambda: collections.defaultdict(lambda: Shell),
    {
        "bash": collections.defaultdict(
            lambda: Bash,
            {"msys": MsysBash},
        ),
        "cmd": collections.defaultdict(
            lambda: Shell,
            {"cmder": CmderCommandPrompt},
        ),
        "powershell": collections.defaultdict(
            lambda: Shell,
            {"cmder": CmderPowershell},
        ),
        "pwsh": collections.defaultdict(
            lambda: Shell,
            {"cmder": CmderPowershell},
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


def choose_shell(project):
    emulator = project.s.PIPENV_EMULATOR.lower() or _detect_emulator()
    type_, command = detect_info(project)
    shell_types = SHELL_LOOKUP[type_]
    for key in emulator.split(","):
        key = key.strip().lower()
        if key in shell_types:
            return shell_types[key](command)
    return shell_types[""](command)
