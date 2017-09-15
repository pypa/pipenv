
from .tableindent import table_entries_should_be_uniformly_indented
from .common import assert_prettifier_works


def test_table_entries_should_be_uniformly_indented():
    toml_text = """
    [firstlevel]
hello = "my name"
    my_id = 12

    [firstlevel.secondlevel]
      my_truth = False
"""

    expected_toml_text = """
[firstlevel]
hello = "my name"
my_id = 12

  [firstlevel.secondlevel]
  my_truth = False
"""

    assert_prettifier_works(toml_text, expected_toml_text, table_entries_should_be_uniformly_indented)
