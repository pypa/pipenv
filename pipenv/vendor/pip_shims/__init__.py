# -*- coding=utf-8 -*-
from __future__ import absolute_import

import sys

__version__ = '0.3.2'

from . import shims


old_module = sys.modules[__name__]


module = sys.modules[__name__] = shims._new()
module.shims = shims
module.__dict__.update({
    '__file__': __file__,
    '__package__': "pip_shims",
    '__path__': __path__,
    '__doc__': __doc__,
    '__all__': module.__all__ + ['shims',],
    '__version__': __version__,
    '__name__': __name__
})
