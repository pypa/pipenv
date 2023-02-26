.. _commands:

# Pipenv Commands

The commands reference for pipenv (incomplete)

## pipenv install

``$ pipenv install`` is used for installing packages into the pipenv virtual environment
and updating your Pipfile.

Along with the basic install command, which takes the form::

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

.. _pipenv_uninstall:

## pipenv uninstall

``$ pipenv uninstall`` supports all of the parameters in `pipenv install <#pipenv-install>`_,
as well as two additional options, ``--all`` and ``--all-dev``.

    - ``--all`` — This parameter will purge all files from the virtual environment,
      but leave the Pipfile untouched.

    - ``--all-dev`` — This parameter will remove all of the development packages from
      the virtual environment, and remove them from the Pipfile.


.. _pipenv_lock:

## pipenv lock

``$ pipenv lock`` is used to create a ``Pipfile.lock``, which declares **all** dependencies (and sub-dependencies) of your project, their latest available versions, and the current hashes for the downloaded files. This ensures repeatable, and most importantly *deterministic*, builds.


