PipEnv: Pip for Humans™
=======================

Experimental work in progress.

- automatically adds things to pipfile when you install them
- automatically creates a pipfile
- automatically creates a virtualenv

::

    $ pipenv
    Usage: pipenv.py [OPTIONS] COMMAND [ARGS]...

    Options:
      --version  Show the version and exit.
      --help     Show this message and exit.

    Commands:
      freeze
      install
      prepare
      uninstall
      where
      py

    $ pipenv where
    Pipfile found at /Users/kennethreitz/repos/kr/pip2/Pipfile. Considering this to be the project home.

    $ pipenv where --virtualenv
    Virtualenv location: /Users/kennethreitz/repos/kr/pip2/.venv

    $ pipenv prepare
    Creating a virtualenv for this project...
    ...
    Virtualenv location: /Users/kennethreitz/repos/kr/pip2/.venv
    Installing dependencies from Pipfile.freeze...
    Installing crayons...
    ...


    $ python pipenv.py install requests --dev
    Installing requests...
    ...
    Adding requests to Pipfile...
    # Generating Pipfile.lock


    $ pipenv freeze
    Generating requirements.txt from Pipfile.lock
