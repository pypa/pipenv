import errno
import os
import sys


class RequirementError(Exception):
    pass


class MissingParameter(Exception):
    def __init__(self, param):
        self.message = self.get_message(param)
        super().__init__(self.message)

    @classmethod
    def get_message(cls, param):
        return "Missing Parameter: %s" % param

    def show(self, param):
        print(self.message, file=sys.stderr, flush=True)


class FileCorruptException(OSError):
    def __init__(self, path, *args, **kwargs):
        backup_path = kwargs.pop("backup_path", None)
        if not backup_path and args:
            args = reversed(args)
            backup_path = args.pop()
            if not isinstance(backup_path, str) or not os.path.exists(
                os.path.abspath(os.path.dirname(backup_path))
            ):
                args.append(backup_path)
                backup_path = None
            if args:
                args = reversed(args)
        self.message = self.get_message(path, backup_path=backup_path)
        super().__init__(self.message)

    def get_message(self, path, backup_path=None):
        message = "ERROR: Failed to load file at %s" % path
        if backup_path:
            msg = "it will be backed up to %s and removed" % backup_path
        else:
            msg = "it will be removed and replaced on the next lock."
        message = f"{message}\nYour lockfile is corrupt, {msg}"
        return message

    def show(self):
        print(self.message, file=sys.stderr, flush=True)


class LockfileCorruptException(FileCorruptException):
    def __init__(self, path, backup_path=None):
        self.message = self.get_message(path, backup_path=backup_path)
        super().__init__(self.message)

    def get_message(self, path, backup_path=None):
        message = "ERROR: Failed to load lockfile at %s" % path
        if backup_path:
            msg = "it will be backed up to %s and removed" % backup_path
        else:
            msg = "it will be removed and replaced on the next lock."
        message = f"{message}\nYour lockfile is corrupt, {msg}"
        return message

    def show(self, path, backup_path=None):
        print(self.message, file=sys.stderr, flush=True)


class PipfileCorruptException(FileCorruptException):
    def __init__(self, path, backup_path=None):
        self.message = self.get_message(path, backup_path=backup_path)
        super().__init__(self.message)

    def get_message(self, path, backup_path=None):
        message = "ERROR: Failed to load Pipfile at %s" % path
        if backup_path:
            msg = "it will be backed up to %s and removed" % backup_path
        else:
            msg = "it will be removed and replaced on the next lock."
        message = f"{message}\nYour Pipfile is corrupt, {msg}"
        return message

    def show(self, path, backup_path=None):
        print(self.message, file=sys.stderr, flush=True)


class PipfileNotFound(FileNotFoundError):
    def __init__(self, path, *args, **kwargs):
        self.errno = errno.ENOENT
        self.filename = path
        super().__init__(self.filename)
