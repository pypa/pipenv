from typing import Optional


class TOMLKitError(Exception):

    pass


class ParseError(ValueError, TOMLKitError):
    """
    This error occurs when the parser encounters a syntax error
    in the TOML being parsed. The error references the line and
    location within the line where the error was encountered.
    """

    def __init__(
        self, line, col, message=None
    ):  # type: (int, int, Optional[str]) -> None
        self._line = line
        self._col = col

        if message is None:
            message = "TOML parse error"

        super(ParseError, self).__init__(
            "{} at line {} col {}".format(message, self._line, self._col)
        )

    @property
    def line(self):
        return self._line

    @property
    def col(self):
        return self._col


class MixedArrayTypesError(ParseError):
    """
    An array was found that had two or more element types.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Mixed types found in array"

        super(MixedArrayTypesError, self).__init__(line, col, message=message)


class InvalidNumberError(ParseError):
    """
    A numeric field was improperly specified.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Invalid number"

        super(InvalidNumberError, self).__init__(line, col, message=message)


class InvalidDateTimeError(ParseError):
    """
    A datetime field was improperly specified.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Invalid datetime"

        super(InvalidDateTimeError, self).__init__(line, col, message=message)


class InvalidDateError(ParseError):
    """
    A date field was improperly specified.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Invalid date"

        super(InvalidDateError, self).__init__(line, col, message=message)


class InvalidTimeError(ParseError):
    """
    A date field was improperly specified.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Invalid time"

        super(InvalidTimeError, self).__init__(line, col, message=message)


class InvalidNumberOrDateError(ParseError):
    """
    A numeric or date field was improperly specified.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Invalid number or date format"

        super(InvalidNumberOrDateError, self).__init__(line, col, message=message)


class InvalidUnicodeValueError(ParseError):
    """
    A unicode code was improperly specified.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Invalid unicode value"

        super(InvalidUnicodeValueError, self).__init__(line, col, message=message)


class UnexpectedCharError(ParseError):
    """
    An unexpected character was found during parsing.
    """

    def __init__(self, line, col, char):  # type: (int, int, str) -> None
        message = "Unexpected character: {}".format(repr(char))

        super(UnexpectedCharError, self).__init__(line, col, message=message)


class EmptyKeyError(ParseError):
    """
    An empty key was found during parsing.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Empty key"

        super(EmptyKeyError, self).__init__(line, col, message=message)


class EmptyTableNameError(ParseError):
    """
    An empty table name was found during parsing.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Empty table name"

        super(EmptyTableNameError, self).__init__(line, col, message=message)


class InvalidCharInStringError(ParseError):
    """
    The string being parsed contains an invalid character.
    """

    def __init__(self, line, col, char):  # type: (int, int, str) -> None
        message = "Invalid character {} in string".format(repr(char))

        super(InvalidCharInStringError, self).__init__(line, col, message=message)


class UnexpectedEofError(ParseError):
    """
    The TOML being parsed ended before the end of a statement.
    """

    def __init__(self, line, col):  # type: (int, int) -> None
        message = "Unexpected end of file"

        super(UnexpectedEofError, self).__init__(line, col, message=message)


class InternalParserError(ParseError):
    """
    An error that indicates a bug in the parser.
    """

    def __init__(
        self, line, col, message=None
    ):  # type: (int, int, Optional[str]) -> None
        msg = "Internal parser error"
        if message:
            msg += " ({})".format(message)

        super(InternalParserError, self).__init__(line, col, message=msg)


class NonExistentKey(KeyError, TOMLKitError):
    """
    A non-existent key was used.
    """

    def __init__(self, key):
        message = 'Key "{}" does not exist.'.format(key)

        super(NonExistentKey, self).__init__(message)


class KeyAlreadyPresent(TOMLKitError):
    """
    An already present key was used.
    """

    def __init__(self, key):
        message = 'Key "{}" already exists.'.format(key)

        super(KeyAlreadyPresent, self).__init__(message)


class InvalidControlChar(ParseError):
    def __init__(self, line, col, char, type):  # type: (int, int, int, str) -> None
        display_code = "\\u00"

        if char < 16:
            display_code += "0"

        display_code += str(char)

        message = (
            "Control characters (codes less than 0x1f and 0x7f) are not allowed in {}, "
            "use {} instead".format(type, display_code)
        )

        super(InvalidControlChar, self).__init__(line, col, message=message)
