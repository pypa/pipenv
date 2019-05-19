"""Base Command class, and related routines"""
from __future__ import absolute_import, print_function

import logging
import logging.config
import optparse
import os
import platform
import sys
import traceback

from pipenv.patched.notpip._internal.cli import cmdoptions
from pipenv.patched.notpip._internal.cli.parser import (
    ConfigOptionParser, UpdatingDefaultsHelpFormatter,
)
from pipenv.patched.notpip._internal.cli.status_codes import (
    ERROR, PREVIOUS_BUILD_DIR_ERROR, SUCCESS, UNKNOWN_ERROR,
    VIRTUALENV_NOT_FOUND,
)
from pipenv.patched.notpip._internal.download import PipSession
from pipenv.patched.notpip._internal.exceptions import (
    BadCommand, CommandError, InstallationError, PreviousBuildDirError,
    UninstallationError,
)
from pipenv.patched.notpip._internal.index import PackageFinder
from pipenv.patched.notpip._internal.locations import running_under_virtualenv
from pipenv.patched.notpip._internal.req.constructors import (
    install_req_from_editable, install_req_from_line,
)
from pipenv.patched.notpip._internal.req.req_file import parse_requirements
from pipenv.patched.notpip._internal.utils.deprecation import deprecated
from pipenv.patched.notpip._internal.utils.logging import BrokenStdoutLoggingError, setup_logging
from pipenv.patched.notpip._internal.utils.misc import (
    get_prog, normalize_path, redact_password_from_url,
)
from pipenv.patched.notpip._internal.utils.outdated import pip_version_check
from pipenv.patched.notpip._internal.utils.typing import MYPY_CHECK_RUNNING

if MYPY_CHECK_RUNNING:
    from typing import Optional, List, Tuple, Any  # noqa: F401
    from optparse import Values  # noqa: F401
    from pipenv.patched.notpip._internal.cache import WheelCache  # noqa: F401
    from pipenv.patched.notpip._internal.req.req_set import RequirementSet  # noqa: F401

__all__ = ['Command']

logger = logging.getLogger(__name__)


class Command(object):
    name = None  # type: Optional[str]
    usage = None  # type: Optional[str]
    hidden = False  # type: bool
    ignore_require_venv = False  # type: bool

    def __init__(self, isolated=False):
        # type: (bool) -> None
        parser_kw = {
            'usage': self.usage,
            'prog': '%s %s' % (get_prog(), self.name),
            'formatter': UpdatingDefaultsHelpFormatter(),
            'add_help_option': False,
            'name': self.name,
            'description': self.__doc__,
            'isolated': isolated,
        }

        self.parser = ConfigOptionParser(**parser_kw)

        # Commands should add options to this option group
        optgroup_name = '%s Options' % self.name.capitalize()
        self.cmd_opts = optparse.OptionGroup(self.parser, optgroup_name)

        # Add the general options
        gen_opts = cmdoptions.make_option_group(
            cmdoptions.general_group,
            self.parser,
        )
        self.parser.add_option_group(gen_opts)

    def run(self, options, args):
        # type: (Values, List[Any]) -> Any
        raise NotImplementedError

    def _build_session(self, options, retries=None, timeout=None):
        # type: (Values, Optional[int], Optional[int]) -> PipSession
        session = PipSession(
            cache=(
                normalize_path(os.path.join(options.cache_dir, "http"))
                if options.cache_dir else None
            ),
            retries=retries if retries is not None else options.retries,
            insecure_hosts=options.trusted_hosts,
        )

        # Handle custom ca-bundles from the user
        if options.cert:
            session.verify = options.cert

        # Handle SSL client certificate
        if options.client_cert:
            session.cert = options.client_cert

        # Handle timeouts
        if options.timeout or timeout:
            session.timeout = (
                timeout if timeout is not None else options.timeout
            )

        # Handle configured proxies
        if options.proxy:
            session.proxies = {
                "http": options.proxy,
                "https": options.proxy,
            }

        # Determine if we can prompt the user for authentication or not
        session.auth.prompting = not options.no_input

        return session

    def parse_args(self, args):
        # type: (List[str]) -> Tuple
        # factored out for testability
        return self.parser.parse_args(args)

    def main(self, args):
        # type: (List[str]) -> int
        options, args = self.parse_args(args)

        # Set verbosity so that it can be used elsewhere.
        self.verbosity = options.verbose - options.quiet

        level_number = setup_logging(
            verbosity=self.verbosity,
            no_color=options.no_color,
            user_log_file=options.log,
        )

        if sys.version_info[:2] == (3, 4):
            deprecated(
                "Python 3.4 support has been deprecated. pip 19.1 will be the "
                "last one supporting it. Please upgrade your Python as Python "
                "3.4 won't be maintained after March 2019 (cf PEP 429).",
                replacement=None,
                gone_in='19.2',
            )
        elif sys.version_info[:2] == (2, 7):
            message = (
                "A future version of pip will drop support for Python 2.7."
            )
            if platform.python_implementation() == "CPython":
                message = (
                    "Python 2.7 will reach the end of its life on January "
                    "1st, 2020. Please upgrade your Python as Python 2.7 "
                    "won't be maintained after that date. "
                ) + message
            deprecated(message, replacement=None, gone_in=None)

        # TODO: Try to get these passing down from the command?
        #       without resorting to os.environ to hold these.
        #       This also affects isolated builds and it should.

        if options.no_input:
            os.environ['PIP_NO_INPUT'] = '1'

        if options.exists_action:
            os.environ['PIP_EXISTS_ACTION'] = ' '.join(options.exists_action)

        if options.require_venv and not self.ignore_require_venv:
            # If a venv is required check if it can really be found
            if not running_under_virtualenv():
                logger.critical(
                    'Could not find an activated virtualenv (required).'
                )
                sys.exit(VIRTUALENV_NOT_FOUND)

        try:
            status = self.run(options, args)
            # FIXME: all commands should return an exit status
            # and when it is done, isinstance is not needed anymore
            if isinstance(status, int):
                return status
        except PreviousBuildDirError as exc:
            logger.critical(str(exc))
            logger.debug('Exception information:', exc_info=True)

            return PREVIOUS_BUILD_DIR_ERROR
        except (InstallationError, UninstallationError, BadCommand) as exc:
            logger.critical(str(exc))
            logger.debug('Exception information:', exc_info=True)

            return ERROR
        except CommandError as exc:
            logger.critical('ERROR: %s', exc)
            logger.debug('Exception information:', exc_info=True)

            return ERROR
        except BrokenStdoutLoggingError:
            # Bypass our logger and write any remaining messages to stderr
            # because stdout no longer works.
            print('ERROR: Pipe to stdout was broken', file=sys.stderr)
            if level_number <= logging.DEBUG:
                traceback.print_exc(file=sys.stderr)

            return ERROR
        except KeyboardInterrupt:
            logger.critical('Operation cancelled by user')
            logger.debug('Exception information:', exc_info=True)

            return ERROR
        except BaseException:
            logger.critical('Exception:', exc_info=True)

            return UNKNOWN_ERROR
        finally:
            allow_version_check = (
                # Does this command have the index_group options?
                hasattr(options, "no_index") and
                # Is this command allowed to perform this check?
                not (options.disable_pip_version_check or options.no_index)
            )
            # Check if we're using the latest version of pip available
            if allow_version_check:
                session = self._build_session(
                    options,
                    retries=0,
                    timeout=min(5, options.timeout)
                )
                with session:
                    pip_version_check(session, options)

            # Shutdown the logging module
            logging.shutdown()

        return SUCCESS


class RequirementCommand(Command):

    @staticmethod
    def populate_requirement_set(requirement_set,  # type: RequirementSet
                                 args,             # type: List[str]
                                 options,          # type: Values
                                 finder,           # type: PackageFinder
                                 session,          # type: PipSession
                                 name,             # type: str
                                 wheel_cache       # type: Optional[WheelCache]
                                 ):
        # type: (...) -> None
        """
        Marshal cmd line args into a requirement set.
        """
        # NOTE: As a side-effect, options.require_hashes and
        #       requirement_set.require_hashes may be updated

        for filename in options.constraints:
            for req_to_add in parse_requirements(
                    filename,
                    constraint=True, finder=finder, options=options,
                    session=session, wheel_cache=wheel_cache):
                req_to_add.is_direct = True
                requirement_set.add_requirement(req_to_add)

        for req in args:
            req_to_add = install_req_from_line(
                req, None, isolated=options.isolated_mode,
                use_pep517=options.use_pep517,
                wheel_cache=wheel_cache
            )
            req_to_add.is_direct = True
            requirement_set.add_requirement(req_to_add)

        for req in options.editables:
            req_to_add = install_req_from_editable(
                req,
                isolated=options.isolated_mode,
                use_pep517=options.use_pep517,
                wheel_cache=wheel_cache
            )
            req_to_add.is_direct = True
            requirement_set.add_requirement(req_to_add)

        for filename in options.requirements:
            for req_to_add in parse_requirements(
                    filename,
                    finder=finder, options=options, session=session,
                    wheel_cache=wheel_cache,
                    use_pep517=options.use_pep517):
                req_to_add.is_direct = True
                requirement_set.add_requirement(req_to_add)
        # If --require-hashes was a line in a requirements file, tell
        # RequirementSet about it:
        requirement_set.require_hashes = options.require_hashes

        if not (args or options.editables or options.requirements):
            opts = {'name': name}
            if options.find_links:
                raise CommandError(
                    'You must give at least one requirement to %(name)s '
                    '(maybe you meant "pip %(name)s %(links)s"?)' %
                    dict(opts, links=' '.join(options.find_links)))
            else:
                raise CommandError(
                    'You must give at least one requirement to %(name)s '
                    '(see "pip help %(name)s")' % opts)

    def _build_package_finder(
        self,
        options,               # type: Values
        session,               # type: PipSession
        platform=None,         # type: Optional[str]
        python_versions=None,  # type: Optional[List[str]]
        abi=None,              # type: Optional[str]
        implementation=None    # type: Optional[str]
    ):
        # type: (...) -> PackageFinder
        """
        Create a package finder appropriate to this requirement command.
        """
        index_urls = [options.index_url] + options.extra_index_urls
        if options.no_index:
            logger.debug(
                'Ignoring indexes: %s',
                ','.join(redact_password_from_url(url) for url in index_urls),
            )
            index_urls = []

        return PackageFinder(
            find_links=options.find_links,
            format_control=options.format_control,
            index_urls=index_urls,
            trusted_hosts=options.trusted_hosts,
            allow_all_prereleases=options.pre,
            session=session,
            platform=platform,
            versions=python_versions,
            abi=abi,
            implementation=implementation,
            prefer_binary=options.prefer_binary,
        )
