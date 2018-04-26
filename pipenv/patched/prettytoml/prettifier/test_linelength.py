from .linelength import line_length_limiter
from .common import assert_prettifier_works, elements_to_text, text_to_elements
import pytoml


def test_splitting_string():
    toml_text = """
k = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. In et lectus nec erat condimentum scelerisque gravida sed ipsum. Mauris non orci tincidunt, viverra enim eget, tincidunt orci. Sed placerat nibh vitae ante maximus egestas maximus eu quam. Praesent vehicula mauris vestibulum, mattis turpis sollicitudin, aliquam felis. Pellentesque volutpat pharetra purus vel finibus. Vestibulum sed tempus dui. Maecenas auctor sit amet diam et porta. Morbi id libero at elit ultricies porta vel vitae nullam. "
"""

    expected_toml_text = """
k = \"\"\"
Lorem ipsum dolor sit amet, consectetur adipiscing elit. In et lectus nec erat condimentum scelerisque gravida sed \\
ipsum. Mauris non orci tincidunt, viverra enim eget, tincidunt orci. Sed placerat nibh vitae ante maximus egestas \\
maximus eu quam. Praesent vehicula mauris vestibulum, mattis turpis sollicitudin, aliquam felis. Pellentesque volutpat \\
pharetra purus vel finibus. Vestibulum sed tempus dui. Maecenas auctor sit amet diam et porta. Morbi id libero at elit \\
ultricies porta vel vitae nullam. \"\"\"
"""
    assert_prettifier_works(toml_text, expected_toml_text, line_length_limiter)


def test_splitting_array():
    toml_text = """

somethingweird = false

[section]
k = [4, 8, 15, 16, 23, 42, 4, 8, 15, 16, 23, 42, 4, 8, 15, 16, 23, 42, 4, 8, 15, 16, 23, 42, 4, 8, 15, 16, 23, 42, 4, 8, 15, 16, 23, 42, 4, 8, 15, 16, 23, 42]


[data]
id = 12

"""

    prettified = elements_to_text(line_length_limiter(text_to_elements(toml_text)))

    assert pytoml.loads(prettified) == pytoml.loads(toml_text)
    assert all(len(line) < 120 for line in prettified.split('\n'))
