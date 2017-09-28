# coding: utf-8
# flake8: noqa
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import six

if six.PY2:
    from .tempfile import TemporaryDirectory
    from .contextlib import ExitStack
else:
    from tempfile import TemporaryDirectory
    from contextlib import ExitStack
