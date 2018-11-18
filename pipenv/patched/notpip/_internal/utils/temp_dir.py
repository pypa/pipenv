from __future__ import absolute_import

import logging
import os.path
import tempfile
import warnings

from pipenv.patched.notpip._internal.utils.misc import rmtree
from pipenv.vendor.vistir.compat import finalize, ResourceWarning

logger = logging.getLogger(__name__)


class TempDirectory(object):
    """Helper class that owns and cleans up a temporary directory.

    This class can be used as a context manager or as an OO representation of a
    temporary directory.

    Attributes:
        path
            Location to the created temporary directory or None
        delete
            Whether the directory should be deleted when exiting
            (when used as a contextmanager)

    Methods:
        create()
            Creates a temporary directory and stores its path in the path
            attribute.
        cleanup()
            Deletes the temporary directory and sets path attribute to None

    When used as a context manager, a temporary directory is created on
    entering the context and, if the delete attribute is True, on exiting the
    context the created directory is deleted.
    """

    def __init__(self, path=None, delete=None, kind="temp"):
        super(TempDirectory, self).__init__()

        if path is None and delete is None:
            # If we were not given an explicit directory, and we were not given
            # an explicit delete option, then we'll default to deleting.
            delete = True

        self.path = path
        self.delete = delete
        self.kind = kind
        self._finalizer = None
        if path:
            self._register_finalizer()

    def _register_finalizer(self):
        if self.delete and self.path:
            self._finalizer = finalize(
                self,
                self._cleanup,
                self.path,
                warn_message=None
            )
        else:
            self._finalizer = None

    def __repr__(self):
        return "<{} {!r}>".format(self.__class__.__name__, self.path)

    def __enter__(self):
        self.create()
        return self

    def __exit__(self, exc, value, tb):
        if self.delete:
            self.cleanup()

    def create(self):
        """Create a temporary directory and store it's path in self.path
        """
        if self.path is not None:
            logger.debug(
                "Skipped creation of temporary directory: {}".format(self.path)
            )
            return
        # We realpath here because some systems have their default tmpdir
        # symlinked to another directory.  This tends to confuse build
        # scripts, so we canonicalize the path by traversing potential
        # symlinks here.
        self.path = os.path.realpath(
            tempfile.mkdtemp(prefix="pip-{}-".format(self.kind))
        )
        self._register_finalizer()
        logger.debug("Created temporary directory: {}".format(self.path))

    @classmethod
    def _cleanup(cls, name, warn_message=None):
        try:
            rmtree(name)
        except OSError:
            pass
        else:
            if warn_message:
                warnings.warn(warn_message, ResourceWarning)

    def cleanup(self):
        """Remove the temporary directory created and reset state
        """
        if getattr(self._finalizer, "detach", None) and self._finalizer.detach():
            if os.path.exists(self.path):
                try:
                    rmtree(self.path)
                except OSError:
                    pass
                else:
                    self.path = None
