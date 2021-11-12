# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import os
import re

import pipenv.vendor.colorama as colorama
import pipenv.vendor.six as six

from .compat import to_native_string

DISABLE_COLORS = os.getenv("CI", False) or os.getenv(
    "ANSI_COLORS_DISABLED", os.getenv("VISTIR_DISABLE_COLORS", False)
)


ATTRIBUTE_NAMES = ["bold", "dark", "", "underline", "blink", "", "reverse", "concealed"]
ATTRIBUTES = dict(zip(ATTRIBUTE_NAMES, range(1, 9)))
del ATTRIBUTES[""]

colors = ["grey", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
COLORS = dict(zip(colors, range(30, 38)))
HIGHLIGHTS = dict(zip(["on_{0}".format(c) for c in colors], range(40, 48)))
ANSI_REMOVAL_RE = re.compile(r"\033\[((?:\d|;)*)([a-zA-Z])")


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
    return colorize(text, fg=color, bg=on_color, attrs=attrs)


def colorize(text, fg=None, bg=None, attrs=None):
    if os.getenv("ANSI_COLORS_DISABLED") is None:
        style = "NORMAL"
        if attrs is not None and not isinstance(attrs, list):
            _attrs = []
            if isinstance(attrs, six.string_types):
                _attrs.append(attrs)
            else:
                _attrs = list(attrs)
            attrs = _attrs
        if attrs and "bold" in attrs:
            style = "BRIGHT"
            attrs.remove("bold")
        if fg is not None:
            fg = fg.upper()
            text = to_native_string("%s%s%s%s%s") % (
                to_native_string(getattr(colorama.Fore, fg)),
                to_native_string(getattr(colorama.Style, style)),
                to_native_string(text),
                to_native_string(colorama.Fore.RESET),
                to_native_string(colorama.Style.NORMAL),
            )

        if bg is not None:
            bg = bg.upper()
            text = to_native_string("%s%s%s%s") % (
                to_native_string(getattr(colorama.Back, bg)),
                to_native_string(text),
                to_native_string(colorama.Back.RESET),
                to_native_string(colorama.Style.NORMAL),
            )

        if attrs is not None:
            fmt_str = to_native_string("%s[%%dm%%s%s[9m") % (chr(27), chr(27))
            for attr in attrs:
                text = fmt_str % (ATTRIBUTES[attr], text)

        text += RESET
    else:
        text = ANSI_REMOVAL_RE.sub("", text)
    return text


def cprint(text, color=None, on_color=None, attrs=None, **kwargs):
    """Print colorize text.

    It accepts arguments of print function.
    """

    print((colored(text, color, on_color, attrs)), **kwargs)
