# -*- coding: utf-8 -*-

# (The MIT License)
#
# Copyright (c) 2014 Kura
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the 'Software'), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
yarg(1) -- A semi hard Cornish cheese, also queries PyPI
========================================================

Yarg is a PyPI client.

    >>> import yarg
    >>>
    >>> package = yarg.get("yarg")
    >>> package.name
    u'yarg'
    >>> package.author
    Author(name=u'Kura', email=u'kura@kura.io')
    >>>
    >>> yarg.newest_packages()
    [<Package yarg>, <Package gray>, <Package ragy>]
    >>>
    >>> yarg.latest_updated_packages()
    [<Package yarg>, <Package gray>, <Package ragy>]

Full documentation is at <https://yarg.readthedocs.org>.
"""


from .client import get
from .exceptions import HTTPError
from .package import json2package
from .parse import (newest_packages, latest_updated_packages)


__all__ = ['get', 'HTTPError', 'json2package', 'newest_packages',
           'latest_updated_packages', ]
