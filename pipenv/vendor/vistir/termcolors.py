# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals
import colorama
import os


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
            text = text = "%s%s%s%s%s" % (
                getattr(colorama.Fore, color),
                getattr(colorama.Style, style),
                text,
                colorama.Fore.RESET,
                colorama.Style.NORMAL,
            )

        if on_color is not None:
            on_color = on_color.upper()
            text = "%s%s%s%s" % (
                getattr(colorama.Back, on_color),
                text,
                colorama.Back.RESET,
                colorama.Style.NORMAL,
            )

        if attrs is not None:
            fmt_str = "%s[%%dm%%s%s[9m" % (
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
