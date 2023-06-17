.. _commands:

# Pipenv Commands

The commands reference for pipenv (incomplete)

## install

``$ pipenv install`` is used for installing packages into the pipenv virtual environment
and updating your Pipfile and Pipfile.lock.

Along with the basic installation command, which takes the form:

    $ pipenv install <package_name>

Running the above will install the package `<package_name>` and add it to the default packages section in the `Pipfile.lock`

The user can provide these additional parameters:

    --python=<path/to/python> — Performs the installation in a virtualenv using the provided Python interpreter.
warning: The above commands should only be used when initially creating the environment.

The user can provide these additional parameters:

    --dev — Install both develop and defaul` package categories from Pipfile.
    --categories — Install packages to the category groups specified here.
    --system — Install packages to the system site-packages rather than into your virtualenv.
    --deploy — Verifies the _meta hash of the lock file is up to date with the ``Pipfile``, aborts install if not.
    --ignore-pipfile — Install from the Pipfile.lock and completely ignore Pipfile information.

General Interface Note:
```{note}
    It has been confusing to many users of pipenv that running install will completely relock the lock file.
    Based on feedback in pipenv issue reports, we are considering changing install to only relock when adding or changing a package.
    For now, to install lock file versions (without modification of the lock file) use: pipenv sync
    To modify only specific packages and their subdependencies use: pipenv update <package_name>
```

## sync
``$ pipenv sync`` installs dependencies from the ``Pipfile.lock`` without any alteration to the lockfile.

The user can provide these additional parameters:

    --categories — Install packages from the category groups specified here.

## uninstall

``$ pipenv uninstall`` supports all of the parameters in `pipenv install <#pipenv-install>`_,
as well as two additional options, ``--all`` and ``--all-dev``.

    - ``--all`` — This parameter will purge all files from the virtual environment,
      but leave the Pipfile untouched.

    - ``--all-dev`` — This parameter will remove all of the development packages from
      the virtual environment, and remove them from the Pipfile.


## lock

``$ pipenv lock`` is used to update all dependencies of ``Pipfile.lock`` to their latest resolved versions based on your ``Pipfile`` specification.

## update

``$ pipenv update <package>`` will update the lock of specified dependency and sub-dependencies only and install the updates.


## upgrade

``$ pipenv upgrade <package>`` will update the lock of specified dependency and sub-dependencies only, but does not modify the environment.

## run

``run`` will run a given command from the virtualenv, with any arguments forwarded (e.g. ``$ pipenv run python`` or ``$ pipenv run pip freeze``).

## shell

``shell`` will spawn a shell with the virtualenv activated. This shell can be deactivated by using ``exit``.

## graph
``graph`` will show you a dependency graph of your installed dependencies where each root node is a specifier from the ``Pipfile``.

## check

``check`` checks for security vulnerabilities and asserts that [PEP 508](https://www.python.org/dev/peps/pep-0508/) requirements are being met by the project's lock file or current environment.
