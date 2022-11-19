Basic Commands and Concepts
///////////////////////////

Pipenv uses a set of commands to manage your Project's dependencies and custom scripts.
It replaces the use of ``Makefile``, direct calls to ``pip`` and ``python -m venv`` or ``virtualenv``.
to create virtual environments and install packages in them.
Pipenv uses two files to do this: ``Pipfile``  and ``Pipfile.lock`` (which will look familiar if you
are used to packages manager like ``yarn`` or ``npm``).

The main commands are:

- ``install`` -

  Will create a virtual env and install dependencies (if it does not exist already)
  The dependencies will be installed inside.

- ``install package==0.2`` -

  Will add the package in version 0.2 to the virtual environment and
  to ``Pipfile`` and ``Pipfile.lock``

- ``uninstall`` - Will remove the dependency

- ``lock`` - Regenarate ``Pipfile.lock`` and updates the dependencies inside it.

These are intended to replace ``$ pip install`` usage, as well as manual virtualenv management.

Other Commands
//////////////

- ``graph`` will show you a dependency graph of your installed dependencies.
- ``shell`` will spawn a shell with the virtualenv activated. This shell can be deactivated by using ``exit``.
- ``run`` will run a given command from the virtualenv, with any arguments forwarded (e.g. ``$ pipenv run python`` or ``$ pipenv run pip freeze``).
- ``check`` checks for security vulnerabilities and asserts that `PEP 508 <https://www.python.org/dev/peps/pep-0508/>`_ requirements are being met by the current environment.
