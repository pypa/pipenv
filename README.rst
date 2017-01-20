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
      prep
      py
      uninstall
      venv
      where
      
    $ pipenv where
    Pipfile found at /Users/kennethreitz/repos/project/Pipfile. Considering this to be the project home.

    $ pipenv where --virtualenv
    Virtualenv location: /Users/kennethreitz/repos/project/.venv
    
    $ pipenv venv --bare
    source /Users/kennethreitz/repos/project/.venv/bin/activate

    $ pipenv prep
    Creating a virtualenv for this project...
    ...
    Virtualenv location: /Users/kennethreitz/repos/project/.venv
    Installing dependencies from Pipfile.freeze...
    Installing crayons...
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
