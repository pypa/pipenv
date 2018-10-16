# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals


def _trace_visit_vertex(graph, current, target, visited, path, paths):
    if current == target:
        paths.append(path)
        return
    for v in graph.iter_children(current):
        if v == current or v in visited:
            continue
        next_path = path + [current]
        next_visited = visited | {current}
        _trace_visit_vertex(graph, v, target, next_visited, next_path, paths)


def trace_graph(graph):
    """Build a collection of "traces" for each package.

    A trace is a list of names that eventually leads to the package. For
    example, if A and B are root dependencies, A depends on C and D, B
    depends on C, and C depends on D, the return value would be like::

        {
            None: [],
            "A": [None],
            "B": [None],
            "C": [[None, "A"], [None, "B"]],
            "D": [[None, "B", "C"], [None, "A"]],
        }
    """
    result = {None: []}
    for vertex in graph:
        result[vertex] = []
        for root in graph.iter_children(None):
            paths = []
            _trace_visit_vertex(graph, root, vertex, {None}, [None], paths)
            result[vertex].extend(paths)
    return result
