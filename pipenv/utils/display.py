def format_help(help):
    """Formats the help string."""
    help = help.replace("Options:", "[bold]Options:[/bold]")
    help = help.replace("Usage: pipenv", "Usage: [bold]pipenv[/bold]")
    help = help.replace("  check", "[bold red]  check[/red bold]")
    help = help.replace("  clean", "[bold red]  clean[/red bold]")
    help = help.replace("  graph", "[bold red]  graph[/red bold]")
    help = help.replace("  install", "[bold magenta]  install[/magenta bold]")
    help = help.replace("  lock", "[bold green]  lock[/green bold]")
    help = help.replace("  open", "[bold red]  open[/red bold]")
    help = help.replace("  run", "[bold yellow]  run[/yellow bold]")
    help = help.replace("  shell", "[bold yellow]  shell[/yellow bold]")
    help = help.replace("  scripts", "[bold yellow]  scripts[/yellow bold]")
    help = help.replace("  sync", "[bold green]  sync[/green bold]")
    help = help.replace("  uninstall", "[bold magenta]  uninstall[/magenta bold]")
    help = help.replace("  update", "[bold green]  update[/green bold]")
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
        "[yellow]pipenv --python 3.7[/yellow]",
        "[yellow]pipenv --rm[/yellow]",
        "[yellow]pipenv install --dev[/yellow]",
        "[yellow]pipenv lock --pre[/yellow]",
        "[yellow]pipenv graph[/yellow]",
        "[yellow]pipenv check[/yellow]",
        "[yellow]pipenv install -e .[/yellow]",
        "[yellow]pipenv run pip freeze[/yellow]",
    )
    help = help.replace("Commands:", additional_help)
    return help
