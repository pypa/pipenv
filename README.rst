Pipenv: Sacred Marriage of Pipfile, Pip, & Virtualenv
=====================================================

Pipenv is an experimental project that aims to bring the best of all packaging worlds to the Python world. It harnesses `Pipfile <https://github.com/pypa/pipfile>`_, pip, and virtualenv into one single toolchain. It features very pretty terminal colors.

It automatically creates and manages a virtualenv for your projects, as well as adds/removes packages from your ``Pipfile`` as you install/uninstall packages. The ``lock`` command generates a lockfile (``Pipfile.lock``).

☤ Features
----------

- Automatically finds your project home, recursively, by looking for a ``Pipfile``.
- Automatically generates a ``Pipfile``, if one doesn't exist.
- Automatically generates a ``Pipfile.lock``, if one doesn't exist.
- Automatically creates a virtualenv in a standard location (``project/.venv``).
- Automatically adds packages to a Pipfile when they are installed.
- Automatically removes packages from a Pipfile when they are un-installed.
- Also automatically updates pip.

The main commands are ```install``, ``uninstall``, and ``lock``, which generates a ``Pipfile.lock``. These are intended to replace ``$ pip install`` usage, as well as manual virtualenv management.

Basic Concepts
//////////////

- A virtualenv will automatically be created, when one doesn't exist.
- When no parameters are passed to ``install``, all packages specified will be installed.
- When no parameters are passed to ``uninstall``, all packages will be uninstalled.

Other Commands
//////////////

- ``shell`` will spawn a shell with the virtualenv activated.
- ``python`` will run the Python interpreter from the virtualenv, with any arguments forwarded.
- ``where`` will give location information about the current project.
- ``check`` asserts that PEP 508 requirements are being met by the current environment.



☤ Usage
-------

::

    $ pipenv
    Usage: pipenv [OPTIONS] COMMAND [ARGS]...

    Options:
      --version  Show the version and exit.
      --help     Show this message and exit.

    Commands:
      check
      install
      lock
      python
      shell
      uninstall
      update
      where

::

    $ pipenv where
    Pipfile found at /Users/kennethreitz/repos/kr/pip2/test/Pipfile. Considering this to be the project home.

::

    $ pipenv where --venv
    Virtualenv location: /Users/kennethreitz/repos/kr/pip2/test/.venv

::

    $ pipenv init
    Pipfile found at /Users/kennethreitz/repos/kr/pip2/test/Pipfile. Considering this to be the project home.
    Creating a virtualenv for this project...
    ...
    Virtualenv location: /Users/kennethreitz/repos/kr/pip2/test/.venv
    Installing dependencies from Pipfile.lock...
    ...

    To activate this project's virtualenv, run the following:
    $ pipenv shell

::

    $ pipenv install pytest --dev
    Installing pytest...
    ...
    Adding pytest to Pipfile's [dev-packages]...

::

    $ pipenv lock
    Assuring all dependencies from Pipfile are installed...
    Locking [dev-packages] dependencies...
    Locking [packages] dependencies...
    Note: your project now has only default [packages] installed.
    To install [dev-packages], run: $ pipenv init --dev


☤ Installation
--------------

::

    $ pip install pipenv

✨🍰✨
