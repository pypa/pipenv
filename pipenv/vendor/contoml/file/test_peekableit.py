from contoml.file.peekableit import PeekableIterator


def test_peekable_iterator():

    peekable = PeekableIterator(i for i in (1, 2, 3, 4))

    assert peekable.peek() == 1
    assert peekable.peek() == 1
    assert peekable.peek() == 1

    assert [next(peekable), next(peekable), next(peekable), next(peekable)] == [1, 2, 3, 4]
