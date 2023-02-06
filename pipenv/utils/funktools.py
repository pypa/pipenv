"""
A small collection of useful functional tools for working with iterables.

This module should be in requirementslib. Once we release a new version of requirementslib
we can remove this file and use the one in requirementslib.
"""
from functools import partial
from itertools import islice, tee
from typing import Any, Iterable


def _is_iterable(elem: Any) -> bool:
    if getattr(elem, "__iter__", False) or isinstance(elem, Iterable):
        return True
    return False


def take(n: int, iterable: Iterable) -> Iterable:
    """Take n elements from the supplied iterable without consuming it.

    :param int n: Number of unique groups
    :param iter iterable: An iterable to split up
    """
    return list(islice(iterable, n))


def chunked(n: int, iterable: Iterable) -> Iterable:
    """Split an iterable into lists of length *n*.

    :param int n: Number of unique groups
    :param iter iterable: An iterable to split up

    """
    return iter(partial(take, n, iter(iterable)), [])


def unnest(elem: Iterable) -> Any:
    # type: (Iterable) -> Any
    """Flatten an arbitrarily nested iterable.

    :param elem: An iterable to flatten
    :type elem: :class:`~collections.Iterable`
    >>> nested_iterable = (
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
    >>> list(unnest(nested_iterable))
    [1234, 3456, 4398345, 234234, 2396, 928379, 29384, 293759,
     2347, 2098, 7987, 27599]
    """

    if isinstance(elem, Iterable) and not isinstance(elem, str):
        elem, target = tee(elem, 2)
    else:
        target = elem
    if not target or not _is_iterable(target):
        yield target
    else:
        for el in target:
            if isinstance(el, Iterable) and not isinstance(el, str):
                el, el_copy = tee(el, 2)
                for sub in unnest(el_copy):
                    yield sub
            else:
                yield el


def dedup(iterable: Iterable) -> Iterable:
    # type: (Iterable) -> Iterable
    """Deduplicate an iterable object like iter(set(iterable)) but order-
    preserved."""

    return iter(dict.fromkeys(iterable))
