# -*- coding=utf-8 -*-
from __future__ import absolute_import

import sys

__version__ = '0.3.0'

from . import shims


old_module = sys.modules["pip_shims"]


module = sys.modules["pip_shims"] = shims._new()
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
