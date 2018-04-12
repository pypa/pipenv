try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib

import dotenv
import six

from .environments import PIPENV_DONT_LOAD_ENV, PIPENV_DOTENV_LOCATION


def load_dot_env(project_directory, preload=None):
    """Loads .env file into sys.environ.
    """
    if PIPENV_DONT_LOAD_ENV:
        return
    if PIPENV_DOTENV_LOCATION:
        dotenv_location = pathlib.Path(PIPENV_DOTENV_LOCATION)
    else:
        # If the project doesn't exist yet, check current directory.
        dotenv_location = str(pathlib.Path(project_directory or '.', '.env'))
    dotenv_path = pathlib.Path(dotenv.find_dotenv(dotenv_location))
    if not dotenv_path.is_file():
        return
    if callable(preload):
        preload()
    with dotenv_path.open() as f:
        stream = six.StringIO(f.read())
    dotenv.load_dotenv(stream, override=True)
