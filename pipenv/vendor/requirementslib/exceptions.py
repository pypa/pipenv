# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import errno
import os
import six
import sys


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
        Exception.__init__(self)
        print("Missing parameter: %s" % param, file=sys.stderr, flush=True)


class FileCorruptException(OSError):
    def __init__(self, path, *args, **kwargs):
        path = path
        backup_path = kwargs.pop("backup_path", None)
        if not backup_path and args:
            args = reversed(args)
            backup_path = args.pop()
            if not isinstance(backup_path, six.string_types) or not os.path.exists(os.path.abspath(os.path.dirname(backup_path))):
                args.append(backup_path)
                backup_path = None
            if args:
                args = reversed(args)
        self.path = path
        self.backup_path = backup_path
        self.show(self.path, self.backup_path)
        OSError.__init__(self, path, *args, **kwargs)

    @classmethod
    def show(cls, path, backup_path=None):
        print("ERROR: Failed to load file at %s" % path, file=sys.stderr, flush=True)
        if backup_path:
            msg = "it will be backed up to %s and removed" % backup_path
        else:
            msg = "it will be removed and replaced."
        print("The file is corrupt, %s" % msg, file=sys.stderr, flush=True)


class LockfileCorruptException(FileCorruptException):

    @classmethod
    def show(cls, path, backup_path=None):
        print("ERROR: Failed to load lockfile at %s" % path, file=sys.stderr, flush=True)
        if backup_path:
            msg = "it will be backed up to %s and removed" % backup_path
        else:
            msg = "it will be removed and replaced on the next lock."
        print("Your lockfile is corrupt, %s" % msg, file=sys.stderr, flush=True)


class PipfileCorruptException(FileCorruptException):

    @classmethod
    def show(cls, path, backup_path=None):
        print("ERROR: Failed to load Pipfile at %s" % path, file=sys.stderr, flush=True)
        if backup_path:
            msg = "it will be backed up to %s and removed" % backup_path
        else:
            msg = "it will be removed and replaced on the next lock."
        print("Your Pipfile is corrupt, %s" % msg, file=sys.stderr, flush=True)


class PipfileNotFound(FileNotFoundError):
    def __init__(self, path, *args, **kwargs):
        self.errno = errno.ENOENT
        self.path = path
        self.show(path)
        super(PipfileNotFound, self).__init__(*args, **kwargs)

    @classmethod
    def show(cls, path):
        print("ERROR: The file could not be found: %s" % path, file=sys.stderr, flush=True)
        print("Aborting...", file=sys.stderr, flush=True)
