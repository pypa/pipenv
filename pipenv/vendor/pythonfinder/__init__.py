from __future__ import print_function, absolute_import

__version__ = '1.1.10'

# Add NullHandler to "pythonfinder" logger, because Python2's default root
# logger has no handler and warnings like this would be reported:
#
# > No handlers could be found for logger "pythonfinder.models.pyenv"
import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = ["Finder", "WindowsFinder", "SystemPath", "InvalidPythonVersion"]
from .pythonfinder import Finder
from .models import SystemPath, WindowsFinder
from .exceptions import InvalidPythonVersion
