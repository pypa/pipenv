# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function
__version__ = '1.4.0'

import logging
import warnings
from vistir.compat import ResourceWarning

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
warnings.filterwarnings("ignore", category=ResourceWarning)

from .models.requirements import Requirement
from .models.lockfile import Lockfile
from .models.pipfile import Pipfile

__all__ = ["Lockfile", "Pipfile", "Requirement"]
