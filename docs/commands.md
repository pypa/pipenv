# Pipenv Commands

The commands reference for pipenv (incomplete)

## install

``$ pipenv install`` is used for installing packages into the pipenv virtual environment
and updating your Pipfile and Pipfile.lock in the case of adding new packages.

Along with the basic installation command, which takes the form:

    $ pipenv install <package_name>

Running the above will install the package `<package_name>` and add it to the default packages section in the `Pipfile` and all of its dependencies to the `Pipfile.lock`.

The user can provide these additional parameters:

    --python=<path/to/python> — Performs the installation in a virtualenv using the provided Python interpreter.
warning: The above commands should only be used when initially creating the environment.

The user can provide these additional parameters:

    --dev — Install both develop and default package categories from Pipfile.
    --categories — Install packages to the category groups specified here.
    --system — Install packages to the system site-packages rather than into your virtualenv.
    --deploy — Verifies the _meta hash of the lock file is up to date with the ``Pipfile``, aborts install if not.
    --ignore-pipfile — Install from the Pipfile.lock completely ignoring Pipfile information.

General Interface Note:
```{note}
    It was confusing to users that prior to pipenv 2024, the install would relock the lock file every time it was run.
    Based on feedback in pipenv issue reports, we changed the install command to only update lock when adding or changing a package.
    If you wish to relock the entire set of Pipfile specifiers, please continue to utilize `pipenv lock`
```

## sync
``$ pipenv sync`` installs dependencies from the ``Pipfile.lock`` without any alteration to the lockfile.

The user can provide these additional parameters:

    --categories — Install packages from the category groups specified here.

## uninstall

``$ pipenv uninstall`` supports all of the parameters in `pipenv install, as well as two additional options,
``--all`` and ``--all-dev``.

    - --all — This parameter will purge all files from the virtual environment,
      but leave the Pipfile untouched.

    - --all-dev — This parameter will remove all of the development packages from
      the virtual environment, and remove them from the Pipfile.


## lock

``$ pipenv lock`` is used to update all dependencies of ``Pipfile.lock`` to their latest resolved versions based on your ``Pipfile`` specification.

## update

``$ pipenv update <package>`` will update the lock of specified dependency and sub-dependencies only and install the updates.


## upgrade

``$ pipenv upgrade <package>`` will update the lock of specified dependency and sub-dependencies only, but does not modify the environment.

## run

``$ pipenv run`` will run a given command from the virtualenv, with any arguments forwarded (e.g. ``$ pipenv run python`` or ``$ pipenv run pip freeze``).

## shell

``$ pipenv shell`` will spawn a shell with the virtualenv activated. This shell can be deactivated by using ``exit``.

## graph
``$ pipenv graph`` will show you a dependency graph of your installed dependencies where each root node is a specifier from the ``Pipfile``.

## check

``$ pipenv check`` checks for security vulnerabilities and asserts that [PEP 508](https://www.python.org/dev/peps/pep-0508/) requirements are being met by the project's lock file or current environment.


## scripts
``$ pipenv scripts`` will list the scripts in the current environment config.
