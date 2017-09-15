from prettytoml.util import is_sequence_like, is_dict_like, chunkate_string


def test_is_sequence_like():
    assert is_sequence_like([1, 3, 4])
    assert not is_sequence_like(42)
    

def test_is_dict_like():
    assert is_dict_like({'name': False})
    assert not is_dict_like(42)
    assert not is_dict_like([4, 8, 15])


def test_chunkate_string():

    text = """Lorem ipsum dolor sit amet, consectetur adipiscing elit. In et lectus nec erat condimentum scelerisque gravida sed ipsum. Mauris non orci tincidunt, viverra enim eget, tincidunt orci. Sed placerat nibh vitae ante maximus egestas maximus eu quam. Praesent vehicula mauris vestibulum, mattis turpis sollicitudin, aliquam felis. Pellentesque volutpat pharetra purus vel finibus. Vestibulum sed tempus dui. Maecenas auctor sit amet diam et porta. Morbi id libero at elit ultricies porta vel vitae nullam. """

    chunks = chunkate_string(text, 50)

    assert ''.join(chunks) == text
    assert all(len(chunk) <= 50 for chunk in chunks)
