from __future__ import annotations

import pipenv.vendor.click as click

from . import __version__
from .pythonfinder import Finder


@click.command()
@click.option("--find", nargs=1, help="Find a specific python version.")
@click.option("--which", nargs=1, help="Run the which command.")
@click.option("--findall", is_flag=True, default=False, help="Find all python versions.")
@click.option(
    "--ignore-unsupported",
    "--no-unsupported",
    is_flag=True,
    default=True,
    envvar="PYTHONFINDER_IGNORE_UNSUPPORTED",
    help="Ignore unsupported python versions.",
)
@click.version_option(
    prog_name=click.style("PythonFinder", bold=True),
    version=click.style(__version__, fg="yellow"),
)
@click.pass_context
def cli(
    ctx, find=False, which=False, findall=False, version=False, ignore_unsupported=True
):
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
        click.secho(f"Searching for python: {find.strip()!s}", fg="yellow")
        found = finder.find_python_version(find.strip())
        if found:
            py = found.py_version
            comes_from = getattr(py, "comes_from", None)
            if comes_from is not None:
                comes_from_path = getattr(comes_from, "path", found.path)
            else:
                comes_from_path = found.path

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
            click.secho(f"Found Executable: {found}", fg="white")
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
