from .parser import parse   # noqa

_MAJOR = 0
_MINOR = 1
_PATCH = 0


def version_tuple():
    '''
    Returns a 3-tuple of ints that represent the version
    '''
    return (_MAJOR, _MINOR, _PATCH)


def version():
    '''
    Returns a string representation of the version
    '''
    return '%d.%d.%d' % (version_tuple())


__version__ = version()
