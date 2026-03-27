# We need to import the patched packages directly from sys.path, so the
# identity checks can pass.
import pipenv  # noqa

import datetime
import sys

import pytest
import pytz
from pipenv.vendor import tomlkit


@pytest.mark.parametrize(
    "dt, content",
    [
        (  # Date.
            datetime.date(1992, 8, 19),
            "1992-08-19",
        ),
        (  # Naive time.
            datetime.time(15, 10),
            "15:10:00",
        ),
        (  # Aware time in UTC.
            datetime.time(15, 10, tzinfo=pytz.UTC),
            "15:10:00+00:00",
        ),
        (  # Aware local time.
            datetime.time(15, 10, tzinfo=pytz.FixedOffset(8 * 60)),
            "15:10:00+08:00",
        ),
        (  # Naive datetime.
            datetime.datetime(1992, 8, 19, 15, 10),
            "1992-08-19T15:10:00",
        ),
        (  # Aware datetime in UTC.
            datetime.datetime(1992, 8, 19, 15, 10, tzinfo=pytz.UTC),
            "1992-08-19T15:10:00Z",
        ),
        (  # Aware local datetime.
            datetime.datetime(1992, 8, 19, 15, 10, tzinfo=pytz.FixedOffset(8 * 60)),
            "1992-08-19T15:10:00+08:00",
        ),
    ],
)
def test_token_date(dt, content):
    item = tomlkit.item(dt)
    assert item.as_string() == content


# ---------------------------------------------------------------------------
# Regression test for https://github.com/pypa/pipenv/issues/5674
# ---------------------------------------------------------------------------

_LOCATIONS_PKG = "pipenv.patched.pip._internal.locations"
_DISTUTILS_KEY = f"{_LOCATIONS_PKG}._distutils"
_SENTINEL = object()


def test_locations_falls_back_to_sysconfig_when_distutils_unavailable():
    """When distutils cannot be imported, locations/__init__ falls back to sysconfig.

    This covers the real-world scenario where:
    - pipenv is installed under Python 3.12+ (which removed distutils), OR
    - the user's Python < 3.10 lacks the python3-distutils package (Debian/Ubuntu), OR
    - a mixed-version subprocess runs with one Python but imports pipenv from another.

    Regression: https://github.com/pypa/pipenv/issues/5674
    """
    import sysconfig

    # Snapshot the currently-loaded locations modules so we can restore them
    # after the test and avoid polluting the module cache for other tests.
    saved_modules = {k: v for k, v in sys.modules.items() if k.startswith(_LOCATIONS_PKG)}
    saved_pip_use_sysconfig = getattr(sysconfig, "_PIP_USE_SYSCONFIG", _SENTINEL)

    try:
        # Evict the locations package so all module-level initialization code
        # runs again from scratch on the next import.
        for key in list(saved_modules):
            del sys.modules[key]

        # Setting sys.modules[name] = None causes Python to raise ImportError
        # when anything attempts "from . import _distutils" – this simulates
        # distutils being absent from the interpreter.
        sys.modules[_DISTUTILS_KEY] = None

        # Force _USE_SYSCONFIG_DEFAULT to False (simulates Python < 3.10) via
        # the documented distributor override so we exercise the distutils path.
        sysconfig._PIP_USE_SYSCONFIG = False

        # The import must succeed without raising ModuleNotFoundError.
        import pipenv.patched.pip._internal.locations as loc  # noqa: F401

        # After the failed _distutils import our fix must have set _USE_SYSCONFIG
        # to True so that all subsequent scheme resolution uses sysconfig.
        assert loc._USE_SYSCONFIG is True, (
            f"Expected _USE_SYSCONFIG=True after distutils fallback, got {loc._USE_SYSCONFIG}"
        )

    finally:
        # Remove the sentinel block so it doesn't poison other imports.
        sys.modules.pop(_DISTUTILS_KEY, None)
        # Restore the original module cache.
        for key in list(sys.modules):
            if key.startswith(_LOCATIONS_PKG):
                del sys.modules[key]
        sys.modules.update(saved_modules)
        # Restore (or remove) the sysconfig override.
        if saved_pip_use_sysconfig is _SENTINEL:
            sysconfig.__dict__.pop("_PIP_USE_SYSCONFIG", None)
        else:
            sysconfig._PIP_USE_SYSCONFIG = saved_pip_use_sysconfig
