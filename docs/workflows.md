# Pipenv Workflows

Clone / create project repository:

    $ cd myproject

Install from `Pipfile.lock`, if there is one:

    $ pipenv install

Add a package to your project, recalibrating subset of lock file using the Pipfile specifiers:

    $ pipenv install <package>

- Note: This will create a `Pipfile` if one doesn't exist. If one does exist, it will automatically be edited with the new package you provided, the lock file updated and the new dependencies installed.
- `pipenv install` is fully compatible with `pip install` [package specifiers](https://pip.pypa.io/en/stable/user_guide/#installing-packages).
- Additional arguments may be supplied to `pip` by supplying `pipenv` with `--extra-pip-args`.

Update everything (equivalent to `pipenv lock && pipenv sync`):

    $ pipenv update

Update and install just the relevant package and its sub-dependencies:

    $ pipenv update <package>

Update in the Pipfile/lockfile just the relevant package and its sub-dependencies:

    $ pipenv upgrade <package>

Find out what's changed upstream:

    $ pipenv update --outdated

Determine the virtualenv `PATH`:

    $ pipenv --venv

Activate the Pipenv shell:

    $ pipenv shell

- Note: This will spawn a new shell subprocess, which can be deactivated by using `exit`.
