import errno
import sys
from pathlib import Path


class RequirementError(Exception):
    pass


class MissingParameter(Exception):
    def __init__(self, param):
        self.message = self.get_message(param)
        super().__init__(self.message)

    @classmethod
    def get_message(cls, param):
        return f"Missing Parameter: {param}"

    def show(self, param):
        print(self.message, file=sys.stderr, flush=True)


class FileCorruptException(OSError):
    def __init__(self, path, *args, **kwargs):
        backup_path = kwargs.pop("backup_path", None)
        if not backup_path and args:
            args = list(reversed(args))
            backup_path = args.pop()

            # Check if backup_path is a valid path with an existing parent directory
            if (
                not isinstance(backup_path, (str, Path))
                or not Path(backup_path).parent.exists()
            ):
                args.append(backup_path)
                backup_path = None

            if args:
                args = list(reversed(args))

        self.message = self.get_message(path, backup_path=backup_path)
        super().__init__(self.message)

    def get_message(self, path, backup_path=None):
        message = f"ERROR: Failed to load file at {path}"
        if backup_path:
            msg = f"it will be backed up to {backup_path} and removed"
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
        message = f"ERROR: Failed to load lockfile at {path}"
        if backup_path:
            msg = f"it will be backed up to {backup_path} and removed"
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
        message = f"ERROR: Failed to load Pipfile at {path}"
        if backup_path:
            msg = f"it will be backed up to {backup_path} and removed"
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
