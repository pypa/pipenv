# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals
import colorama
import os
from .compat import to_native_string


ATTRIBUTES = dict(
        list(zip([
            'bold',
            'dark',
            '',
            'underline',
            'blink',
            '',
            'reverse',
            'concealed'
            ],
            list(range(1, 9))
            ))
        )
del ATTRIBUTES['']


HIGHLIGHTS = dict(
        list(zip([
            'on_grey',
            'on_red',
            'on_green',
            'on_yellow',
            'on_blue',
            'on_magenta',
            'on_cyan',
            'on_white'
            ],
            list(range(40, 48))
            ))
        )


COLORS = dict(
        list(zip([
            'grey',
            'red',
            'green',
            'yellow',
            'blue',
            'magenta',
            'cyan',
            'white',
            ],
            list(range(30, 38))
            ))
        )


COLOR_MAP = {
    # name: type
    "blink": "attrs",
    "bold": "attrs",
    "concealed": "attrs",
    "dark": "attrs",
    "reverse": "attrs",
    "underline": "attrs",
    "blue": "color",
    "cyan": "color",
    "green": "color",
    "magenta": "color",
    "red": "color",
    "white": "color",
    "yellow": "color",
    "on_blue": "on_color",
    "on_cyan": "on_color",
    "on_green": "on_color",
    "on_grey": "on_color",
    "on_magenta": "on_color",
    "on_red": "on_color",
    "on_white": "on_color",
    "on_yellow": "on_color",
}
COLOR_ATTRS = COLOR_MAP.keys()


RESET = colorama.Style.RESET_ALL


def colored(text, color=None, on_color=None, attrs=None):
    """Colorize text using a reimplementation of the colorizer from
    https://github.com/pavdmyt/yaspin so that it works on windows.

    Available text colors:
        red, green, yellow, blue, magenta, cyan, white.

    Available text highlights:
        on_red, on_green, on_yellow, on_blue, on_magenta, on_cyan, on_white.

    Available attributes:
        bold, dark, underline, blink, reverse, concealed.

    Example:
        colored('Hello, World!', 'red', 'on_grey', ['blue', 'blink'])
        colored('Hello, World!', 'green')
    """
    if os.getenv('ANSI_COLORS_DISABLED') is None:
        style = "NORMAL"
        if 'bold' in attrs:
            style = "BRIGHT"
            attrs.remove('bold')
        if color is not None:
            color = color.upper()
            text = to_native_string("%s%s%s%s%s") % (
                to_native_string(getattr(colorama.Fore, color)),
                to_native_string(getattr(colorama.Style, style)),
                to_native_string(text),
                to_native_string(colorama.Fore.RESET),
                to_native_string(colorama.Style.NORMAL),
            )

        if on_color is not None:
            on_color = on_color.upper()
            text = to_native_string("%s%s%s%s") % (
                to_native_string(getattr(colorama.Back, on_color)),
                to_native_string(text),
                to_native_string(colorama.Back.RESET),
                to_native_string(colorama.Style.NORMAL),
            )

        if attrs is not None:
            fmt_str = to_native_string("%s[%%dm%%s%s[9m") % (
                chr(27),
                chr(27)
            )
            for attr in attrs:
                text = fmt_str % (ATTRIBUTES[attr], text)

        text += RESET
    return text


def cprint(text, color=None, on_color=None, attrs=None, **kwargs):
    """Print colorize text.

    It accepts arguments of print function.
    """

    print((colored(text, color, on_color, attrs)), **kwargs)
