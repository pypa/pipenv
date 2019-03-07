# -*- coding=utf-8 -*-
from __future__ import absolute_import

import argparse
import os
import sys

import tomlkit.exceptions

import passa.models.projects
import vistir


PYTHON_VERSION = ".".join(str(v) for v in sys.version_info[:2])


class Project(passa.models.projects.Project):
    def __init__(self, root, *args, **kwargs):
        root = vistir.compat.Path(root).absolute()
        pipfile = root.joinpath("Pipfile")
        if not pipfile.is_file():
            raise argparse.ArgumentError(
                "project", "{0!r} is not a Pipfile project".format(root),
            )
        try:
            super(Project, self).__init__(root.as_posix(), *args, **kwargs)
        except tomlkit.exceptions.ParseError as e:
            raise argparse.ArgumentError(
                "project", "failed to parse Pipfile: {0!r}".format(str(e)),
            )

    def __name__(self):
        return "Project Root"


class Option(object):
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def add_to_parser(self, parser):
        parser.add_argument(*self.args, **self.kwargs)

    def add_to_group(self, group):
        group.add_argument(*self.args, **self.kwargs)


class ArgumentGroup(object):
    def __init__(
            self, name, parser=None,
            is_mutually_exclusive=False,
            required=None, options=None):
        self.name = name
        self.options = options or []
        self.parser = parser
        self.required = required
        self.is_mutually_exclusive = is_mutually_exclusive
        self.argument_group = None

    def add_to_parser(self, parser):
        group = None
        if self.is_mutually_exclusive:
            group = parser.add_mutually_exclusive_group(required=self.required)
        else:
            group = parser.add_argument_group()
        for option in self.options:
            option.add_to_group(group)
        self.argument_group = group
        self.parser = parser


project = Option(
    "--project", metavar="project", default=os.getcwd(), type=Project,
    help="path to project root (directory containing Pipfile)",
)

new_project = Option(
    "--project", metavar="project", default=os.getcwd(), type=str,
    help="path to project root (directory containing Pipfile)",
)

python_version = Option(
    "--py-version", "--python-version", "--requires-python", metavar="python-version",
    dest="python_version", default=PYTHON_VERSION, type=str,
    help="required minor python version for the project"
)

packages = Option(
    "packages", metavar="package", nargs="*",
    help="requirement to add (can be used multiple times)",
)

editable = Option(
    '-e', '--editable', dest='editables', nargs="*", default=[], metavar='path/vcs',
    help="editable requirement to add (can be used multiple times)",
)

dev = Option(
    "--dev", action="store_true", default=False,
    help="Use [dev-packages] for install/freeze/uninstall operations",
)

no_sync = Option(
    "--no-sync", dest="sync", action="store_false", default=True,
    help="do not synchronize the environment",
)

target = Option(
    "-t", "--target", default=None,
    help="file to export into (default is to print to stdout)"
)

no_default = Option(
    "--no-default", dest="default", action="store_false", default=True,
    help="do not include default packages when exporting, importing, or cleaning"
)

include_hashes = Option(
    "--include-hashes", dest="include_hashes", action="store_true",
    help="output hashes in requirements.txt (default is to guess)",
)

no_include_hashes = Option(
    "--no-include-hashes", dest="include_hashes", action="store_false",
    help="do not output hashes in requirements.txt (default is to guess)",
)

no_check = Option(
    "--no-check", dest="check", action="store_false", default=True,
    help="do not check if Pipfile.lock is up to date, always resolve",
)

no_clean = Option(
    "--no-clean", dest="clean", action="store_false", default=True,
    help="do not remove packages not specified in Pipfile.lock",
)

dev_only = Option(
    "--dev", dest="only", action="store_const", const="dev",
    help="only try to modify [dev-packages]",
)

default_only = Option(
    "--default", dest="only", action="store_const", const="default",
    help="only try to modify [default]",
)

strategy = Option(
    "--strategy", choices=["eager", "only-if-needed"], default="only-if-needed",
    help="how dependency upgrading is handled",
)

include_hashes_group = ArgumentGroup("include_hashes", is_mutually_exclusive=True, options=[include_hashes, no_include_hashes])
dev_group = ArgumentGroup("dev", is_mutually_exclusive="True", options=[dev_only, default_only])
package_group = ArgumentGroup("packages", options=[packages, editable, dev, no_sync])
new_project_group = ArgumentGroup("new-project", options=[new_project, python_version])
