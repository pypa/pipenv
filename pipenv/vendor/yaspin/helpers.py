# :copyright: (c) 2021 by Pavlo Dmytrenko.
# :license: MIT, see LICENSE for more details.

"""
yaspin.helpers
~~~~~~~~~~~~~~

Helper functions.
"""

from .constants import ENCODING


def to_unicode(text_type, encoding=ENCODING):
    if isinstance(text_type, bytes):
        return text_type.decode(encoding)
    return text_type
