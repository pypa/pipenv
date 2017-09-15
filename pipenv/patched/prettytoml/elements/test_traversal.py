from prettytoml.elements.test_common import DummyFile


def test_traversal():
    dummy_file = DummyFile()

    assert dummy_file._find_following_table_header(-1) == 1
    assert dummy_file._find_following_table_header(1) == 3
    assert dummy_file._find_following_table_header(3) == 5
    assert dummy_file._find_following_table_header(5) == 7
    assert dummy_file._find_following_table_header(7) < 0

    assert dummy_file._find_preceding_table(30) == 8
    assert dummy_file._find_preceding_table(8) == 6
    assert dummy_file._find_preceding_table(6) == 4
    assert dummy_file._find_preceding_table(4) == 2
    assert dummy_file._find_preceding_table(2) == 0
    assert dummy_file._find_preceding_table(0) < 0
