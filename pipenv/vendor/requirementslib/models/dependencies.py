import atexit
import os

from pipenv.patched.pip._internal.index.package_finder import PackageFinder
from pipenv.patched.pip._vendor.platformdirs import user_cache_dir

from ..utils import get_package_finder, get_pip_command, prepare_pip_source_args

CACHE_DIR = os.environ.get("PIPENV_CACHE_DIR", user_cache_dir("pipenv"))


def is_python(section):
    return section.startswith("[") and ":" in section


def get_pip_options(args=None, sources=None, pip_command=None):
    """Build a pip command from a list of sources.

    :param args: positional arguments passed through to the pip parser
    :param sources: A list of pipfile-formatted sources, defaults to None
    :param sources: list[dict], optional
    :param pip_command: A pre-built pip command instance
    :type pip_command: :class:`~pipenv.patched.pip._internal.cli.base_command.Command`
    :return: An instance of pip_options using the supplied arguments plus sane defaults
    :rtype: :class:`~pipenv.patched.pip._internal.cli.cmdoptions`
    """

    if not pip_command:
        pip_command = get_pip_command()
    if not sources:
        sources = [{"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}]
    os.makedirs(CACHE_DIR, mode=0o777, exist_ok=True)
    pip_args = args or []
    pip_args = prepare_pip_source_args(sources, pip_args)
    pip_options, _ = pip_command.parser.parse_args(pip_args)
    pip_options.cache_dir = CACHE_DIR
    return pip_options


def get_finder(sources=None, pip_command=None, pip_options=None) -> PackageFinder:
    """Get a package finder for looking up candidates to install.

    :param sources: A list of pipfile-formatted sources, defaults to None
    :param sources: list[dict], optional
    :param pip_command: A pip command instance, defaults to None
    :type pip_command: :class:`~pipenv.patched.pip._internal.cli.base_command.Command`
    :param pip_options: A pip options, defaults to None
    :type pip_options: :class:`~pipenv.patched.pip._internal.cli.cmdoptions`
    :return: A package finder
    :rtype: :class:`~pipenv.patched.pip._internal.index.PackageFinder`
    """

    if not pip_command:
        pip_command = get_pip_command()
    if not sources:
        sources = [{"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}]
    if not pip_options:
        pip_options = get_pip_options(sources=sources, pip_command=pip_command)
    session = pip_command._build_session(pip_options)
    atexit.register(session.close)
    finder = get_package_finder(get_pip_command(), options=pip_options, session=session)
    return session, finder
