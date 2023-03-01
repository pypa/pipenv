import pytest

from pipenv.utils.funktools import dedup, unnest, _is_iterable


def test_unnest():
    nested_iterable = (
            1234, (3456, 4398345, (234234)), (
                2396, (
                    928379, 29384, (
                        293759, 2347, (
                            2098, 7987, 27599
                        )
                    )
                )
            )
        )
    list(unnest(nested_iterable)) == [1234, 3456, 4398345, 234234,
                                      2396, 928379, 29384, 293759,
                                      2347, 2098, 7987, 27599]


@pytest.mark.parametrize(
    "iterable, result",
    [
        [["abc", "def"], True],
        [("abc", "def"), True],
        ["abcdef", True],
        [None, False],
        [1234, False],
    ],
)
def test_is_iterable(iterable, result):
    assert _is_iterable(iterable) is result


def test_unnest_none():
    assert list(unnest(None)) == [None]


def test_dedup():
    dup_strings = ["abcde", "fghij", "klmno", "pqrst", "abcde", "klmno"]
    assert list(dedup(dup_strings)) == [
        "abcde",
        "fghij",
        "klmno",
        "pqrst",
    ]
    dup_ints = (12345, 56789, 12345, 54321, 98765, 54321)
    assert list(dedup(dup_ints)) == [12345, 56789, 54321, 98765]
