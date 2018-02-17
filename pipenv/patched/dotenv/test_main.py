import os
from textwrap import dedent
import unittest

from main import parse_dotenv


class TestParseDotenv(unittest.TestCase):
    filename = 'testfile.conf'

    def tearDown(self):
        if os.path.exists(self.filename):
            os.remove(self.filename)

    def write_file(self, contents):
        with open(self.filename, 'w') as f:
            f.write(contents)

    def assert_parsed(self, *expected):
        parsed = parse_dotenv(self.filename)
        for expected_key, expected_val in expected:
            actual_key, actual_val = next(parsed)
            self.assertEqual(actual_key, expected_key)
            self.assertEqual(actual_val, expected_val)

        with self.assertRaises(StopIteration):
            next(parsed)

    def test_value_unquoted(self):
        self.write_file(dedent("""
        var1 = value1
        var2=value2
        """))
        self.assert_parsed(('var1', 'value1'), ('var2', 'value2'))

    def test_value_double_quoted(self):
        self.write_file(dedent("""
        var1 = "value1"
        var2="value2"
        """))
        self.assert_parsed(('var1', 'value1'), ('var2', 'value2'))

    def test_value_single_quoted(self):
        self.write_file(dedent("""
        var1 = 'value1'
        var2='value2'
        """))
        self.assert_parsed(('var1', 'value1'), ('var2', 'value2'))

    def test_value_with_space_double_quoted(self):
        self.write_file(dedent("""
        var1 = "value1 with spaces"
        var2 = "othervalue"
        """))
        self.assert_parsed(('var1', 'value1 with spaces'),
                           ('var2', 'othervalue'))

    def test_value_with_space_single_quoted(self):
        self.write_file(dedent("""
        var1 = 'value with spaces'
        var2 = 'othervalue'
        """))
        self.assert_parsed(('var1', 'value with spaces'),
                           ('var2', 'othervalue'))

    def test_values_with_mixed_quotes_and_spaces(self):
        self.write_file(dedent("""
        var1 = 'value with spaces'
        var2=   othervalue
        var3="double-quoted value with spaces"
        var4 = "double-quoted value
        with
        newlines"
        var5='single quote
        and newline'
        """))
        self.assert_parsed(('var1', 'value with spaces'),
                           ('var2', 'othervalue'),
                           ('var3', 'double-quoted value with spaces'),
                           ('var4', 'double-quoted value\nwith\nnewlines'),
                           ('var5', 'single quote\nand newline'))


if __name__ == '__main__':
    unittest.main()
