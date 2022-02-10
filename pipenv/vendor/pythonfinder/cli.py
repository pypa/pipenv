# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import pipenv.vendor.click as click

from . import __version__
from .pythonfinder import Finder


@click.command()
@click.option("--find", default=False, nargs=1, help="Find a specific python version.")
@click.option("--which", default=False, nargs=1, help="Run the which command.")
@click.option("--findall", is_flag=True, default=False, help="Find all python versions.")
@click.option(
    "--version", is_flag=True, default=False, help="Display PythonFinder version."
)
@click.option(
    "--ignore-unsupported/--no-unsupported",
    is_flag=True,
    default=True,
    envvar="PYTHONFINDER_IGNORE_UNSUPPORTED",
    help="Ignore unsupported python versions.",
)
@click.version_option(prog_name="pyfinder", version=__version__)
@click.pass_context
def cli(
    ctx, find=False, which=False, findall=False, version=False, ignore_unsupported=True
):
    if version:
        click.echo(
            "{0} version {1}".format(
                click.style("PythonFinder", fg="white", bold=True),
                click.style(str(__version__), fg="yellow")
            )
        )
        ctx.exit()
    finder = Finder(ignore_unsupported=ignore_unsupported)
    if findall:
        versions = [v for v in finder.find_all_python_versions()]
        if versions:
            click.secho("Found python at the following locations:", fg="green")
            for v in versions:
                py = v.py_version
                comes_from = getattr(py, "comes_from", None)
                if comes_from is not None:
                    comes_from_path = getattr(comes_from, "path", v.path)
                else:
                    comes_from_path = v.path
                click.secho(
                    "{py.name!s}: {py.version!s} ({py.architecture!s}) @ {comes_from!s}".format(
                        py=py, comes_from=comes_from_path
                    ),
                    fg="yellow",
                )
            ctx.exit()
        else:
            click.secho(
                "ERROR: No valid python versions found! Check your path and try again.",
                fg="red",
            )
    if find:
        click.secho("Searching for python: {0!s}".format(find.strip()), fg="yellow")
        found = finder.find_python_version(find.strip())
        if found:
            py = found.py_version
            comes_from = getattr(py, "comes_from", None)
            if comes_from is not None:
                comes_from_path = getattr(comes_from, "path", found.path)
            else:
                comes_from_path = found.path
            arch = getattr(py, "architecture", None)
            click.secho("Found python at the following locations:", fg="green")
            click.secho(
                "{py.name!s}: {py.version!s} ({py.architecture!s}) @ {comes_from!s}".format(
                    py=py, comes_from=comes_from_path
                ),
                fg="yellow",
            )
            ctx.exit()
        else:
            click.secho("Failed to find matching executable...", fg="yellow")
            ctx.exit(1)
    elif which:
        found = finder.system_path.which(which.strip())
        if found:
            click.secho("Found Executable: {0}".format(found), fg="white")
            ctx.exit()
        else:
            click.secho("Failed to find matching executable...", fg="yellow")
            ctx.exit(1)
    else:
        click.echo("Please provide a command", color="red")
        ctx.exit(1)
    ctx.exit()


if __name__ == "__main__":
    cli()
