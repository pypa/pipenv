"""
Click is a simple Python module inspired by the stdlib optparse to make
writing command line scripts fun. Unlike other modules, it's based
around a simple API that does not come with too much magic and is
composable.
"""
from .core import Argument
from .core import BaseCommand
from .core import Command
from .core import CommandCollection
from .core import Context
from .core import Group
from .core import MultiCommand
from .core import Option
from .core import Parameter
from .decorators import argument
from .decorators import command
from .decorators import confirmation_option
from .decorators import group
from .decorators import help_option
from .decorators import make_pass_decorator
from .decorators import option
from .decorators import pass_context
from .decorators import pass_obj
from .decorators import password_option
from .decorators import version_option
from .exceptions import Abort
from .exceptions import BadArgumentUsage
from .exceptions import BadOptionUsage
from .exceptions import BadParameter
from .exceptions import ClickException
from .exceptions import FileError
from .exceptions import MissingParameter
from .exceptions import NoSuchOption
from .exceptions import UsageError
from .formatting import HelpFormatter
from .formatting import wrap_text
from .globals import get_current_context
from .parser import OptionParser
from .termui import clear
from .termui import confirm
from .termui import echo_via_pager
from .termui import edit
from .termui import get_terminal_size
from .termui import getchar
from .termui import launch
from .termui import pause
from .termui import progressbar
from .termui import prompt
from .termui import secho
from .termui import style
from .termui import unstyle
from .types import BOOL
from .types import Choice
from .types import DateTime
from .types import File
from .types import FLOAT
from .types import FloatRange
from .types import INT
from .types import IntRange
from .types import ParamType
from .types import Path
from .types import STRING
from .types import Tuple
from .types import UNPROCESSED
from .types import UUID
from .utils import echo
from .utils import format_filename
from .utils import get_app_dir
from .utils import get_binary_stream
from .utils import get_os_args
from .utils import get_text_stream
from .utils import open_file

# Controls if click should emit the warning about the use of unicode
# literals.
disable_unicode_literals_warning = False

__version__ = "7.1.1"
