from __future__ import annotations


__lazy_modules__ = {'subprocess'}

import contextvars
import logging
import subprocess
import typing


TYPE_CHECKING = False

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ._types import StrPath


class Logger(typing.Protocol):  # pragma: no cover
    def __call__(self, message: str, *, kind: tuple[str, ...] | None = None) -> None: ...


_default_logger = logging.getLogger(typing.cast('str', __spec__.parent))


def _log_default(message: str, *, kind: tuple[str, ...] | None = None) -> None:  # noqa: ARG001
    # the log function that works in tests, real log function is set in __main__
    _default_logger.log(logging.INFO, message, stacklevel=2)


LOGGER = contextvars.ContextVar[Logger]('LOGGER', default=_log_default)
VERBOSITY = contextvars.ContextVar[int]('VERBOSITY', default=0)


def log_subprocess_error(error: subprocess.CalledProcessError) -> None:
    log = LOGGER.get()

    log(subprocess.list2cmdline(error.cmd), kind=('subprocess', 'cmd'))

    for stream_name in ('stdout', 'stderr'):
        stream = getattr(error, stream_name)
        if stream:
            log(stream.decode() if isinstance(stream, bytes) else stream, kind=('subprocess', stream_name))


def run_subprocess(cmd: Sequence[StrPath], cwd: str | None = None, env: Mapping[str, str] | None = None) -> None:
    verbosity = VERBOSITY.get()

    if verbosity > 0:
        log = LOGGER.get()

        with subprocess.Popen(  # noqa: S603
            cmd, cwd=cwd, encoding='utf-8', env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        ) as process:
            log(subprocess.list2cmdline(cmd), kind=('subprocess', 'cmd'))

            assert process.stdout
            for line in process.stdout:
                log(line, kind=('subprocess', 'stdout'))

            code = process.wait()
            if code:  # pragma: no cover
                raise subprocess.CalledProcessError(code, process.args)

    else:
        try:
            subprocess.run(cmd, capture_output=True, check=True, cwd=cwd, env=env)  # noqa: S603
        except subprocess.CalledProcessError as error:
            log_subprocess_error(error)
            raise


if TYPE_CHECKING:
    log: Logger
    verbosity: int

else:

    def __getattr__(name: str) -> Logger | int:
        if name == 'log':
            return LOGGER.get()
        if name == 'verbosity':
            return VERBOSITY.get()
        raise AttributeError(name)  # pragma: no cover


__all__ = [
    'LOGGER',
    'VERBOSITY',
    'log',
    'log_subprocess_error',
    'run_subprocess',
    'verbosity',
]
