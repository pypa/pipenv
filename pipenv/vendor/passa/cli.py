# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

import argparse
import collections
import functools
import io
import os

import plette
import requirementslib
import six

from . import operations


_DEFAULT_NEWLINES = "\n"


def _preferred_newlines(f):
    if isinstance(f.newlines, six.text_type):
        return f.newlines
    return _DEFAULT_NEWLINES


FileModel = collections.namedtuple("FileModel", "model location newline")
Project = collections.namedtuple("Project", "root pipfile lockfile")


def _build_project(root):
    root = os.path.abspath(root)
    pipfile_location = os.path.join(root, "Pipfile")
    with io.open(pipfile_location, encoding="utf-8") as f:
        pipfile = plette.Pipfile.load(f)
        pipfile_le = _preferred_newlines(f)

    lockfile_location = os.path.join(root, "Pipfile.lock")
    if os.path.exists(lockfile_location):
        with io.open(lockfile_location, encoding="utf-8") as f:
            lockfile = plette.Lockfile.load(f)
            lockfile_le = _preferred_newlines(f)
    else:
        lockfile = None
        lockfile_le = _DEFAULT_NEWLINES

    return Project(
        root=root,
        pipfile=FileModel(pipfile, pipfile_location, pipfile_le),
        lockfile=FileModel(lockfile, lockfile_location, lockfile_le),
    )


def locking_subparser(name):

    def decorator(f):

        @functools.wraps(f)
        def wrapped(subs):
            parser = subs.add_parser(name)
            parser.set_defaults(_cmdkey=name)
            parser.add_argument(
                "project",
                type=_build_project,
            )
            parser.add_argument(
                "-o", "--output",
                choices=["write", "print", "none"],
                default="print",
                help="How to output the lockfile",
            )
            f(parser)

        return wrapped

    return decorator


@locking_subparser("add")
def add_parser(parser):
    parser.add_argument(
        "requirement",
        nargs="+", type=requirementslib.Requirement.from_line,
        help="Requirement(s) to add",
    )


@locking_subparser("lock")
def lock_parser(parser):
    parser.add_argument(
        "--force",
        action="store_true", default=False,
        help="Always re-generate lock file",
    )


def get_parser():
    parser = argparse.ArgumentParser(prog="passa")
    subs = parser.add_subparsers()
    lock_parser(subs)
    return parser


def parse_arguments(argv):
    parser = get_parser()
    return parser.parse_args(argv)


def main(argv=None):
    options = parse_arguments(argv)
    operations.main(options)


if __name__ == "__main__":
    main()
