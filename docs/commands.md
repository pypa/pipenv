.. _commands:

# Pipenv Commands

The commands reference for pipenv (incomplete)

## install

``$ pipenv install`` is used for installing packages into the pipenv virtual environment
and updating your Pipfile.

Along with the basic installation command, which takes the form::

    $ pipenv install [package names]

The user can provide these additional parameters:

    - ``--python`` — Performs the installation in a virtualenv using the provided Python interpreter.

    .. warning:: None of the above commands should be used together. They are also
                 **destructive** and will delete your current virtualenv before replacing
                 it with an appropriately versioned one.

    - ``--dev`` — Install both ``develop`` and ``default`` packages from ``Pipfile``.
    - ``--system`` — Install packages to the system site-packages rather than into your virtualenv.
    - ``--deploy`` — Verifies the _meta hash of the lock file is up to date with the ``Pipfile``, aborts install if not.
    - ``--ignore-pipfile`` — Ignore the ``Pipfile`` and install from the ``Pipfile.lock``.
    - ``--skip-lock`` — Ignore the ``Pipfile.lock`` and install from the ``Pipfile``. In addition, do not write out a ``Pipfile.lock`` reflecting changes to the ``Pipfile``.


## uninstall

``$ pipenv uninstall`` supports all of the parameters in `pipenv install <#pipenv-install>`_,
as well as two additional options, ``--all`` and ``--all-dev``.

    - ``--all`` — This parameter will purge all files from the virtual environment,
      but leave the Pipfile untouched.

    - ``--all-dev`` — This parameter will remove all of the development packages from
      the virtual environment, and remove them from the Pipfile.


## sync
``$ pipenv sync`` installs dependencies from the ``Pipfile.lock`` without any alteration to the lockfile.


## lock

``$ pipenv lock`` is used to update a ``Pipfile.lock``, which declares **all** dependencies of your project, their latest resolved versions based on your ``Pipfile`` specifiers, and the current hashes for the downloaded files. This ensures repeatable and deterministic builds.

## update

``$ pipenv update <package>`` will update the lock of specified dependency and sub-dependencies only and install the updates.


## upgrade

``$ pipenv upgarde <package>`` will update the lock of specified dependency and sub-dependencies only, but does not modify the environment.

## run

``run`` will run a given command from the virtualenv, with any arguments forwarded (e.g. ``$ pipenv run python`` or ``$ pipenv run pip freeze``).

## shell

``shell`` will spawn a shell with the virtualenv activated. This shell can be deactivated by using ``exit``.

## graph
``graph`` will show you a dependency graph of your installed dependencies where each root node is a specifier from the ``Pipfile``.

## check

``check`` checks for security vulnerabilities and asserts that [PEP 508](https://www.python.org/dev/peps/pep-0508/) requirements are being met by the project's lock file or current environment.
