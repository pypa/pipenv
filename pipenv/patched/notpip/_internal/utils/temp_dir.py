# The following comment should be removed at some point in the future.
# mypy: disallow-untyped-defs=False

from __future__ import absolute_import

import errno
import itertools
import logging
import os.path
import tempfile
import warnings

from pipenv.patched.notpip._internal.utils.misc import rmtree
from pipenv.patched.notpip._internal.utils.typing import MYPY_CHECK_RUNNING
from pipenv.vendor.vistir.compat import finalize, ResourceWarning

if MYPY_CHECK_RUNNING:
    from typing import Optional


logger = logging.getLogger(__name__)


class TempDirectory(object):
    """Helper class that owns and cleans up a temporary directory.

    This class can be used as a context manager or as an OO representation of a
    temporary directory.

    Attributes:
        path
            Location to the created temporary directory
        delete
            Whether the directory should be deleted when exiting
            (when used as a contextmanager)

    Methods:
        cleanup()
            Deletes the temporary directory

    When used as a context manager, if the delete attribute is True, on
    exiting the context the temporary directory is deleted.
    """

    def __init__(
        self,
        path=None,    # type: Optional[str]
        delete=None,  # type: Optional[bool]
        kind="temp"
    ):
        super(TempDirectory, self).__init__()

        if path is None and delete is None:
            # If we were not given an explicit directory, and we were not given
            # an explicit delete option, then we'll default to deleting.
            delete = True

        if path is None:
            path = self._create(kind)

        self._path = path
        self._deleted = False
        self.delete = delete
        self.kind = kind
        self._finalizer = None
        if self._path:
            self._register_finalizer()

    def _register_finalizer(self):
        if self.delete and self._path:
            self._finalizer = finalize(
                self,
                self._cleanup,
                self._path,
                warn_message = None
            )
        else:
            self._finalizer = None

    @property
    def path(self):
        # type: () -> str
        assert not self._deleted, (
            "Attempted to access deleted path: {}".format(self._path)
        )
        return self._path

    def __repr__(self):
        return "<{} {!r}>".format(self.__class__.__name__, self.path)

    def __enter__(self):
        return self

    def __exit__(self, exc, value, tb):
        if self.delete:
            self.cleanup()

    def _create(self, kind):
        """Create a temporary directory and store its path in self.path
        """
        # We realpath here because some systems have their default tmpdir
        # symlinked to another directory.  This tends to confuse build
        # scripts, so we canonicalize the path by traversing potential
        # symlinks here.
        path = os.path.realpath(
            tempfile.mkdtemp(prefix="pip-{}-".format(kind))
        )
        logger.debug("Created temporary directory: {}".format(path))
        return path

    @classmethod
    def _cleanup(cls, name, warn_message=None):
        if not os.path.exists(name):
            return
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
            if os.path.exists(self._path):
                self._deleted = True
                try:
                    rmtree(self._path)
                except OSError:
                    pass


class AdjacentTempDirectory(TempDirectory):
    """Helper class that creates a temporary directory adjacent to a real one.

    Attributes:
        original
            The original directory to create a temp directory for.
        path
            After calling create() or entering, contains the full
            path to the temporary directory.
        delete
            Whether the directory should be deleted when exiting
            (when used as a contextmanager)

    """
    # The characters that may be used to name the temp directory
    # We always prepend a ~ and then rotate through these until
    # a usable name is found.
    # pkg_resources raises a different error for .dist-info folder
    # with leading '-' and invalid metadata
    LEADING_CHARS = "-~.=%0123456789"

    def __init__(self, original, delete=None):
        self.original = original.rstrip('/\\')
        super(AdjacentTempDirectory, self).__init__(delete=delete)

    @classmethod
    def _generate_names(cls, name):
        """Generates a series of temporary names.

        The algorithm replaces the leading characters in the name
        with ones that are valid filesystem characters, but are not
        valid package names (for both Python and pip definitions of
        package).
        """
        for i in range(1, len(name)):
            for candidate in itertools.combinations_with_replacement(
                    cls.LEADING_CHARS, i - 1):
                new_name = '~' + ''.join(candidate) + name[i:]
                if new_name != name:
                    yield new_name

        # If we make it this far, we will have to make a longer name
        for i in range(len(cls.LEADING_CHARS)):
            for candidate in itertools.combinations_with_replacement(
                    cls.LEADING_CHARS, i):
                new_name = '~' + ''.join(candidate) + name
                if new_name != name:
                    yield new_name

    def _create(self, kind):
        root, name = os.path.split(self.original)
        for candidate in self._generate_names(name):
            path = os.path.join(root, candidate)
            try:
                os.mkdir(path)
            except OSError as ex:
                # Continue if the name exists already
                if ex.errno != errno.EEXIST:
                    raise
            else:
                path = os.path.realpath(path)
                break
        else:
            # Final fallback on the default behavior.
            path = os.path.realpath(
                tempfile.mkdtemp(prefix="pip-{}-".format(kind))
            )

        logger.debug("Created temporary directory: {}".format(path))
        return path