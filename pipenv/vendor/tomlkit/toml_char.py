import string

from ._compat import unicode


class TOMLChar(unicode):
    def __init__(self, c):
        super(TOMLChar, self).__init__()

        if len(self) > 1:
            raise ValueError("A TOML character must be of length 1")

    def is_bare_key_char(self):  # type: () -> bool
        """
        Whether the character is a valid bare key name or not.
        """
        return self in string.ascii_letters + string.digits + "-" + "_"

    def is_kv_sep(self):  # type: () -> bool
        """
        Whether the character is a valid key/value separator ot not.
        """
        return self in "= \t"

    def is_int_float_char(self):  # type: () -> bool
        """
        Whether the character if a valid integer or float value character or not.
        """
        return self in string.digits + "+" + "-" + "_" + "." + "e"

    def is_ws(self):  # type: () -> bool
        """
        Whether the character is a whitespace character or not.
        """
        return self in " \t\r\n"

    def is_nl(self):  # type: () -> bool
        """
        Whether the character is a new line character or not.
        """
        return self in "\n\r"

    def is_spaces(self):  # type: () -> bool
        """
        Whether the character is a space or not
        """
        return self in " \t"
