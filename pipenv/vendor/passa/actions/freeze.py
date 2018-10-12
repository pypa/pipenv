# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import contextlib
import io
import itertools
import sys

import vistir.misc


def _source_as_lines(source, extra):
    url = source["url"]
    if extra:
        lines = ["--extra-index-url {}".format(url)]
    else:
        lines = ["--index-url {}".format(url)]
    if not source.get("verify_ssl", True):
        lines = ["--trusted-host {}".format(url)]
    return lines


def _requirement_as_line(requirement, sources, include_hashes):
    if requirement.index:
        sources = sources
    else:
        sources = None
    line = vistir.misc.to_text(
        requirement.as_line(sources=sources, include_hashes=include_hashes)
    )
    return line


@contextlib.contextmanager
def open_for_output(filename):
    if filename is None:
        yield sys.stdout
        return
    with io.open(filename, "w", encoding="utf-8", newline="\n") as f:
        yield f


def freeze(project=None, default=True, dev=True, include_hashes=None, target=None):
    from requirementslib import Requirement

    lockfile = project.lockfile
    if not lockfile:
        print("Pipfile.lock is required to export.", file=sys.stderr)
        return 1

    section_names = []
    if default:
        section_names.append("default")
    if dev:
        section_names.append("develop")
    requirements = [
        Requirement.from_pipfile(key, entry._data)
        for key, entry in itertools.chain.from_iterable(
            lockfile.get(name, {}).items()
            for name in section_names
        )
    ]

    if include_hashes is None:
        include_hashes = all(r.is_named for r in requirements)

    sources = lockfile.meta.sources._data

    source_lines = list(vistir.misc.dedup(itertools.chain(
        itertools.chain.from_iterable(
            _source_as_lines(source, False)
            for source in sources[:1]
        ),
        itertools.chain.from_iterable(
            _source_as_lines(source, True)
            for source in sources[1:]
        ),
    )))

    requirement_lines = sorted(vistir.misc.dedup(
        _requirement_as_line(requirement, sources, include_hashes)
        for requirement in requirements
    ))

    with open_for_output(target) as f:
        for line in source_lines:
            f.write(line)
            f.write("\n")
        f.write("\n")
        for line in requirement_lines:
            f.write(line)
            f.write("\n")
