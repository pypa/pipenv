.. _advanced:

Advanced Usage of Pipenv
========================

This document covers some of pipenv's more advanced features.


.. _proper_installation:

☤ Fancy Installation
--------------------

To install pipenv in a fancy way, we recommend using `pipsi <https://github.com/mitsuhiko/pipsi>`_.

Pipsi is a powerful tool which allows you to install Python scripts into isolated virtual environments.

To install pipsi, first run this::

    $ curl https://raw.githubusercontent.com/mitsuhiko/pipsi/master/get-pipsi.py | python

Follow the instructions, you'll have to update your ``PATH``.

Then, simply run::

    $ pipsi install pew
    $ pipsi install pipenv

To upgrade pipenv at any time::

    $ pipsi upgrade pipenv


This will install both ``pipenv`` and ``pew`` (one of our dependencies) in an isolated virtualenv, so it doesn't interfere with the rest of your Python installation!


.. _environment_management:

☤ Environment Management
------------------------

The two primary commands you'll use in managing your pipenv environment are
``$ pipenv install``, ``$ pipenv uninstall``, and ``$ pipenv lock`.

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


.. _pipenv_lock

$ pipenv lock
/////////////

``$ pipenv lock`` is used to create a ``Pipfile.lock``, which declares **all** dependencies (and sub-depdendencies) of your project, their latest available versions, and the current hashes for the downloaded files. This ensures repeatable, and most importantly *deterministic*, builds.


☤ Configuration With Environment Variables
------------------------------------------

``pipenv`` comes with a handful of options that can be enabled via shell environment
variables. To activate them, simply create the variable in your shell and pipenv
will detect it.

    - ``PIPENV_SHELL_COMPAT`` — Toggle from our default ``pipenv shell`` mode to classic.
                                  (Suggested for use with pyenv).

    - ``PIPENV_VENV_IN_PROJECT`` — Toggle for detecting a ``.venv`` in your project directory
                                    and using it over the default environment manager, ``pew``.

    - ``PIPENV_COLORBLIND`` — Disable terminal colors, for some reason.

    - ``PIPENV_NOSPIN`` — Disable terminal spinner, for cleaner logs.

    - ``PIPENV_MAX_DEPTH`` — Set to an integer for the maximum number of directories to
                               search for a Pipfile.

☤ Testing Projects
------------------

While pipenv is still a relatively new project, it's already being used in
projects like `Requests`_. Specifically for transitioning to the new Pipfile
format and running the test suite.

We've currently tested deployments with both `Travis-CI`_ and `tox`_ with success.

.. note:: It's highly recommended to run ``pipenv lock`` before installing on a
          CI platform, due to possible hash conflicts between system binaries.


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
        pipenv lock
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
