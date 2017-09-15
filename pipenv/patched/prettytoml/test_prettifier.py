
from .prettifier import prettify
from .prettifier.common import assert_prettifier_works
import pytoml


def test_prettifying_against_humanly_verified_sample():
    toml_source = open('sample.toml').read()
    expected = open('sample-prettified.toml').read()

    assert_prettifier_works(toml_source, expected, prettify)
    assert pytoml.loads(toml_source) == pytoml.loads(expected)
