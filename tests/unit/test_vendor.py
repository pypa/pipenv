# We need to import the patched packages directly from sys.path, so the
# identity checks can pass.
import pipenv  # noqa

import datetime


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
