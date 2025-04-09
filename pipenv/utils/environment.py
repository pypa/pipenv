import os
from pathlib import Path

from pipenv import environments
from pipenv.utils import err
from pipenv.vendor import dotenv


def load_dot_env(project, as_dict=False, quiet=False):
    """Loads .env file into sys.environ."""
    if not project.s.PIPENV_DONT_LOAD_ENV:
        # If the project doesn't exist yet, check current directory for a .env file
        project_directory = project.project_directory or "."

        # Determine the .env file path
        if project.s.PIPENV_DOTENV_LOCATION:
            dotenv_file = Path(project.s.PIPENV_DOTENV_LOCATION)
        else:
            dotenv_file = Path(project_directory) / ".env"

        if not dotenv_file.is_file() and project.s.PIPENV_DOTENV_LOCATION:
            err.print(
                f"[bold][red]WARNING[/red]:"
                f"file PIPENV_DOTENV_LOCATION={project.s.PIPENV_DOTENV_LOCATION}"
                "does not exist!"
                "[red]Not loading environment variables.[/red][/bold]"
            )

        if as_dict:
            return dotenv.dotenv_values(str(dotenv_file))
        elif dotenv_file.is_file():
            if not quiet:
                err.print("[bold]Loading .env environment variables...[/bold]")

            dotenv.load_dotenv(str(dotenv_file), override=True)
            project.s = environments.Setting()


def ensure_environment():
    # Skip this on Windows...
    if os.name != "nt" and "LANG" not in os.environ:
        err.print(
            "[red]Warning[/red]: the environment variable [bold]LANG[/bold] "
            "is not set!\nWe recommend setting this in "
            "[green]~/.profile[/green] (or equivalent) for "
            "proper expected behavior."
        )
