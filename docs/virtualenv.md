# virtualenv

## Custom Virtual Environment Location

Pipenv automatically honors the `WORKON_HOME` environment variable, if it
is set, so you can tell pipenv to store your virtual environments
wherever you want, e.g.:

    export WORKON_HOME=~/.venvs

In addition, you can also have Pipenv stick the virtualenv in `project/.venv` by setting the `PIPENV_VENV_IN_PROJECT` environment variable.

## Virtual Environment Name

The virtualenv name created by Pipenv may be different from what you were expecting.
Dangerous characters (i.e. `` $!*@"` ``, as well as space, line feed, carriage return,
and tab) are converted to underscores. Additionally, the full path to the current
folder is encoded into a "slug value" and appended to ensure the virtualenv name
is unique.

Pipenv supports a arbitrary custom name for the virtual environment set at `PIPENV_CUSTOM_VENV_NAME`.

The logical place to specify this would be in a user's `.env` file in the root of the project, which gets loaded by pipenv when it is invoked.

## Renaming or Moving a project folder managed by pipenv
By default pipenv creates a virtualenv for your project and gives it a name. The default name is how pipenv maps the individual project to the correct virtualenv. Pipenv names the virtualenv with the name of the project’s root directory plus the hash of the full path to the project's root (e.g., `my_project-a3de50`).

If you rename or move the project folder this will change the project path.  Then, pipenv will no longer be able to find your virtualenv and it will make a new virtualenv. This leaves you with the old virtualenv still lying around on you system.  Luckily the fix is simple.
- Run 'pipenv --rm' *before* renaming or moving your project directory
- Then, after renaming or moving the directory run 'pipenv install' to recreate the virtualenv
