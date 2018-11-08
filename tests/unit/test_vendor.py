# -*- coding: utf-8 -*-
# We need to import the patched packages directly from sys.path, so the
# identity checks can pass.
import os

import pipenv  # noqa
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
