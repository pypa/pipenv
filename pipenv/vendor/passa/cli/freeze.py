# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import contextlib
import io
import itertools
import sys

import six
import vistir.misc

from ._base import BaseCommand


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
    line = requirement.as_line(sources=sources, include_hashes=include_hashes)
    if not isinstance(line, six.text_type):
        line = line.decode("utf-8")
    return line


@contextlib.contextmanager
def open_for_output(filename):
    if filename is None:
        yield sys.stdout
        return
    with io.open(filename, "w", encoding="utf-8", newline="\n") as f:
        yield f


def main(options):
    from requirementslib import Requirement

    lockfile = options.project.lockfile
    if not lockfile:
        print("Pipfile.lock is required to export.", file=sys.stderr)
        return 1

    section_names = []
    if options.default:
        section_names.append("default")
    if options.dev:
        section_names.append("develop")
    requirements = [
        Requirement.from_pipfile(key, entry._data)
        for key, entry in itertools.chain.from_iterable(
            lockfile.get(name, {}).items()
            for name in section_names
        )
    ]

    include_hashes = options.include_hashes
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

    with open_for_output(options.target) as f:
        for line in source_lines:
            f.write(line)
            f.write("\n")
        f.write("\n")
        for line in requirement_lines:
            f.write(line)
            f.write("\n\n")


class Command(BaseCommand):

    name = "freeze"
    description = "Export project depenencies to requirements.txt."
    parsed_main = main

    def add_arguments(self):
        super(Command, self).add_arguments()
        self.parser.add_argument(
            "--target",
            default=None,
            help="file to export into (default is to print to stdout)",
        )
        self.parser.add_argument(
            "--dev",
            action="store_true", default=False,
            help="include development packages in requirements.txt",
        )
        self.parser.add_argument(
            "--no-default", dest="default",
            action="store_false", default=True,
            help="do not include default packages in requirements.txt",
        )
        include_hashes_group = self.parser.add_mutually_exclusive_group()
        include_hashes_group.add_argument(
            "--include-hashes", dest="include_hashes",
            action="store_true",
            help="output hashes in requirements.txt (default is to guess)",
        )
        include_hashes_group.add_argument(
            "--no-include-hashes", dest="include_hashes",
            action="store_false",
            help=("do not output hashes in requirements.txt "
                  "(default is to guess)"),
        )


if __name__ == "__main__":
    Command.run_current_module()
