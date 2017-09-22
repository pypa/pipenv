Pipenv: Sacred Marriage of Pipfile, Pip, & Virtualenv
=====================================================

.. image:: https://img.shields.io/pypi/v/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/l/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/pyversions/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://travis-ci.org/kennethreitz/pipenv.svg?branch=master
    :target: https://travis-ci.org/kennethreitz/pipenv

.. image:: https://img.shields.io/appveyor/ci/kennethreitz/pipenv.svg
    :target: https://ci.appveyor.com/project/kennethreitz/pipenv/branch/master

.. image:: https://img.shields.io/badge/Say%20Thanks-!-1EAEDB.svg
    :target: https://saythanks.io/to/kennethreitz

---------------

**Pipenv** — the officially recommended Python packaging tool from `Python.org <https://packaging.python.org/new-tutorials/installing-and-using-packages/>`_, free (as in freedom).

Pipenv harnesses `Pipfile <https://github.com/pypa/pipfile>`_, `Pip <https://github.com/pypa/pip>`_, and `Virtualenv <https://github.com/pypa/virtualenv>`_ together in unison to create a single, high-quality tool that is optimized for workflow efficiency and best practices. *Windows is a first–class citizen, in our world.*

Pipenv automatically creates and manages the virtualenvs of your projects, as well as adds/removes packages from your ``Pipfile`` as you install/uninstall packages. The ``lock`` command generates a lockfile (``Pipfile.lock``).

.. image:: http://media.kennethreitz.com.s3.amazonaws.com/pipenv.gif

The problems that Pipenv seeks to solve are multi-faceted:

- You no longer need to use ``pip`` and ``virtualenv`` separately. They work together.
- Managing a ``requirements.txt`` file `can be problematic <https://www.kennethreitz.org/essays/a-better-pip-workflow>`_, so Pipenv uses the upcoming ``Pipfile`` and ``Pipfile.lock`` instead, which is superior for basic use cases.
- Hashes are used everywhere, always. Security. Automatically expose security vulnerabilities.
- Give you insight into your dependency graph (e.g. ``$ pipenv graph``).
- Streamline development workflow by loading ``.env`` files.

Installation
------------

::

    $ pip install pipenv

✨🍰✨

☤ User Testimonials
-------------------

**Jannis Leidel**, former pip maintainer—
    *Pipenv is the porcelain I always wanted to build for pip. It fits my brain and mostly replaces virtualenvwrapper and manual pip calls for me. Use it.*

**Jhon Crypt**—
    *Pipenv is the best thing since pip, thank you!*

**Isaac Sanders**—
    *Pipenv is literally the best thing about my day today. Thanks, Kenneth!*



☤ Features
----------

- Enables truly *deterministic builds*, while easily specifying *only what you want*.
- Generates and checks file hashes for locked dependencies.
- Automatically install required Pythons, if ``pyenv`` is available.
- Automatically finds your project home, recursively, by looking for a ``Pipfile``.
- Automatically generates a ``Pipfile``, if one doesn't exist.
- Automatically creates a virtualenv in a standard location.
- Automatically adds/removes packages to a ``Pipfile`` when they are un/installed.
- Automatically loads ``.env`` files, if they exist.

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
- ``graph`` will print a pretty graph of all your installed dependencies.

Shell Completion
////////////////

Set ``_PIPENV_COMPLETE`` and then source the output of the program. For example, with fish, put this
in your ``~/.config/fish/completions/pipenv.fish``::

    eval (env _PIPENV_COMPLETE=source-fish pipenv)

Magic shell completions are now enabled! There is also a `fish plugin <https://github.com/fisherman/pipenv>`_, which will automatically activate your subshells for you!

Fish is the best shell. You should use it.

☤ Usage
-------

::

    $ pipenv
    Usage: pipenv [OPTIONS] COMMAND [ARGS]...

    Options:
      --update         Update Pipenv & pip to latest.
      --where          Output project home information.
      --venv           Output virtualenv information.
      --py             Output Python interpreter information.
      --rm             Remove the virtualenv.
      --bare           Minimal output.
      --three / --two  Use Python 3/2 when creating virtualenv.
      --python TEXT    Specify which version of Python virtualenv should use.
      -h, --help       Show this message then exit.
      -j, --jumbotron  An easter egg, effectively.
      --version        Show the version and exit.


    Usage Examples:
       Create a new project using Python 3:
       $ pipenv --three

       Create a new project using Python 3.6, specifically:
       $ pipenv --python 3.6

       Install all dependencies for a project (including dev):
       $ pipenv install --dev

       Create a lockfile:
       $ pipenv lock

       Show a graph of your installed dependencies:
       $ pipenv graph

    Commands:
      check      Checks for security vulnerabilities and...
      graph      Displays currently–installed dependency graph...
      install    Installs provided packages and adds them to...
      lock       Generates Pipfile.lock.
      run        Spawns a command installed into the...
      shell      Spawns a shell within the virtualenv.
      uninstall  Un-installs a provided package and removes it...
      update     Uninstalls all packages, and re-installs...


Locate the project::

    $ pipenv --where
    /Users/kennethreitz/Library/Mobile Documents/com~apple~CloudDocs/repos/kr/pipenv/test

Locate the virtualenv::

   $ pipenv --venv
   /Users/kennethreitz/.local/share/virtualenvs/test-Skyy4vre
   
Locate the Python interpreter::

    $ pipenv --py
    /Users/kennethreitz/.local/share/virtualenvs/test-Skyy4vre/bin/python
    
Install packages::

    $ pipenv install
    Creating a virtualenv for this project...
    ...
    No package provided, installing all dependencies.
    Virtualenv location: /Users/kennethreitz/.local/share/virtualenvs/test-EJkjoYts
    Installing dependencies from Pipfile.lock...
    ...

    To activate this project's virtualenv, run the following:
    $ pipenv shell

Install a dev dependency::

    $ pipenv install pytest --dev
    Installing pytest...
    ...
    Adding pytest to Pipfile's [dev-packages]...

Show a dependency graph::

    $ pipenv graph
    requests==2.18.4
      - certifi [required: >=2017.4.17, installed: 2017.7.27.1]
      - chardet [required: >=3.0.2,<3.1.0, installed: 3.0.4]
      - idna [required: >=2.5,<2.7, installed: 2.6]
      - urllib3 [required: <1.23,>=1.21.1, installed: 1.22]

Generate a lockfile::

    $ pipenv lock
    Assuring all dependencies from Pipfile are installed...
    Locking [dev-packages] dependencies...
    Locking [packages] dependencies...
    Note: your project now has only default [packages] installed.
    To install [dev-packages], run: $ pipenv install --dev

Install all dev dependencies::

    $ pipenv install --dev
    Pipfile found at /Users/kennethreitz/repos/kr/pip2/test/Pipfile. Considering this to be the project home.
    Pipfile.lock out of date, updating...
    Assuring all dependencies from Pipfile are installed...
    Locking [dev-packages] dependencies...
    Locking [packages] dependencies...

Uninstall everything::

    $ pipenv uninstall --all
    No package provided, un-installing all dependencies.
    Found 25 installed package(s), purging...
    ...
    Environment now purged and fresh!

Use the shell::

    $ pipenv shell
    Loading .env environment variables…
    Launching subshell in virtual environment. Type 'exit' or 'Ctrl+D' to return.
    $ ▯

☤ Documentation
---------------

Documentation resides over at `pipenv.org <http://pipenv.org/>`_.
