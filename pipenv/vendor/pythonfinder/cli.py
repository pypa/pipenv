#!/usr/bin/env python
# -*- coding=utf-8 -*-
from __future__ import print_function, absolute_import
import click
import crayons
import sys
from . import __version__
from .pythonfinder import Finder


@click.command()
@click.option("--find", default=False, nargs=1, help="Find a specific python version.")
@click.option("--which", default=False, nargs=1, help="Run the which command.")
@click.option(
    "--findall", is_flag=True, default=False, help="Find all python versions."
)
@click.option(
    "--version", is_flag=True, default=False, help="Display PythonFinder version."
)
@click.option("--ignore-unsupported/--no-unsupported", is_flag=True, default=True, envvar="PYTHONFINDER_IGNORE_UNSUPPORTED", help="Ignore unsupported python versions.")
@click.version_option(prog_name='pyfinder', version=__version__)
@click.pass_context
def cli(ctx, find=False, which=False, findall=False, version=False, ignore_unsupported=True):
    if version:
        click.echo(
            "{0} version {1}".format(
                crayons.white("PythonFinder", bold=True), crayons.yellow(__version__)
            )
        )
        sys.exit(0)
    finder = Finder(ignore_unsupported=ignore_unsupported)
    if findall:
        versions = finder.find_all_python_versions()
        if versions:
            click.secho("Found python at the following locations:", fg="green")
            for v in versions:
                py = v.py_version
                click.secho(
                    "{py.name!s}: {py.version!s} ({py.architecture!s}) @ {py.comes_from.path!s}".format(
                        py=py
                    ),
                    fg="yellow",
                )
        else:
            click.secho(
                "ERROR: No valid python versions found! Check your path and try again.",
                fg="red",
            )
    if find:
        click.secho("Searching for python: {0!s}".format(find.strip()), fg="yellow")
        found = finder.find_python_version(find.strip())
        if found:
            click.secho("Found python at the following locations:", fg="green")
            sys.exit(0)
        else:
            click.secho("Failed to find matching executable...", fg="yellow")
            sys.exit(1)
    elif which:
        found = finder.system_path.which(which.strip())
        if found:
            click.secho("Found Executable: {0}".format(found), fg="white")
            sys.exit(0)
        else:
            click.secho("Failed to find matching executable...", fg="yellow")
            sys.exit(1)
    else:
        click.echo("Please provide a command", color="red")
        sys.exit(1)
    sys.exit()


if __name__ == "__main__":
    cli()
