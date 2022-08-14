import os
import platform
import sys
import tempfile
from collections import OrderedDict

MEM_BASED_FS = ["tmpfs", "ramfs"]
SUITABLE_PATHS = ["/tmp", "/run/user/{uid}", "/run/shm", "/dev/shm"]


class MemoryTempfile:
    def __init__(self, preferred_paths: list = None):
        self.os_tempdir = tempfile.gettempdir()
        self.tempdir = self.os_tempdir

        if platform.system() == "Linux":
            self._set_tempdir_for_linux(preferred_paths)

    def _set_tempdir_for_linux(self, preferred_paths):
        filesystem_types = MEM_BASED_FS
        self.filesystem_types = (
            list(filesystem_types) if filesystem_types is not None else MEM_BASED_FS
        )

        preferred_paths = [] if preferred_paths is None else preferred_paths
        suitable_paths = [self.os_tempdir] + SUITABLE_PATHS

        self.suitable_paths = preferred_paths + suitable_paths

        uid = os.geteuid()

        with open("/proc/self/mountinfo", "r") as file:
            mnt_info = {i[2]: i for i in [line.split() for line in file]}

        self.usable_paths = OrderedDict()
        for path in self.suitable_paths:
            path = path.replace("{uid}", str(uid))

            # We may have repeated
            if self.usable_paths.get(path) is not None:
                continue
            self.usable_paths[path] = False
            try:
                dev = os.stat(path).st_dev
                major, minor = os.major(dev), os.minor(dev)
                mp = mnt_info.get("{}:{}".format(major, minor))
                if mp and mp[mp.index("-", 6) + 1] in self.filesystem_types:
                    self.usable_paths[path] = mp
            except FileNotFoundError:
                pass

        for key in [k for k, v in self.usable_paths.items() if not v]:
            del self.usable_paths[key]

        if len(self.usable_paths) > 0:
            self.tempdir = next(iter(self.usable_paths.keys()))

    def found_mem_tempdir(self):
        return len(self.usable_paths) > 0

    def using_mem_tempdir(self):
        return self.tempdir in self.usable_paths

    def get_usable_mem_tempdir_paths(self):
        return list(self.usable_paths.keys())

    def gettempdir(self):
        return self.tempdir

    def gettempdirb(self):
        return self.tempdir.encode(sys.getfilesystemencoding(), "surrogateescape")

    def mkdtemp(self, suffix=None, prefix=None, dir=None):
        return tempfile.mkdtemp(
            suffix=suffix, prefix=prefix, dir=self.tempdir if not dir else dir
        )

    def mkstemp(self, suffix=None, prefix=None, dir=None, text=False):
        return tempfile.mkstemp(
            suffix=suffix, prefix=prefix, dir=self.tempdir if not dir else dir, text=text
        )

    def TemporaryDirectory(self, suffix=None, prefix=None, dir=None):
        return tempfile.TemporaryDirectory(
            suffix=suffix, prefix=prefix, dir=self.tempdir if not dir else dir
        )

    def SpooledTemporaryFile(
        self,
        max_size=0,
        mode="w+b",
        buffering=-1,
        encoding=None,
        newline=None,
        suffix=None,
        prefix=None,
        dir=None,
    ):
        return tempfile.SpooledTemporaryFile(
            max_size=max_size,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            newline=newline,
            suffix=suffix,
            prefix=prefix,
            dir=self.tempdir if not dir else dir,
        )

    def NamedTemporaryFile(
        self,
        mode="w+b",
        buffering=-1,
        encoding=None,
        newline=None,
        suffix=None,
        prefix=None,
        dir=None,
        delete=True,
    ):
        return tempfile.NamedTemporaryFile(
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            newline=newline,
            suffix=suffix,
            prefix=prefix,
            dir=self.tempdir if not dir else dir,
            delete=delete,
        )

    def TemporaryFile(
        self,
        mode="w+b",
        buffering=-1,
        encoding=None,
        newline=None,
        suffix=None,
        prefix=None,
        dir=None,
    ):
        return tempfile.TemporaryFile(
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            newline=newline,
            suffix=suffix,
            prefix=prefix,
            dir=self.tempdir if not dir else dir,
        )

    def gettempprefix(self):
        return tempfile.gettempdir()

    def gettempprefixb(self):
        return tempfile.gettempprefixb()
