import os


class UndefinedValueError(Exception):
    pass


class Undefined(object):
    """Class to represent undefined type. """
    pass


# Reference instance to represent undefined values
undefined = Undefined()


def _cast_boolean(value):
    """
    Helper to convert config values to boolean as ConfigParser do.
    """
    _BOOLEANS = {'1': True, 'yes': True, 'true': True, 'on': True,
                 '0': False, 'no': False, 'false': False, 'off': False, '': False}
    value = str(value)
    if value.lower() not in _BOOLEANS:
        raise ValueError('Not a boolean: %s' % value)

    return _BOOLEANS[value.lower()]


def getenv(option, default=undefined, cast=undefined):
    """
    Return the value for option or default if defined.
    """

    # We can't avoid __contains__ because value may be empty.
    if option in os.environ:
        value = os.environ[option]
    else:
        if isinstance(default, Undefined):
            raise UndefinedValueError('{} not found. Declare it as envvar or define a default value.'.format(option))

        value = default

    if isinstance(cast, Undefined):
        return value

    if cast is bool:
        value = _cast_boolean(value)
    elif cast is list:
        value = [x for x in value.split(',') if x]
    else:
        value = cast(value)

    return value
