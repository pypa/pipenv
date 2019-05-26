from __future__ import absolute_import, print_function

# Add NullHandler to "pythonfinder" logger, because Python2's default root
# logger has no handler and warnings like this would be reported:
#
# > No handlers could be found for logger "pythonfinder.models.pyenv"
import logging

from .exceptions import InvalidPythonVersion
from .models import SystemPath, WindowsFinder
from .pythonfinder import Finder

__version__ = "1.2.1"


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = ["Finder", "WindowsFinder", "SystemPath", "InvalidPythonVersion"]
