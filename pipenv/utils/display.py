from pipenv.vendor import click


def format_help(help):
    """Formats the help string."""
    help = help.replace("Options:", str(click.style("Options:", bold=True)))
    help = help.replace(
        "Usage: pipenv", str("Usage: {}".format(click.style("pipenv", bold=True)))
    )
    help = help.replace("  check", str(click.style("  check", fg="red", bold=True)))
    help = help.replace("  clean", str(click.style("  clean", fg="red", bold=True)))
    help = help.replace("  graph", str(click.style("  graph", fg="red", bold=True)))
    help = help.replace(
        "  install", str(click.style("  install", fg="magenta", bold=True))
    )
    help = help.replace("  lock", str(click.style("  lock", fg="green", bold=True)))
    help = help.replace("  open", str(click.style("  open", fg="red", bold=True)))
    help = help.replace("  run", str(click.style("  run", fg="yellow", bold=True)))
    help = help.replace("  shell", str(click.style("  shell", fg="yellow", bold=True)))
    help = help.replace(
        "  scripts", str(click.style("  scripts", fg="yellow", bold=True))
    )
    help = help.replace("  sync", str(click.style("  sync", fg="green", bold=True)))
    help = help.replace(
        "  uninstall", str(click.style("  uninstall", fg="magenta", bold=True))
    )
    help = help.replace("  update", str(click.style("  update", fg="green", bold=True)))
    additional_help = """
Usage Examples:
   Create a new project using Python 3.7, specifically:
   $ {}

   Remove project virtualenv (inferred from current directory):
   $ {}

   Install all dependencies for a project (including dev):
   $ {}

   Create a lockfile containing pre-releases:
   $ {}

   Show a graph of your installed dependencies:
   $ {}

   Check your installed dependencies for security vulnerabilities:
   $ {}

   Install a local setup.py into your virtual environment/Pipfile:
   $ {}

   Use a lower-level pip command:
   $ {}

Commands:""".format(
        click.style("pipenv --python 3.7", fg="yellow"),
        click.style("pipenv --rm", fg="yellow"),
        click.style("pipenv install --dev", fg="yellow"),
        click.style("pipenv lock --pre", fg="yellow"),
        click.style("pipenv graph", fg="yellow"),
        click.style("pipenv check", fg="yellow"),
        click.style("pipenv install -e .", fg="yellow"),
        click.style("pipenv run pip freeze", fg="yellow"),
    )
    help = help.replace("Commands:", additional_help)
    return help
