# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

from packaging.markers import Marker


def _strip_extra(elements):
    """Remove the "extra == ..." operands from the list.

    This is not a comprehensive implementation, but relies on an important
    characteristic of metadata generation: The "extra == ..." operand is always
    associated with an "and" operator. This means that we can simply remove the
    operand and the "and" operator associated with it.
    """
    extra_indexes = []
    for i, element in enumerate(elements):
        if isinstance(element, list):
            cancelled = _strip_extra(element)
            if cancelled:
                extra_indexes.append(i)
        elif isinstance(element, tuple) and element[0].value == "extra":
            extra_indexes.append(i)
    for i in reversed(extra_indexes):
        del elements[i]
        if i > 0 and elements[i - 1] == "and":
            # Remove the "and" before it.
            del elements[i - 1]
        elif elements:
            # This shouldn't ever happen, but is included for completeness.
            # If there is not an "and" before this element, try to remove the
            # operator after it.
            del elements[0]
    return (not elements)


def get_without_extra(marker):
    """Build a new marker without the `extra == ...` part.

    The implementation relies very deep into packaging's internals, but I don't
    have a better way now (except implementing the whole thing myself).

    This could return `None` if the `extra == ...` part is the only one in the
    input marker.
    """
    # TODO: Why is this very deep in the internals? Why is a better solution
    # implementing it yourself when someone is already maintaining a codebase
    # for this? It's literally a grammar implementation that is required to
    # meet the demands of a pep... -d
    if not marker:
        return None
    marker = Marker(str(marker))
    elements = marker._markers
    _strip_extra(elements)
    if elements:
        return marker
    return None


def _markers_collect_extras(markers, collection):
    # Optimization: the marker element is usually appended at the end.
    for el in reversed(markers):
        if (isinstance(el, tuple) and
                el[0].value == "extra" and
                el[1].value == "=="):
            collection.add(el[2].value)
        elif isinstance(el, list):
            _markers_collect_extras(el, collection)


def get_contained_extras(marker):
    """Collect "extra == ..." operands from a marker.

    Returns a list of str. Each str is a speficied extra in this marker.
    """
    if not marker:
        return set()
    marker = Marker(str(marker))
    extras = set()
    _markers_collect_extras(marker._markers, extras)
    return extras


def _markers_contains_extra(markers):
    # Optimization: the marker element is usually appended at the end.
    for element in reversed(markers):
        if isinstance(element, tuple) and element[0].value == "extra":
            return True
        elif isinstance(element, list):
            if _markers_contains_extra(element):
                return True
    return False


def contains_extra(marker):
    """Check whehter a marker contains an "extra == ..." operand.
    """
    if not marker:
        return False
    marker = Marker(str(marker))
    return _markers_contains_extra(marker._markers)
