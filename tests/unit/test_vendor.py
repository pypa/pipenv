# -*- coding: utf-8 -*-
# We need to import the patched packages directly from sys.path, so the
# identity checks can pass.
import pipenv  # noqa

import datetime
import os

import pytest
import pytz
import tomlkit

from pipfile.api import PipfileParser


class TestPipfileParser:

    def test_inject_environment_variables(self):
        os.environ['PYTEST_PIPFILE_TEST'] = "XYZ"
        p = PipfileParser()

        parsed_dict = p.inject_environment_variables({
            "a_string": "https://$PYTEST_PIPFILE_TEST@something.com",
            "another_string": "https://${PYTEST_PIPFILE_TEST}@something.com",
            "nested": {
                "a_string": "https://$PYTEST_PIPFILE_TEST@something.com",
                "another_string": "${PYTEST_PIPFILE_TEST}",
            },
            "list": [
                {
                    "a_string": "https://$PYTEST_PIPFILE_TEST@something.com",
                    "another_string": "${PYTEST_PIPFILE_TEST}"
                },
                {},
            ],
            "bool": True,
            "none": None,
        })

        assert parsed_dict["a_string"] == "https://XYZ@something.com"
        assert parsed_dict["another_string"] == "https://XYZ@something.com"
        assert parsed_dict["nested"]["another_string"] == "XYZ"
        assert parsed_dict["list"][0]["a_string"] == "https://XYZ@something.com"
        assert parsed_dict["list"][1] == {}
        assert parsed_dict["bool"] is True
        assert parsed_dict["none"] is None


@pytest.mark.parametrize('dt, content', [
    (   # Date.
        datetime.date(1992, 8, 19),
        '1992-08-19',
    ),
    (   # Naive time.
        datetime.time(15, 10),
        '15:10:00',
    ),
    (   # Aware time in UTC.
        datetime.time(15, 10, tzinfo=pytz.UTC),
        '15:10:00+00:00',
    ),
    (   # Aware local time.
        datetime.time(15, 10, tzinfo=pytz.FixedOffset(8 * 60)),
        '15:10:00+08:00',
    ),
    (   # Naive datetime.
        datetime.datetime(1992, 8, 19, 15, 10),
        '1992-08-19T15:10:00',
    ),
    (   # Aware datetime in UTC.
        datetime.datetime(1992, 8, 19, 15, 10, tzinfo=pytz.UTC),
        '1992-08-19T15:10:00Z',
    ),
    (   # Aware local datetime.
        datetime.datetime(1992, 8, 19, 15, 10, tzinfo=pytz.FixedOffset(8 * 60)),
        '1992-08-19T15:10:00+08:00',
    ),
])
def test_token_date(dt, content):
    item = tomlkit.item(dt)
    assert item.as_string() == content


def test_dump_nonascii_string():
    content = u'name = "Stažené"\n'
    toml_content = tomlkit.dumps(tomlkit.loads(content))
    assert toml_content == content
