import os


try:
    from test.support import import_helper  # type: ignore
except ImportError:
    # Python 3.9 and earlier
    class import_helper:  # type: ignore
        from test.support import modules_setup, modules_cleanup


try:
    # Python 3.10
    from test.support.os_helper import unlink
except ImportError:
    from test.support import unlink as _unlink

    def unlink(target):
        return _unlink(os.fspath(target))
