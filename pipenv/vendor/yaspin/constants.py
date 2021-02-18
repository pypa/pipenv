# -*- coding: utf-8 -*-
#
# :copyright: (c) 2020 by Pavlo Dmytrenko.
# :license: MIT, see LICENSE for more details.

"""
yaspin.constants
~~~~~~~~~~~~~~~~

Some setups.
"""


ENCODING = "utf-8"
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

# Get spinner names:
# $ < yaspin/data/spinners.json | jq '. | keys'
SPINNER_ATTRS = [
    "aesthetic",
    "arc",
    "arrow",
    "arrow2",
    "arrow3",
    "balloon",
    "balloon2",
    "betaWave",
    "bounce",
    "bouncingBall",
    "bouncingBar",
    "boxBounce",
    "boxBounce2",
    "christmas",
    "circle",
    "circleHalves",
    "circleQuarters",
    "clock",
    "dots",
    "dots10",
    "dots11",
    "dots12",
    "dots2",
    "dots3",
    "dots4",
    "dots5",
    "dots6",
    "dots7",
    "dots8",
    "dots8Bit",
    "dots9",
    "dqpb",
    "earth",
    "flip",
    "grenade",
    "growHorizontal",
    "growVertical",
    "hamburger",
    "hearts",
    "layer",
    "line",
    "line2",
    "material",
    "monkey",
    "moon",
    "noise",
    "pipe",
    "point",
    "pong",
    "runner",
    "shark",
    "simpleDots",
    "simpleDotsScrolling",
    "smiley",
    "squareCorners",
    "squish",
    "star",
    "star2",
    "toggle",
    "toggle10",
    "toggle11",
    "toggle12",
    "toggle13",
    "toggle2",
    "toggle3",
    "toggle4",
    "toggle5",
    "toggle6",
    "toggle7",
    "toggle8",
    "toggle9",
    "triangle",
    "weather",
]
