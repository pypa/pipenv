
from .tableassignment import table_assignment_spacing
from .common import assert_prettifier_works


def test_table_assignment_spacing():
    toml_text = """
    key1= "my value"
    key2 =42
    keys        =   [4, 5,1]

    [section]
    key1= "my value"
    key2 =42
    keys        =   [4, 5,1]
"""

    expected_prettified = """
    key1 = "my value"
    key2 = 42
    keys = [4, 5,1]

    [section]
    key1 = "my value"
    key2 = 42
    keys = [4, 5,1]
"""

    assert_prettifier_works(toml_text, expected_prettified, table_assignment_spacing)
