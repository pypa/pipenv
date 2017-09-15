
from .common import assert_prettifier_works
from .commentspace import comment_space


def test_comment_space():

    toml_text = """
my_key = string
id = 12 # My special ID

[section.name]
headerk = false
# Own-line comment should stay the same
other_key = "value"
"""

    expected_toml_text = """
my_key = string
id = 12\t# My special ID

[section.name]
headerk = false
# Own-line comment should stay the same
other_key = "value"
"""

    assert_prettifier_works(toml_text, expected_toml_text, comment_space)
