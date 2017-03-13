.. _advanced:

Advanced Usage of Pipenv
========================

This document covers some of pipenv's more advanced features.

☤ Example Pipfile & Pipfile.lock
--------------------------------

.. _example_files:

Here is a simple example of a ``Pipfile`` and the resulting ``Pipfile.lock``.

Example Pipfile
///////////////

::

    [dev-packages]
    pytest = "*"

    [packages]
    requests = "*"

Example Pipfile.lock
////////////////////

::

    {
      "default": {
          "requests": {
              "version": "==2.13.0",
              "hash": "sha256:1a720e8862a41aa22e339373b526f508ef0c8988baf48b84d3fc891a8e237efb"
          }
      },
      "develop": {
          "packaging": {
              "version": "==16.8",
              "hash": "sha256:99276dc6e3a7851f32027a68f1095cd3f77c148091b092ea867a351811cfe388"
          },
          "pytest": {
              "version": "==3.0.6",
              "hash": "sha256:da0ab50c7eec0683bc24f1c1137db1f4111752054ecdad63125e7ec71316b813"
          },
          "setuptools": {
              "version": "==34.1.0",
              "hash": "sha256:edd9d39782fe38b9c533002b2e6fdf06498793cbd29266accdcc519431d4b7ba"
          },
          "pyparsing": {
              "version": "==2.1.10",
              "hash": "sha256:67101d7acee692962f33dd30b5dce079ff532dd9aa99ff48d52a3dad51d2fe84"
          },
          "py": {
              "version": "==1.4.32",
              "hash": "sha256:2d4bba2e25fff58140e6bdce1e485e89bb59776adbe01d490baa6b1f37a3dd6b"
          },
          "six": {
              "version": "==1.10.0",
              "hash": "sha256:0ff78c403d9bccf5a425a6d31a12aa6b47f1c21ca4dc2573a7e2f32a97335eb1"
          },
          "appdirs": {
              "version": "==1.4.0",
              "hash": "sha256:85e58578db8f29538f3109c11250c2a5514a2fcdc9890d9b2fe777eb55517736"
          }
      },
      "_meta": {
          "sources": [
              {
                  "url": "https://pypi.python.org/simple",
                  "verify_ssl": true
              }
          ],
          "requires": {},
          "hash": {
              "sha256": "08e3181df84d04301c9d435357ec9cf43c4a491d79a1ada682cce8936c492f49"
          }
      }
  }



.. _proper_installation:

☤ Fancy Installation of Pipenv
------------------------------

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

☤ Environment Management with Pipenv
------------------------------------

The two primary commands you'll use in managing your pipenv environment are
``$ pipenv install``, ``$ pipenv uninstall``, and ``$ pipenv lock``.

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
    passenv=HOME
    deps = pipenv
    commands=
        pipenv lock
        pipenv install --dev
        pipenv run py.test tests

    [testenv:flake8-py3]
    passenv=HOME
    basepython = python3.4
    commands=
        {[testenv]deps}
        pipenv lock
        pipenv install --dev
        pipenv run flake8 --version
        pipenv run flake8 setup.py docs project test

.. note:: With Pipenv's default configuration, you'll need to use tox's ``passenv`` parameter
          to pass your shell's ``HOME`` variable.

.. _Requests: https://github.com/kennethreitz/requests
.. _tox: https://tox.readthedocs.io/en/latest/
.. _Travis-CI: https://travis-ci.org/

☤ Pipfile.lock Security Features
--------------------------------

``Pipfile.lock`` takes advantage of some great new security improvements in ``pip``.
By default, the ``Pipfile.lock`` will be generated with a sha256 hash of the downloaded
package. This will allow pip to guarantee you're installing what you intend to when on a
compromised network, or downloading dependencies from an untrusted PyPI endpoint.

We highly recommend approaching deployments with a development->production approach. You
can use ``pipenv lock`` to compile your dependencies on your development environment and
deploy the compiled Pipfile.lock to all of your production environments for reproducible
builds.

.. note:: Due to different hashes being generated between wheels on different systems, you
          will find hashes don't work cross-platform or between Python versions.
          To solve this, you may either compile the lock file on your target system, or use
          the less secure ``pipenv install --ignore-hashes``. If you wish to produce a
          Pipfile.lock without hashes, you may also use ``pipenv lock --no-hashes``.

☤ Shell Completion
------------------

Set ``_PIPENV_COMPLETE`` and then source the output of the program.
For example, with ``fish``, put this in your
``~/.config/fish/completions/pipenv.fish``::

    eval (env _PIPENV_COMPLETE=source-fish pipenv)

Magic shell completions are now enabled!

✨🍰✨
