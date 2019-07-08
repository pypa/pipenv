# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import errno
import os
import sys

import six
from vistir.compat import FileNotFoundError

if six.PY2:

    class FileExistsError(OSError):
        def __init__(self, *args, **kwargs):
            self.errno = errno.EEXIST
            super(FileExistsError, self).__init__(*args, **kwargs)


else:
    from six.moves.builtins import FileExistsError


class RequirementError(Exception):
    pass


class MissingParameter(Exception):
    def __init__(self, param):
        self.message = self.get_message(param)
        super(MissingParameter, self).__init__(self.message)

    @classmethod
    def get_message(cls, param):
        return "Missing Parameter: %s" % param

    def show(self, param):
        print(self.message, file=sys.stderr, flush=True)


class FileCorruptException(OSError):
    def __init__(self, path, *args, **kwargs):
        path = path
        backup_path = kwargs.pop("backup_path", None)
        if not backup_path and args:
            args = reversed(args)
            backup_path = args.pop()
            if not isinstance(backup_path, six.string_types) or not os.path.exists(
                os.path.abspath(os.path.dirname(backup_path))
            ):
                args.append(backup_path)
                backup_path = None
            if args:
                args = reversed(args)
        self.message = self.get_message(path, backup_path=backup_path)
        super(FileCorruptException, self).__init__(self.message)

    def get_message(self, path, backup_path=None):
        message = "ERROR: Failed to load file at %s" % path
        if backup_path:
            msg = "it will be backed up to %s and removed" % backup_path
        else:
            msg = "it will be removed and replaced on the next lock."
        message = "{0}\nYour lockfile is corrupt, {1}".format(message, msg)
        return message

    def show(self):
        print(self.message, file=sys.stderr, flush=True)


class LockfileCorruptException(FileCorruptException):
    def __init__(self, path, backup_path=None):
        self.message = self.get_message(path, backup_path=backup_path)
        super(LockfileCorruptException, self).__init__(self.message)

    def get_message(self, path, backup_path=None):
        message = "ERROR: Failed to load lockfile at %s" % path
        if backup_path:
            msg = "it will be backed up to %s and removed" % backup_path
        else:
            msg = "it will be removed and replaced on the next lock."
        message = "{0}\nYour lockfile is corrupt, {1}".format(message, msg)
        return message

    def show(self, path, backup_path=None):
        print(self.message, file=sys.stderr, flush=True)


class PipfileCorruptException(FileCorruptException):
    def __init__(self, path, backup_path=None):
        self.message = self.get_message(path, backup_path=backup_path)
        super(PipfileCorruptException, self).__init__(self.message)

    def get_message(self, path, backup_path=None):
        message = "ERROR: Failed to load Pipfile at %s" % path
        if backup_path:
            msg = "it will be backed up to %s and removed" % backup_path
        else:
            msg = "it will be removed and replaced on the next lock."
        message = "{0}\nYour Pipfile is corrupt, {1}".format(message, msg)
        return message

    def show(self, path, backup_path=None):
        print(self.message, file=sys.stderr, flush=True)


class PipfileNotFound(FileNotFoundError):
    def __init__(self, path, *args, **kwargs):
        self.errno = errno.ENOENT
        self.filename = path
        super(PipfileNotFound, self).__init__(self.filename)
