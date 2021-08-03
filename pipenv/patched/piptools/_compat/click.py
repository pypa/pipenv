import click

CLICK_MAJOR_VERSION = int(
    # extract major version of click
    click.__version__.split(".")[0]
)
IS_CLICK_VER_8_PLUS = CLICK_MAJOR_VERSION > 7
