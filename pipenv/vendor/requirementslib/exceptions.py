# -*- coding: utf-8 -*-
from __future__ import absolute_import
import errno
import six


if six.PY2:
    class FileExistsError(OSError):
        def __init__(self, *args, **kwargs):
            self.errno = errno.EEXIST
            super(FileExistsError, self).__init__(*args, **kwargs)
else:
    from six.moves.builtins import FileExistsError


class RequirementError(Exception):
    pass
