from __future__ import print_function
from .main import load_dotenv, find_dotenv

from IPython.core.magic import Magics, magics_class, line_magic
from IPython.core.magic_arguments import (argument, magic_arguments,
                                          parse_argstring)


@magics_class
class IPythonDotEnv(Magics):

    @magic_arguments()
    @argument(
        '-o', '--override', action='store_true',
        help="Indicate to override existing variables"
    )
    @argument(
        '-v', '--verbose', action='store_true',
        help="Indicate function calls to be verbose"
    )
    @argument('dotenv_path', nargs='?', type=str, default='.env',
              help='Search in increasingly higher folders for the `dotenv_path`')
    @line_magic
    def dotenv(self, line):
        args = parse_argstring(self.dotenv, line)
        # Locate the .env file
        dotenv_path = args.dotenv_path
        try:
            dotenv_path = find_dotenv(dotenv_path, True, True)
        except IOError:
            print("cannot find .env file")
            return

        # Load the .env file
        load_dotenv(dotenv_path, verbose=args.verbose, override=args.override)


def load_ipython_extension(ipython):
    """Register the %dotenv magic."""
    ipython.register_magics(IPythonDotEnv)
