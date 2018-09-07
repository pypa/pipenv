# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

from resolvelib import NoVersionsAvailable, ResolutionImpossible

from .base import BaseReporter


def _print_title(text):
    print('\n{:=^84}\n'.format(text))


def _print_requirement(r, end='\n'):
    print('{:>40}'.format(r.as_line(include_hashes=False)), end=end)


def _print_dependency(state, key):
    _print_requirement(state.mapping[key], end='')
    parents = sorted(
        state.graph.iter_parents(key),
        key=lambda n: (-1, '') if n is None else (ord(n[0].lower()), n),
    )
    for i, p in enumerate(parents):
        if p is None:
            line = '(user)'
        else:
            line = state.mapping[p].as_line(include_hashes=False)
        if i == 0:
            padding = ' <= '
        else:
            padding = ' ' * 44
        print('{pad}{line}'.format(pad=padding, line=line))


class Reporter(BaseReporter):
    """A reporter implementation that prints messages to stdout.
    """
    def handle_resolvelib_starting(self, context):
        context["child"]._prev_mapping = None

    def handle_resolvelib_ending_round(self, context):
        _print_title(' Round {} '.format(context["index"]))
        mapping = context["state"].mapping
        if context["child"]._prev_mapping is None:
            difference = set(mapping.keys())
            changed = set()
        else:
            prev = context["child"]._prev_mapping
            difference = set(mapping.keys()) - set(prev.keys())
            changed = set(
                k for k, v in mapping.items()
                if k in prev and prev[k] != v
            )
        context["child"]._prev_mapping = mapping

        if difference:
            print('New pins: ')
            for k in difference:
                _print_dependency(context["state"], k)
        print()

        if changed:
            print('Changed pins:')
            for k in changed:
                _print_dependency(context["state"], k)
        print()

    def handle_lock_starting(self, context):
        _print_title(' User requirements ')
        for r in context["requirements"]:
            _print_requirement(r)

    def handle_lock_trace_ended(self, context):
        _print_title(" STABLE PINS ")
        mapping = context["state"].mapping
        for k in sorted(mapping):
            print(mapping[k].as_line(include_hashes=False))
            paths = context["traces"][k]
            for path in paths:
                if path == [None]:
                    print('    User requirement')
                    continue
                print('   ', end='')
                for v in reversed(path[1:]):
                    line = mapping[v].as_line(include_hashes=False)
                    print(' <=', line, end='')
                print()
        print()

    def handle_lock_failed(self, context):
        e = context["exception"]
        if isinstance(e, ResolutionImpossible):
            print("\nCANNOT RESOLVE.\nOFFENDING REQUIREMENTS:")
            for r in e.requirements:
                _print_requirement(r)
        elif isinstance(e, NoVersionsAvailable):
            print("\nCANNOT RESOLVE. NO CANDIDATES FOUND FOR:")
            print("{:>40}".format(e.requirement.as_line(include_hashes=False)))
            if e.parent:
                line = e.parent.as_line(include_hashes=False)
                print("{:>41}".format("(from {})".format(line)))
            else:
                print("{:>41}".format("(user)"))
        else:
            raise
