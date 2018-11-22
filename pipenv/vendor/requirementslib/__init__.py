# -*- coding=utf-8 -*-
__version__ = '1.3.2'

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
