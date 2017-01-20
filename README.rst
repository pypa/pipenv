Pipenv: Sacred Marriage of Pipfile, Pip, & Virtualenv 
=====================================================

Pipenv is an experimental project that aims to bring the best of all packaging worlds to the Python world. It harnesses `Pipfile <https://github.com/pypa/pipfile>`_, pip, and virtualenv into one single toolchain.

Features
--------

- Automatically generates a Pipfile, if one doesn't exist.
- Automatically generates a Pipfile.lock, if one doesn't exist. 
- Automatically creates a virtualenv in a standard location.
- Automatically adds packages to a Pipfile when they are installed.
- Automatically removes packages from a Pipfile when they are un-installed. 
- Also automatically updates pip.

The main commands are ``init``, which initializes the environment, ``install`` and ``uninstall``, and ``freeze``, which generates a Pipfile.lock. These are intended to replace ``$ pip install`` usage. 

- ``py`` will run the Python interpreter from the virtualenv, with any arguments forwarded.
- ``purge`` will uninstall all packages from the virtualenv.
- ``where`` will give location information about the current project. 
- ``venv`` will give virtutalenv activation information. 

Usage
-----

::

    $ pipenv
    Usage: pipenv.py [OPTIONS] COMMAND [ARGS]...

    Options:
      --version  Show the version and exit.
      --help     Show this message and exit.

    Commands:
      freeze
      install
      init
      py
      purge
      uninstall
      venv
      where
      
    $ pipenv where
    Pipfile found at /Users/kennethreitz/repos/project/Pipfile. Considering this to be the project home.

    $ pipenv where --venv
    Virtualenv location: /Users/kennethreitz/repos/project/.venv
    
    $ pipenv venv --bare
    source /Users/kennethreitz/repos/project/.venv/bin/activate

    $ pipenv init
    Creating a Pipfile for this project...
    Assuring all dependencies from Pipfile are installed...
    Freezing development dependencies...
    Freezing default dependencies.....
    Pipfile found at /Users/kennethreitz/repos/project/Pipfile. Considering this to be the project home.
    Creating a virtualenv for this project...
    ...
    Virtualenv location: /Users/kennethreitz/repos/project/.venv
    Pipfile.freeze not found, creating...
    ...
    
    To activate this project's virtualenv, run the following:
    $ source /Users/kennethreitz/repos/project/.venv/bin/activate


    $ python pipenv.py install requests --dev
    Installing requests...
    ...
    Adding requests to Pipfile...
    # Generating Pipfile.lock


    $ pipenv freeze
    Generating requirements.txt from Pipfile.lock
