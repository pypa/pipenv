.. _advanced:

Advanced Usage of Pipenv
========================

This document covers some of pipenv's more advanced features.


.. _proper_installation:

☤ Fancy Installation
--------------------

To install pipenv in a fancy way, we recommend using `pipsi <https://github.com/mitsuhiko/pipsi>`_.

To install pipsi, first run this::

    $ curl https://raw.githubusercontent.com/mitsuhiko/pipsi/master/get-pipsi.py | python

Then, simply run::

    $ pipsi install pew

    $ pipsi install pipenv

To upgrade pipenv at any time::

    $ pipsi upgrade pipenv


Enjoy!


.. _environment_management:

☤ Environment Management
------------------------

The two primary commands you'll use in managing your pipenv environment are
``$ pipenv install`` and ``$ pipenv uninstall``.

.. _pipenv_install

$ pipenv install
////////////////

``$ pipenv install`` is used for installing packages into the pipenv virtual environment
and updating your Pipfile.

Along with the basic install command, which takes the form::

    $ pipenv install [package names]

The user can provide these additional parameters:

    - ``--two`` — Performs the installation in a virtualenv using the system ``python2`` link.
    - ``--three`` — Performs the installation in a virtualenv using the system ``python3`` link.
    - ``--python`` — Performs the installation in a virtualenv using the provided Python intepreter.

    .. warning:: None of the above commands should be used together. They are also
                 **destructive** and will delete your current virtualenv before replacing
                 it with an appropriately versioned one.

    - ``--dev`` — Install both ``develop`` and ``default`` packages from ``Pipfile.lock``.
    - ``--system`` — Use the system ``pip`` command rather than the one from your virtualenv.
    - ``--lock`` — Generate a new ``Pipfile.lock`` adding the newly installed packages.

.. _pipenv_uninstall

$ pipenv uninstall
//////////////////

``$ pipenv uninstall`` supports all of the parameters in `pipenv install <#pipenv-install>`_,
as well as one additonal, ``--all``.

    - ``--all`` — This parameter will purge all files from the virtual environment,
                  but leave the Pipfile untouched.

☤ Configuration With Environment Variables
------------------------------------------

``pipenv`` comes with a handful of options that can be enabled via shell environment
variables. To activate them, simply create the variable in your shell and pipenv
will detect it.

    - ``PIPENV_SHELL_COMPAT`` — Toggle from our default ``pipenv shell`` mode to classic.
                                  (Suggested for use with pyenv)

    - ``PIPENV_VENV_IN_PROJECT`` — Toggle for detecting a .venv in your directory and using
                                     the local virtual environment over the default, ``pew``.

    - ``PIPENV_COLORBLIND`` — Disable terminal colors.

    - ``PIPENV_MAX_DEPTH`` — Set to an integer for the maximum number of directories to
                               search for a Pipfile.

☤ Testing Projects
------------------

While pipenv is still a relatively new project, it's already being used in
projects like `Requests`_. Specifically for transitioning to the new Pipfile
format and running the test suite.

We've currently tested deployments with both `Travis-CI`_ and `tox`_ with success.


Travis CI
/////////

An example Travis CI setup can be found in `Requests`_. The project uses a Makefile to
define common functions such as its ``init`` and ``tests`` commands. Here is
a stripped down example ``.travis.yml``::

    language: python
    python:
        - "2.6"
        - "2.7"
        - "3.3"
        - "3.4"
        - "3.5"
        - "3.6"
        - "3.7dev"

    # command to install dependencies
    install: "make"

    # command to run tests
    script:
        - make test

and the corresponding Makefile::

    init:
        pip install pipenv
        pipenv lock
        pipenv install --dev

    test:
        pipenv run py.test tests

``$ pipenv lock`` needs to be run here, because Python 2 will generate a different lockfile than Python 3.

Tox Automation Project
//////////////////////

Alternatively, you can configure a ``tox.ini`` like the one below for both local
and external testing::

    [tox]
    envlist = flake8-py3, py26, py27, py33, py34, py35, py36, pypy

    [testenv]
    deps = pipenv
    commands=
        pipenv install --dev
        pipenv run py.test tests

    [testenv:flake8-py3]
    basepython = python3.4
    commands=
        {[testenv]deps}
        pipenv lock
        pipenv install --dev
        pipenv run flake8 --version
        pipenv run flake8 setup.py docs project test


.. _Requests: https://github.com/kennethreitz/requests
.. _tox: https://tox.readthedocs.io/en/latest/
.. _Travis-CI: https://travis-ci.org/
