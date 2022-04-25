# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import logging
import warnings

import setuptools

from .models.lockfile import Lockfile
from .models.pipfile import Pipfile
from .models.requirements import Requirement

__version__ = "1.6.4"


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
warnings.filterwarnings("ignore", category=ResourceWarning)


__all__ = ["Lockfile", "Pipfile", "Requirement"]
