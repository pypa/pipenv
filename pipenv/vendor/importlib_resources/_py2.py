import os
import errno

from . import _common
from ._compat import FileNotFoundError
from io import BytesIO, TextIOWrapper, open as io_open


def open_binary(package, resource):
    """Return a file-like object opened for binary reading of the resource."""
    resource = _common.normalize_path(resource)
    package = _common.get_package(package)
    # Using pathlib doesn't work well here due to the lack of 'strict' argument
    # for pathlib.Path.resolve() prior to Python 3.6.
    package_path = os.path.dirname(package.__file__)
    relative_path = os.path.join(package_path, resource)
    full_path = os.path.abspath(relative_path)
    try:
        return io_open(full_path, 'rb')
    except IOError:
        # This might be a package in a zip file.  zipimport provides a loader
        # with a functioning get_data() method, however we have to strip the
        # archive (i.e. the .zip file's name) off the front of the path.  This
        # is because the zipimport loader in Python 2 doesn't actually follow
        # PEP 302.  It should allow the full path, but actually requires that
        # the path be relative to the zip file.
        try:
            loader = package.__loader__
            full_path = relative_path[len(loader.archive)+1:]
            data = loader.get_data(full_path)
        except (IOError, AttributeError):
            package_name = package.__name__
            message = '{!r} resource not found in {!r}'.format(
                resource, package_name)
            raise FileNotFoundError(message)
        return BytesIO(data)


def open_text(package, resource, encoding='utf-8', errors='strict'):
    """Return a file-like object opened for text reading of the resource."""
    return TextIOWrapper(
        open_binary(package, resource), encoding=encoding, errors=errors)


def read_binary(package, resource):
    """Return the binary contents of the resource."""
    with open_binary(package, resource) as fp:
        return fp.read()


def read_text(package, resource, encoding='utf-8', errors='strict'):
    """Return the decoded string of the resource.

    The decoding-related arguments have the same semantics as those of
    bytes.decode().
    """
    with open_text(package, resource, encoding, errors) as fp:
        return fp.read()


def path(package, resource):
    """A context manager providing a file path object to the resource.

    If the resource does not already exist on its own on the file system,
    a temporary file will be created. If the file was created, the file
    will be deleted upon exiting the context manager (no exception is
    raised if the file was deleted prior to the context manager
    exiting).
    """
    path = _common.files(package).joinpath(_common.normalize_path(resource))
    if not path.is_file():
        raise FileNotFoundError(path)
    return _common.as_file(path)


def is_resource(package, name):
    """True if name is a resource inside package.

    Directories are *not* resources.
    """
    package = _common.get_package(package)
    _common.normalize_path(name)
    try:
        package_contents = set(contents(package))
    except OSError as error:
        if error.errno not in (errno.ENOENT, errno.ENOTDIR):
            # We won't hit this in the Python 2 tests, so it'll appear
            # uncovered.  We could mock os.listdir() to return a non-ENOENT or
            # ENOTDIR, but then we'd have to depend on another external
            # library since Python 2 doesn't have unittest.mock.  It's not
            # worth it.
            raise                     # pragma: nocover
        return False
    if name not in package_contents:
        return False
    return (_common.from_package(package) / name).is_file()


def contents(package):
    """Return an iterable of entries in `package`.

    Note that not all entries are resources.  Specifically, directories are
    not considered resources.  Use `is_resource()` on each entry returned here
    to check if it is a resource or not.
    """
    package = _common.get_package(package)
    return list(item.name for item in _common.from_package(package).iterdir())
