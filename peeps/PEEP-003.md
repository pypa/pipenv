# Virtual-env folder location

Project maintainer may have different opinion on how their project'v virtualenv should be located.
Some are more confortable with a virtualenv folder within the `.venv` folder at the root folder of their project.

# Current state

Pipenv, as 2018.10.8, has the following behavior:

- by default, the virtualenv folder is created in `~/.local/` folder, inside the user's home
- if a `.venv` folder exists in the projects's folder before the first call to `pipenv install`, this folder will be used to store the virtualenv
- if a `.venv` file exists in the projects's folder, its content will be read and is expected to be the path to the location where to store the virtualenv.

# Proposal

These feature would be exposed to the command line (and in respect of PEEP002, exposed as environment variables as well).

## Default behavior

First call of:
```bash
pipenv install
```
will kep the default behavior of storing in `~/.local`

## Force .venv folder

Add an option `--venv` that would mimick the behavior when a `.venv` folder has been created prior to `pipenv install`.

```bash
pipenv install --venv
# or
pipenv install --dev --venv
```
Would install to a folder name `.venv` in the current directory.

This would be enabled as well if the environment variable `PIPENV_INSTALL_VENV=1` is set.

## Custom location

```bash
pipenv install --venv-dir /path/to/my/custom/venv
```
Would create a .venv file in the current folder and store the custom location of the virtualenv.
If an relative path is given, this is expected to be a path relative to the project root folder (where the Pipfile is stored).

This would be enabled as well with an environment variable: `PIPENV_INSTALL_VENV_DIR=custom/path`.

## Precedence and conflict management

pipenv should just discard any conflicting commands.

For example:

```bash
pipenv install
pipenv install --dev  --venv
```

- the first command would create the virtualenv inside the `~/.local` folder
- the second command should ignore the `--venv` command and display a warning such as `Virtualenv already configured in ..., cannot change its location. Use 'pipenv --rm' first.
