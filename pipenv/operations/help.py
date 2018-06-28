from pipenv.patched import crayons


def format_help(help):
    """Formats the help string."""
    help = help.replace('Options:', str(crayons.normal('Options:', bold=True)))
    help = help.replace(
        'Usage: pipenv',
        str('Usage: {0}'.format(crayons.normal('pipenv', bold=True))),
    )
    help = help.replace('  check', str(crayons.red('  check', bold=True)))
    help = help.replace('  clean', str(crayons.red('  clean', bold=True)))
    help = help.replace('  graph', str(crayons.red('  graph', bold=True)))
    help = help.replace(
        '  install', str(crayons.magenta('  install', bold=True))
    )
    help = help.replace('  lock', str(crayons.green('  lock', bold=True)))
    help = help.replace('  open', str(crayons.red('  open', bold=True)))
    help = help.replace('  run', str(crayons.yellow('  run', bold=True)))
    help = help.replace('  shell', str(crayons.yellow('  shell', bold=True)))
    help = help.replace('  sync', str(crayons.green('  sync', bold=True)))
    help = help.replace(
        '  uninstall', str(crayons.magenta('  uninstall', bold=True))
    )
    help = help.replace('  update', str(crayons.green('  update', bold=True)))
    additional_help = """
Usage Examples:
   Create a new project using Python 3.6, specifically:
   $ {1}

   Install all dependencies for a project (including dev):
   $ {2}

   Create a lockfile containing pre-releases:
   $ {6}

   Show a graph of your installed dependencies:
   $ {4}

   Check your installed dependencies for security vulnerabilities:
   $ {7}

   Install a local setup.py into your virtual environment/Pipfile:
   $ {5}

   Use a lower-level pip command:
   $ {8}

Commands:""".format(
        crayons.red('pipenv --three'),
        crayons.red('pipenv --python 3.6'),
        crayons.red('pipenv install --dev'),
        crayons.red('pipenv lock'),
        crayons.red('pipenv graph'),
        crayons.red('pipenv install -e .'),
        crayons.red('pipenv lock --pre'),
        crayons.red('pipenv check'),
        crayons.red('pipenv run pip freeze'),
    )
    help = help.replace('Commands:', additional_help)
    return help
