import os

from pipenv import environments
from pipenv._compat import fix_utf8
from pipenv.vendor import click, dotenv


def load_dot_env(project, as_dict=False, quiet=False):
    """Loads .env file into sys.environ."""
    if not project.s.PIPENV_DONT_LOAD_ENV:
        # If the project doesn't exist yet, check current directory for a .env file
        project_directory = project.project_directory or "."
        dotenv_file = project.s.PIPENV_DOTENV_LOCATION or os.sep.join(
            [project_directory, ".env"]
        )

        if not os.path.isfile(dotenv_file) and project.s.PIPENV_DOTENV_LOCATION:
            click.echo(
                "{}: file {}={} does not exist!!\n{}".format(
                    click.style("Warning", fg="red", bold=True),
                    click.style("PIPENV_DOTENV_LOCATION", bold=True),
                    click.style(project.s.PIPENV_DOTENV_LOCATION, bold=True),
                    click.style(
                        "Not loading environment variables.", fg="red", bold=True
                    ),
                ),
                err=True,
            )
        if as_dict:
            return dotenv.dotenv_values(dotenv_file)
        elif os.path.isfile(dotenv_file):
            if not quiet:
                click.echo(
                    click.style(
                        fix_utf8("Loading .env environment variables..."), bold=True
                    ),
                    err=True,
                )
            dotenv.load_dotenv(dotenv_file, override=True)

            project.s = environments.Setting()
