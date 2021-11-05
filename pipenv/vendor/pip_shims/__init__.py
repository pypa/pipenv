# -*- coding=utf-8 -*-
"""
This library is a set of compatibilty access shims to the ``pip`` internal API.
It provides compatibility with pip versions 8.0 through the current release. The
shims are provided using a lazy import strategy by hacking a module by overloading
a class instance's ``getattr`` method. This library exists due to my constant
writing of the same set of import shims.

Submodules
==========

.. autosummary::
    :toctree: _autosummary

    pip_shims.models
    pip_shims.compat
    pip_shims.utils
    pip_shims.shims
    pip_shims.environment

"""
from __future__ import absolute_import

import sys

from . import shims

__version__ = "0.6.0"


if "pip_shims" in sys.modules:
    # mainly to keep a reference to the old module on hand so it doesn't get
    # weakref'd away
    if __name__ != "pip_shims":
        del sys.modules["pip_shims"]


if __name__ in sys.modules:
    old_module = sys.modules[__name__]


module = sys.modules["pip_shims"] = sys.modules[__name__] = shims._new()
module.shims = shims
module.__dict__.update(
    {
        "__file__": __file__,
        "__package__": "pip_shims",
        "__path__": __path__,
        "__doc__": __doc__,
        "__all__": module.__all__ + ["shims"],
        "__version__": __version__,
        "__name__": __name__,
    }
)
