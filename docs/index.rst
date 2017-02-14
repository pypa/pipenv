.. pipenv documentation master file, created by
   sphinx-quickstart on Mon Jan 30 13:28:36 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Pipenv: Sacred Marriage of Pipfile, Pip, & Virtualenv
=====================================================

.. image:: https://img.shields.io/pypi/v/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/l/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/wheel/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/pyversions/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://travis-ci.org/kennethreitz/pipenv.svg?branch=master
    :target: https://travis-ci.org/kennethreitz/pipenv

.. image:: https://img.shields.io/badge/Say%20Thanks!-🦉-1EAEDB.svg
    :target: https://saythanks.io/to/kennethreitz

---------------

**Pipenv** is an experimental project that aims to bring the best of all packaging worlds to the Python world. It harnesses `Pipfile <https://github.com/pypa/pipfile>`_, `pip <https://github.com/pypa/pip>`_, and `virtualenv <https://github.com/pypa/virtualenv>`_ into one single toolchain. It features very pretty terminal colors.

It automatically creates and manages a virtualenv for your projects, as well as adds/removes packages from your ``Pipfile`` as you install/uninstall packages. The ``lock`` command generates a lockfile (``Pipfile.lock``).

.. image:: http://media.kennethreitz.com.s3.amazonaws.com/pipenv.gif

User Testimonials
-----------------

**Jannis Leidel**, former pip maintainer—
    *Pipenv is the porcelain I always wanted built for pip. It fits my brain and mostly replaces virtualenvwrapper and manual pip calls for me. Use it.*

**Jhon Crypt**—
    *pipenv is the best thing since pip, thank you!*

**Isaac Sanders**—
    *pipenv is literally the best thing about my day today. Thanks, Kenneth!*

☤ Pipenv Features
-----------------

- Enables truly *deterministic builds*, while easily specifying *what you want*.
- **Automatically generates and checks file hashes for locked dependencies.**
- Automatically finds your project home, recursively, by looking for a ``Pipfile``.
- Automatically generates a ``Pipfile``, if one doesn't exist.
- Automatically generates a ``Pipfile.lock``, if one doesn't exist.
- Automatically creates a virtualenv in a standard location.
- Automatically adds packages to a Pipfile when they are installed.
- Automatically removes packages from a Pipfile when they are un-installed.
- Also automatically updates pip.

The main commands are ``install``, ``uninstall``, and ``lock``, which generates a ``Pipfile.lock``. These are intended to replace ``$ pip install`` usage, as well as manual virtualenv management (to activate a virtualenv, run ``$ pipenv shell``).

Basic Concepts
//////////////

- A virtualenv will automatically be created, when one doesn't exist.
- When no parameters are passed to ``install``, all packages ``[packages]`` specified will be installed.
- To initialize a Python 3 virtual environment, run ``$ pipenv --three``.
- To initialize a Python 2 virtual environment, run ``$ pipenv --two``.
- Otherwise, whatever virtualenv defaults to will be the default.



Other Commands
//////////////

- ``shell`` will spawn a shell with the virtualenv activated.
- ``run`` will run a given command from the virtualenv, with any arguments forwarded (e.g. ``$ pipenv run python``).
- ``check`` asserts that PEP 508 requirements are being met by the current environment.

Caveats
///////

- Windows is not currently supported.

☤ Pipenv Usage
--------------

::

    $ pipenv
    Usage: pipenv [OPTIONS] COMMAND [ARGS]...

    Options:
      --where          Output project home information.
      --bare           Minimal output.
      --three / --two  Use Python 3/2 when creating virtualenv.
      --python TEXT    Specify which version of Python virtualenv should use.
      -h, --help       Show this message then exit.
      --version        Show the version and exit.


    Usage Examples:
       Create a new project using Python 3:
       $ pipenv --three

       Install all dependencies for a project (including dev):
       $ pipenv install --dev

       Create a lockfile:
       $ pipenv lock

    Commands:
      check      Checks PEP 508 markers provided in Pipfile.
      install    Installs provided packages and adds them to...
      lock       Generates Pipfile.lock.
      run        Spawns a command installed into the...
      shell      Spawns a shell within the virtualenv.
      uninstall  Un-installs a provided package and removes it...
      update     Updates pip to latest version, uninstalls all....

::

    $ pipenv --where
    Pipfile found at /Users/kennethreitz/repos/kr/pip2/test/Pipfile. Considering this to be the project home.

::

    $ pipenv install
    Creating a virtualenv for this project...
    ...
    No package provided, installing all dependencies.
    Virtualenv location: /Users/kennethreitz/repos/kr/pip2/test/.venv
    Installing dependencies from Pipfile.lock...
    ...

    To activate this project's virtualenv, run the following:
    $ pipenv shell


Further Documentation Guides
----------------------------

.. toctree::
   :maxdepth: 2

   advanced


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
