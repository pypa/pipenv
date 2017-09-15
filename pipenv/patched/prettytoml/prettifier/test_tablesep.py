
from .tablesep import table_separation
from .common import assert_prettifier_works


def test_table_separation():

    toml_text = """key1 = "value1"
key2 = 22
[section]
k = false
m= "true"



[another.section]
l = "t"
creativity = "on vacation"
"""

    expected_toml_text = """key1 = "value1"
key2 = 22

[section]
k = false
m= "true"

[another.section]
l = "t"
creativity = "on vacation"

"""

    assert_prettifier_works(toml_text, expected_toml_text, table_separation)
