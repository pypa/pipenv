# SPDX-License-Identifier: MIT

from __future__ import annotations


__lazy_modules__ = {
    'argparse',
    'build._compat',
    'build._compat.tarfile',
    'build._exceptions',
    'build._util',
    'build.env',
    'functools',
    'hashlib',
    'json',
    'packaging',
    'packaging.utils',
    'packaging.version',
    'platform',
    'pyproject_hooks',
    'shutil',
    'subprocess',
    'tarfile',
    'tempfile',
    'textwrap',
    'traceback',
    'warnings',
    'zipfile',
}

import argparse
import contextlib
import contextvars
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import textwrap
import traceback
import warnings
import zipfile

from functools import partial
from tarfile import TarError
from tarfile import open as tar_open
from typing import NoReturn, TextIO, TypedDict

import pipenv.vendor.pyproject_hooks as pyproject_hooks

from pipenv.vendor.packaging.utils import InvalidSdistFilename, parse_sdist_filename
from pipenv.vendor.packaging.version import InvalidVersion

import pipenv.vendor.build as build
import pipenv.vendor.build.env as _env

from pipenv.vendor.build import ProjectBuilder, _ctx
from pipenv.vendor.build._compat.tarfile import safe_extractall
from pipenv.vendor.build._exceptions import BuildBackendException, BuildException, FailedProcessError
from pipenv.vendor.build._util import format_unmet_dependencies
from pipenv.vendor.build.env import DefaultIsolatedEnv


TYPE_CHECKING = False

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence

    from pipenv.vendor.build._types import ConfigSettings, Distribution, JSONValue, StrPath, SubprocessRunner


class _CliArgs:
    """The arguments :func:`main_parser` produces, typed for the rest of the module."""

    srcdir: str
    verbosity: int
    outdir: str | None
    distributions: list[Distribution] | None
    metadata: bool
    config_settings: list[str] | None
    config_json: str | None
    installer: _env.Installer
    no_isolation: bool
    dependency_constraints_txt: str | None
    skip_dependency_check: bool
    sdist_extract_dir: str | None
    env_dir: str | None
    report: str | None


_COLORS = {
    'red': '\33[91m',
    'green': '\33[92m',
    'yellow': '\33[93m',
    'bold': '\33[1m',
    'dim': '\33[2m',
    'underline': '\33[4m',
    'reset': '\33[0m',
}
_NO_COLORS = dict.fromkeys(_COLORS, '')


_DEFAULT_STYLES = {'stdout': _COLORS, 'stderr': _COLORS}
_styles = contextvars.ContextVar('_styles', default=_DEFAULT_STYLES)


def _init_colors() -> None:
    match os.environ:
        case {'NO_COLOR': _, 'FORCE_COLOR': _}:
            warnings.warn('Both NO_COLOR and FORCE_COLOR environment variables are set, disabling color', stacklevel=2)
            _styles.set({'stdout': _NO_COLORS, 'stderr': _NO_COLORS})
        case {'NO_COLOR': _}:
            _styles.set({'stdout': _NO_COLORS, 'stderr': _NO_COLORS})
        case {'FORCE_COLOR': _}:
            _styles.set({'stdout': _COLORS, 'stderr': _COLORS})
        case _:
            _styles.set(
                {
                    'stdout': _COLORS if sys.stdout.isatty() else _NO_COLORS,
                    'stderr': _COLORS if sys.stderr.isatty() else _NO_COLORS,
                }
            )


def _cprint(fmt: str = '', msg: str = '', file: TextIO | None = None) -> None:
    stream = file or sys.stdout
    key = 'stderr' if stream is sys.stderr else 'stdout'
    print(fmt.format(msg, **_styles.get()[key]), file=file, flush=True)


def _showwarning(
    message: Warning | str,
    category: type[Warning],  # noqa: ARG001
    filename: str,  # noqa: ARG001
    lineno: int,  # noqa: ARG001
    file: TextIO | None = None,
    line: str | None = None,  # noqa: ARG001
) -> None:
    _cprint('{yellow}WARNING{reset} {}', str(message), file if file is not None else sys.stderr)


def _make_logger() -> _ctx.Logger:
    max_terminal_width = shutil.get_terminal_size().columns - 2
    if max_terminal_width <= 0:  # pragma: no cover
        max_terminal_width = 78

    fill = partial(textwrap.fill, subsequent_indent='  ', width=max_terminal_width)

    def emit(message: str, *, indent: str, style: str = '{}') -> None:
        for line in message.splitlines():
            _cprint(style, fill(line, initial_indent=indent), file=sys.stderr)

    # Nested so it cannot be called directly, bypassing the logger setup above.
    def log(message: str, *, kind: tuple[str, ...] | None = None) -> None:
        if _ctx.verbosity < -1:
            return
        match kind:
            case ('step', *_):
                first, _, rest = message.partition('\n')
                _cprint('{bold}{}{reset}', fill(first, initial_indent='* '), file=sys.stderr)
                emit(rest, indent='  ')
            case ('subprocess', 'cmd'):
                emit(message, indent='> ', style='{dim}{}{reset}')
            case ('subprocess', 'stdout' | 'stderr'):
                emit(message, indent='< ', style='{dim}{}{reset}')
            case _:
                emit(message, indent='  ')

    return log


def _setup_cli(*, verbosity: int) -> None:
    warnings.showwarning = _showwarning

    if platform.system() == 'Windows':
        try:
            import colorama

            colorama.init()
        except ModuleNotFoundError:
            pass

    _init_colors()

    _ctx.LOGGER.set(_make_logger())
    _ctx.VERBOSITY.set(verbosity)


def _error(msg: str, code: int = 1) -> NoReturn:  # pragma: no cover
    """
    Print an error message and exit. Will color the output when writing to a TTY.

    :param msg: Error message
    :param code: Error code
    """
    _cprint('{red}ERROR{reset} {}', msg, file=sys.stderr)
    raise SystemExit(code)


@contextlib.contextmanager
def _bootstrap_build_env(
    isolation: bool,
    srcdir: StrPath,
    distribution: Distribution,
    config_settings: ConfigSettings | None,
    skip_dependency_check: bool,
    dependency_constraints_txt: os.PathLike[str] | None,
    installer: _env.Installer,
    env_dir: str | None = None,
    runner: SubprocessRunner | None = None,
) -> Generator[ProjectBuilder]:
    runner = runner or pyproject_hooks.default_subprocess_runner
    if isolation:
        with DefaultIsolatedEnv(installer=installer, path=env_dir) as env:
            builder = ProjectBuilder.from_isolated_env(env, srcdir, runner=runner)

            install = env.install
            if dependency_constraints_txt:
                with open(dependency_constraints_txt, encoding='utf-8') as dependency_constraints_file:
                    constraints_text = dependency_constraints_file.read()
                if constraints_text.strip():
                    # Passed through as a single element instead of re-parsed into lines, so a requirement can never
                    # be split from its `--hash` continuation lines (as produced by `pip-compile --generate-hashes`)
                    # and silently lose its hash check. env.py's installer backends reconstruct the original file via
                    # `'\n'.join(constraints)` (see `_PipInstaller`/`_UvInstaller.install_dependencies`), a no-op here
                    # since there is only one element.
                    install = partial(install, constraints=(constraints_text,))

            # first install the build dependencies
            install(builder.build_system_requires, _fresh=True)
            # then get the extra required dependencies from the backend (which was installed in the call above :P)
            extra_requires = builder.get_requires_for_build(distribution, config_settings)
            install(extra_requires)

            _log_dependency_versions(env, builder.build_system_requires | extra_requires)

            yield builder

    else:
        builder = ProjectBuilder(srcdir, runner=runner)

        if not skip_dependency_check and (missing := builder.check_dependencies(distribution, config_settings)):
            _cprint()
            _error(format_unmet_dependencies(missing))

        yield builder


def _log_dependency_versions(env: DefaultIsolatedEnv, requirements: set[str]) -> None:
    if versions := env.installed_versions(requirements):
        _ctx.log(
            'Installed build dependency versions:\n'
            + '\n'.join(f'- {name}=={version}' for name, version in sorted(versions.items())),
            kind=('step',),
        )


def _build(
    isolation: bool,
    srcdir: StrPath,
    outdir: StrPath,
    distribution: Distribution,
    config_settings: ConfigSettings | None,
    skip_dependency_check: bool,
    dependency_constraints_txt: os.PathLike[str] | None,
    installer: _env.Installer,
    env_dir: str | None = None,
) -> str:
    with _bootstrap_build_env(
        isolation,
        srcdir,
        distribution,
        config_settings,
        skip_dependency_check,
        dependency_constraints_txt,
        installer,
        env_dir,
        pyproject_hooks.quiet_subprocess_runner if _ctx.verbosity < 0 else None,
    ) as builder:
        return builder.build(distribution, outdir, config_settings)


@contextlib.contextmanager
def _handle_build_error(*, env_dir: str | None, sdist_extract_dir: StrPath | None) -> Generator[None]:
    try:
        yield
    except (BuildException, FailedProcessError) as e:
        _error(str(e))
    except BuildBackendException as e:
        hint = _build_failure_hint(env_dir, sdist_extract_dir)
        if isinstance(e.exception, subprocess.CalledProcessError):
            _cprint()
            _cprint('{yellow}TIP{reset} {}', hint, file=sys.stderr)
            _error(str(e))

        inner_exception = e.exception
        tb_lines = traceback.format_exception(inner_exception, limit=-1)
        tb = ''.join(tb_lines)
        _cprint('\n{dim}{}{reset}\n', tb.strip('\n'))
        _cprint('{yellow}TIP{reset} {}', hint, file=sys.stderr)
        _error(str(e))
    except Exception as e:  # pragma: no cover
        tb = traceback.format_exc().strip('\n')
        _cprint('\n{dim}{}{reset}\n', tb)
        _error(str(e))


def _build_failure_hint(env_dir: str | None, sdist_extract_dir: StrPath | None) -> str:
    kept = [
        f'{label} at {os.fspath(path)}'
        for path, label in ((env_dir, 'the build environment'), (sdist_extract_dir, 'the extracted sources'))
        if path is not None
    ]
    if kept:
        action = f'inspect {" and ".join(kept)}'
    else:
        action = 'pass --env-dir and --sdist-extract-dir to keep the build environment and sources'
    docs = 'https://build.pypa.io/en/stable/how-to/troubleshooting.html#debug-a-failed-build'
    return f'{action}, then see {docs} for help debugging a failed build'


def _natural_language_list(elements: Sequence[str]) -> str:
    if len(elements) == 0:
        msg = 'no elements'
        raise IndexError(msg)
    if len(elements) == 1:
        return elements[0]
    return '{} and {}'.format(
        ', '.join(elements[:-1]),
        elements[-1],
    )


def build_package(
    srcdir: StrPath,
    outdir: StrPath,
    distributions: Sequence[Distribution],
    config_settings: ConfigSettings | None = None,
    isolation: bool = True,
    skip_dependency_check: bool = False,
    dependency_constraints_txt: os.PathLike[str] | None = None,
    installer: _env.Installer = 'pip',
    env_dir: str | None = None,
) -> list[str]:
    """
    Run the build process.

    :param srcdir: Source directory
    :param outdir: Output directory
    :param distribution: Distribution to build (sdist or wheel)
    :param config_settings: Configuration settings to be passed to the backend
    :param isolation: Isolate the build in a separate environment
    :param skip_dependency_check: Do not perform the dependency check
    :param env_dir: Location of the isolated build environment (a temporary directory is used when not set)
    """
    built: list[str] = []
    for distribution in distributions:
        out = _build(
            isolation,
            srcdir,
            outdir,
            distribution,
            config_settings,
            skip_dependency_check,
            dependency_constraints_txt,
            installer,
            env_dir,
        )
        built.append(os.path.basename(out))
    return built


def build_package_via_sdist(
    srcdir: StrPath,
    outdir: StrPath,
    distributions: Sequence[Distribution],
    config_settings: ConfigSettings | None = None,
    isolation: bool = True,
    skip_dependency_check: bool = False,
    dependency_constraints_txt: os.PathLike[str] | None = None,
    installer: _env.Installer = 'pip',
    sdist_extract_dir: StrPath | None = None,
    env_dir: str | None = None,
) -> list[str]:
    """
    Build a sdist and then the specified distributions from it.

    :param srcdir: Source directory
    :param outdir: Output directory
    :param distribution: Distribution to build (only wheel)
    :param config_settings: Configuration settings to be passed to the backend
    :param isolation: Isolate the build in a separate environment
    :param skip_dependency_check: Do not perform the dependency check
    :param sdist_extract_dir: Directory to extract the intermediate sdist into; a temporary directory is used and
        removed afterwards when ``None``
    :param env_dir: Location of the isolated build environment (a temporary directory is used when not set)
    """
    if 'sdist' in distributions:
        msg = 'Only binary distributions are allowed but sdist was specified'
        raise ValueError(msg)

    sdist = _build(
        isolation,
        srcdir,
        outdir,
        'sdist',
        config_settings,
        skip_dependency_check,
        dependency_constraints_txt,
        installer,
        env_dir,
    )

    sdist_name = os.path.basename(sdist)
    built: list[str] = []
    if distributions:
        top_level = _validate_sdist_archive(sdist)
        with _extract_sdist(sdist, top_level, extract_dir=sdist_extract_dir) as extracted_srcdir:
            _ctx.log(f'Building {_natural_language_list(distributions)} from sdist', kind=('step',))
            for distribution in distributions:
                out = _build(
                    isolation,
                    extracted_srcdir,
                    outdir,
                    distribution,
                    config_settings,
                    skip_dependency_check,
                    dependency_constraints_txt,
                    installer,
                    env_dir,
                )
                built.append(os.path.basename(out))
    return [sdist_name, *built]


def _build_metadata(
    srcdir: StrPath,
    outdir: StrPath,  # noqa: ARG001
    distributions: Sequence[Distribution],  # noqa: ARG001
    config_settings: ConfigSettings | None = None,
    isolation: bool = True,
    skip_dependency_check: bool = False,
    dependency_constraints_txt: os.PathLike[str] | None = None,
    installer: _env.Installer = 'pip',
    env_dir: str | None = None,
) -> list[str]:
    if os.path.isfile(srcdir) and os.fspath(srcdir).lower().endswith('.whl'):
        _print_metadata(_wheel_metadata(srcdir))
        return []

    def run_subprocess(cmd: Sequence[StrPath], cwd: str | None = None, extra_environ: Mapping[str, str] | None = None) -> None:
        env = os.environ.copy()
        if extra_environ:
            env.update(extra_environ)
        _ctx.run_subprocess(cmd, cwd, env)

    with (
        _bootstrap_build_env(
            isolation,
            srcdir,
            'wheel',
            config_settings,
            skip_dependency_check,
            dependency_constraints_txt,
            installer,
            env_dir,
            runner=run_subprocess,
        ) as builder,
        tempfile.TemporaryDirectory() as tempdir,
        open(
            os.path.join(builder.metadata_path(tempdir), 'METADATA'),
            'rb',
        ) as metadata_file,
    ):
        _print_metadata(metadata_file.read())

    return []


def _wheel_metadata(wheel: StrPath) -> bytes:
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.count('/') == 1 and name.endswith('.dist-info/METADATA')]
        if len(names) != 1:
            msg = f'{os.fspath(wheel)!r} is not a valid wheel: expected one .dist-info/METADATA, found {len(names)}'
            raise BuildException(msg)
        return archive.read(names[0])


def _print_metadata(raw_metadata: bytes) -> None:
    import pipenv.vendor.packaging.metadata as packaging_metadata

    valid_metadata, _ = packaging_metadata.parse_email(raw_metadata)
    print(  # noqa: T201
        json.dumps(valid_metadata, ensure_ascii=False, indent=2),
    )


def main_parser() -> argparse.ArgumentParser:
    """
    Construct the main parser.
    """

    class NegativeCountAction(argparse.Action):
        def __init__(
            self,
            option_strings: Sequence[str],
            dest: str,
            default: int | None = None,
            help: str | None = None,
        ) -> None:
            super().__init__(
                option_strings=option_strings,
                dest=dest,
                nargs=0,
                default=default,
                help=help,
            )

        def __call__(
            self,
            parser: argparse.ArgumentParser,  # noqa: ARG002
            namespace: argparse.Namespace,
            values: str | Sequence[str] | None,  # noqa: ARG002
            option_string: str | None = None,  # noqa: ARG002
        ) -> None:
            setattr(namespace, self.dest, getattr(namespace, self.dest, 0) - 1)

    make_parser = partial(
        argparse.ArgumentParser,
        add_help=False,
        description="""\
    A simple, correct Python build frontend.

    By default, a source distribution (sdist) is built from the project root
    and a binary distribution (wheel) is built from the sdist.
    If this is undesirable, you can pass `--sdist` and/or `--wheel`
    to build distributions independently of each other.
    """.rstrip(),
        # Prevent argparse from taking up the entire width of the terminal window
        # which impedes readability. Also keep the description formatted.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    if sys.version_info >= (3, 14):  # pragma: no branch
        make_parser = partial(make_parser, suggest_on_error=True)  # pragma: no cover

    parser = make_parser()
    parser.add_argument(
        'srcdir',
        type=str,
        nargs='?',
        default=os.getcwd(),
        help='source directory, .tar.gz source distribution, or (with --metadata) a .whl to read metadata from '
        '(defaults to the current working directory)',
    )

    global_group = parser.add_argument_group('global options')
    global_group.add_argument(
        '-h',
        '--help',
        action='help',
        default=argparse.SUPPRESS,
        help='show this help message and exit',
    )
    global_group.add_argument(
        '--version',
        '-V',
        action='version',
        version=f'build {build.__version__} ({",".join(build.__path__)})',
    )
    verbosity_exclusive_group = global_group.add_mutually_exclusive_group()
    verbosity_exclusive_group.add_argument(
        '--quiet',
        '-q',
        dest='verbosity',
        action=NegativeCountAction,
        default=0,
        help='reduce verbosity',
    )
    verbosity_exclusive_group.add_argument(
        '--verbose',
        '-v',
        dest='verbosity',
        action='count',
        default=0,
        help='increase verbosity',
    )

    build_group = parser.add_argument_group('build options')
    build_group.add_argument(
        '--outdir',
        '-o',
        help=f'output directory (defaults to {{srcdir}}{os.sep}dist).  Cannot be used together with ``--metadata``',
        metavar='PATH',
    )
    build_group.add_argument(
        '--sdist-extract-dir',
        help='extract the intermediate sdist to PATH (created if missing and kept afterwards) instead of a random '
        'temporary directory; reusing it across rebuilds gives compiler caches such as ccache/sccache a stable '
        'source path. Only affects the default (via-sdist) build and building a wheel from an sdist',
        metavar='PATH',
    )
    build_group.add_argument(
        '--sdist',
        '-s',
        dest='distributions',
        action='append_const',
        const='sdist',
        help='build a source distribution (disables the default behavior)',
    )
    build_group.add_argument(
        '--wheel',
        '-w',
        dest='distributions',
        action='append_const',
        const='wheel',
        help='build a wheel (disables the default behavior)',
    )
    build_group.add_argument(
        '--metadata',
        action='store_true',
        help="print out a wheel's metadata in JSON format, building it first unless the source argument is already a "
        '.whl. Cannot be used in conjunction with ``--sdist`` or ``--wheel``',
    )
    build_group.add_argument(
        '--report',
        help='write a machine-readable JSON report of the built artifacts (name, path, kind, size and SHA-256 hash) '
        'to this path. Cannot be used together with ``--metadata``',
        metavar='PATH',
    )
    config_exclusive_group = build_group.add_mutually_exclusive_group()
    config_exclusive_group.add_argument(
        '--config-setting',
        '-C',
        dest='config_settings',
        action='append',
        help='settings to pass to the backend.  Multiple settings can be provided. '
        'Settings beginning with a hyphen will erroneously be interpreted as options to build if separated '
        'by a space; use ``--config-setting=--my-setting -C--my-other-setting`` instead. '
        'A setting passed without ``=VALUE`` is given an empty value, but this form is not supported by pip; '
        'write ``KEY=`` instead for compatibility',
        metavar='KEY=[VALUE]',
    )
    config_exclusive_group.add_argument(
        '--config-json',
        help='settings to pass to the backend as a JSON object. '
        'This is an alternative to ``--config-setting`` that allows complex nested structures. '
        'Cannot be used together with ``--config-setting``',
        metavar='JSON_STRING',
    )

    install_group = parser.add_argument_group('installation options')
    env_exclusive_group = install_group.add_mutually_exclusive_group()
    env_exclusive_group.add_argument(
        '--installer',
        choices=_env.INSTALLERS,
        default='pip',
        help='Python package installer to use (defaults to pip)',
    )
    env_exclusive_group.add_argument(
        '--no-isolation',
        '-n',
        action='store_true',
        help='disable building the project in an isolated virtual environment. '
        'Build dependencies must be installed separately when this option is used',
    )
    install_group.add_argument(
        '--env-dir',
        help='create the isolated build environment at this location instead of a temporary directory. The location '
        'must be empty; it is removed on success and kept on failure so it can be inspected',
        metavar='PATH',
    )
    install_group.add_argument(
        '--dependency-constraints-txt',
        help='constrain build dependencies using a constraints.txt when installing dependencies',
        metavar='PATH',
    )
    install_group.add_argument(
        '--skip-dependency-check',
        '-x',
        action='store_true',
        help='do not check that build dependencies are installed',
    )

    return parser


def _parse_config_settings(raw_config_settings: list[str]) -> dict[str, str | list[str]]:
    config_settings = dict[str, str | list[str]]()

    for arg in raw_config_settings:
        setting, sep, value = arg.partition('=')
        if not sep:
            warnings.warn(
                f'Config setting {setting!r} was passed without a value; this form is not supported by pip. '
                f'Write {setting}= instead to be compatible with both tools',
                stacklevel=2,
            )
        existing = config_settings.get(setting)
        if existing is None:
            config_settings[setting] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            config_settings[setting] = [existing, value]

    return config_settings


def main(cli_args: Sequence[str], prog: str | None = None) -> None:
    """
    Parse the CLI arguments and invoke the build process.

    :param cli_args: CLI arguments
    :param prog: Program name to show in help text
    """
    parser = main_parser()
    if prog:
        parser.prog = prog
    args = parser.parse_args(cli_args, _CliArgs())

    if args.env_dir is not None and args.no_isolation:
        parser.error('--env-dir: not allowed with --no-isolation')

    _setup_cli(verbosity=args.verbosity)

    is_file = os.path.isfile(args.srcdir)
    sdist_input = is_file and os.fspath(args.srcdir).lower().endswith('.tar.gz')
    wheel_input = is_file and os.fspath(args.srcdir).lower().endswith('.whl')
    run_build = partial(
        _select_build(parser, args, sdist_input=sdist_input, wheel_input=wheel_input),
        config_settings=_resolve_config_settings(args),
        isolation=not args.no_isolation,
        skip_dependency_check=args.skip_dependency_check,
        dependency_constraints_txt=args.dependency_constraints_txt,
        installer=args.installer,
        env_dir=args.env_dir,
    )

    if args.outdir is not None:
        outdir = args.outdir
    elif sdist_input or wheel_input:
        outdir = os.path.dirname(os.path.abspath(args.srcdir))
    else:
        outdir = os.path.join(args.srcdir, 'dist')

    with _handle_build_error(env_dir=args.env_dir, sdist_extract_dir=args.sdist_extract_dir):
        if sdist_input:
            top_level = _validate_sdist_archive(args.srcdir)
            with _extract_sdist(args.srcdir, top_level, extract_dir=args.sdist_extract_dir) as extracted_srcdir:
                built = run_build(extracted_srcdir, outdir)
        else:
            built = run_build(args.srcdir, outdir)
        if args.report is not None:
            _write_report(args.report, outdir, built)
        if _ctx.verbosity >= -1 and built:
            artifact_list = _natural_language_list(
                ['{underline}{}{reset}{bold}{green}'.format(artifact, **_styles.get()['stdout']) for artifact in built]
            )
            _cprint('{bold}{green}Successfully built {}{reset}', artifact_list)


class _ArtifactReport(TypedDict):
    name: str
    path: str
    kind: str
    size: int
    hashes: dict[str, str]


class _BuildReport(TypedDict):
    version: str
    artifacts: list[_ArtifactReport]


def _write_report(path: StrPath, outdir: StrPath, artifacts: Sequence[str]) -> None:
    report: _BuildReport = {
        'version': '1.0',
        'artifacts': [_describe_artifact(os.path.join(outdir, name), name) for name in artifacts],
    }
    data = json.dumps(report, indent=2) + '\n'

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as report_file:
            report_file.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _describe_artifact(path: str, name: str) -> _ArtifactReport:
    digest = hashlib.sha256()
    size = 0
    with open(path, 'rb') as artifact:
        while chunk := artifact.read(65536):
            size += len(chunk)
            digest.update(chunk)
    return {
        'name': name,
        'path': path,
        'kind': 'sdist' if name.endswith('.tar.gz') else 'wheel',
        'size': size,
        'hashes': {'sha256': digest.hexdigest()},
    }


def _resolve_config_settings(args: _CliArgs) -> Mapping[str, JSONValue]:
    if args.config_json:
        try:
            config_settings = json.loads(args.config_json)
        except json.JSONDecodeError as e:
            _error(f'Invalid JSON in --config-json: {e}')
        if not isinstance(config_settings, dict):
            _error('--config-json must contain a JSON object (dict), not a list or primitive value')
        return config_settings
    if args.config_settings:
        return _parse_config_settings(args.config_settings)
    return {}


def _select_build(
    parser: argparse.ArgumentParser, args: _CliArgs, *, sdist_input: bool, wheel_input: bool
) -> partial[list[str]]:
    if args.report is not None and args.metadata:
        parser.error('--report: not allowed with --metadata')
    if wheel_input and not args.metadata:
        parser.error('a wheel can only be used with --metadata, to read its metadata; it cannot be built from')
    if args.metadata and args.distributions:
        parser.error('--metadata: not allowed with --sdist or --wheel')
    if sdist_input and args.distributions and 'sdist' in args.distributions:
        parser.error(
            'cannot build a source distribution from a source distribution; '
            'pass --wheel to build a wheel from the sdist (see https://github.com/pypa/build/issues/311)'
        )
    if args.metadata:
        return partial(_build_metadata, distributions=['wheel'])
    if sdist_input:
        distributions: list[Distribution] = args.distributions or ['wheel']
        return partial(build_package, distributions=distributions)
    if args.distributions:
        return partial(build_package, distributions=args.distributions)
    return partial(build_package_via_sdist, distributions=['wheel'], sdist_extract_dir=args.sdist_extract_dir)


def _validate_sdist_archive(archive: StrPath) -> str:
    """Validate that ``archive`` is a PEP 625 source distribution and return its top-level directory name."""
    name = os.path.basename(os.fspath(archive))
    try:
        parse_sdist_filename(name)
    except (InvalidSdistFilename, InvalidVersion) as exc:
        msg = f'{name!r} does not look like a source distribution: {exc}'
        raise BuildException(msg) from exc

    try:
        with tar_open(archive) as tar:
            members = tar.getmembers()
    except (OSError, TarError) as exc:
        msg = f'failed to read source distribution {archive}: {exc}'
        raise BuildException(msg) from exc

    top_levels = {m.name.split('/', 1)[0] for m in members if m.name}
    top_levels.discard('')
    if len(top_levels) != 1:
        msg = f'source distribution {archive} must contain a single top-level directory, got: {sorted(top_levels)}'
        raise BuildException(msg)

    top = next(iter(top_levels))
    if not any(m.name == f'{top}/PKG-INFO' and m.isfile() for m in members):
        msg = (
            f'source distribution {archive} does not contain {top}/PKG-INFO; '
            'this does not appear to be a valid source distribution'
        )
        raise BuildException(msg)
    return top


@contextlib.contextmanager
def _extract_sdist(archive: StrPath, top_level: str, *, extract_dir: StrPath | None = None) -> Generator[str]:
    if extract_dir is None:
        tmp_dir = tempfile.mkdtemp(prefix='build-via-sdist-')
        try:
            with tar_open(archive) as tar:
                safe_extractall(tar, tmp_dir)
            yield os.path.join(tmp_dir, top_level)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        root = os.fspath(extract_dir)
        os.makedirs(root, exist_ok=True)
        target = os.path.join(root, top_level)
        shutil.rmtree(target, ignore_errors=True)
        with tar_open(archive) as tar:
            safe_extractall(tar, root)
        yield target


def entrypoint() -> None:
    main(sys.argv[1:])


if __name__ == '__main__':  # pragma: no cover
    main(sys.argv[1:], 'python -m build')


__all__ = [
    'main',
    'main_parser',
]
