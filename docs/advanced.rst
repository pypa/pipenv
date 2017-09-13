.. _advanced:

Advanced Usage of Pipenv
========================

.. image:: https://farm4.staticflickr.com/3672/33231486560_bff4124c9a_k_d.jpg

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
        "_meta": {
            "hash": {
                "sha256": "08e3181df84d04301c9d435357ec9cf43c4a491d79a1ada682cce8936c492f49"
            },
            "host-environment-markers": {
                "implementation_name": "cpython",
                "implementation_version": "3.6.2",
                "os_name": "posix",
                "platform_machine": "x86_64",
                "platform_python_implementation": "CPython",
                "platform_release": "16.7.0",
                "platform_system": "Darwin",
                "platform_version": "Darwin Kernel Version 16.7.0: Thu Jun 15 17:36:27 PDT 2017; root:xnu-3789.70.16~2/RELEASE_X86_64",
                "python_full_version": "3.6.2",
                "python_version": "3.6",
                "sys_platform": "darwin"
            },
            "pipfile-spec": 2,
            "requires": {},
            "sources": [
                {
                    "url": "https://pypi.python.org/simple",
                    "verify_ssl": true
                }
            ]
        },
        "default": {
            "certifi": {
                "hashes": [
                    "sha256:54a07c09c586b0e4c619f02a5e94e36619da8e2b053e20f594348c0611803704",
                    "sha256:40523d2efb60523e113b44602298f0960e900388cf3bb6043f645cf57ea9e3f5"
                ],
                "version": "==2017.7.27.1"
            },
            "chardet": {
                "hashes": [
                    "sha256:fc323ffcaeaed0e0a02bf4d117757b98aed530d9ed4531e3e15460124c106691",
                    "sha256:84ab92ed1c4d4f16916e05906b6b75a6c0fb5db821cc65e70cbd64a3e2a5eaae"
                ],
                "version": "==3.0.4"
            },
            "idna": {
                "hashes": [
                    "sha256:8c7309c718f94b3a625cb648ace320157ad16ff131ae0af362c9f21b80ef6ec4",
                    "sha256:2c6a5de3089009e3da7c5dde64a141dbc8551d5b7f6cf4ed7c2568d0cc520a8f"
                ],
                "version": "==2.6"
            },
            "requests": {
                "hashes": [
                    "sha256:6a1b267aa90cac58ac3a765d067950e7dbbf75b1da07e895d1f594193a40a38b",
                    "sha256:9c443e7324ba5b85070c4a818ade28bfabedf16ea10206da1132edaa6dda237e"
                ],
                "version": "==2.18.4"
            },
            "urllib3": {
                "hashes": [
                    "sha256:06330f386d6e4b195fbfc736b297f58c5a892e4440e54d294d7004e3a9bbea1b",
                    "sha256:cc44da8e1145637334317feebd728bd869a35285b93cbb4cca2577da7e62db4f"
                ],
                "version": "==1.22"
            }
        },
        "develop": {
            "py": {
                "version": "==1.4.34"
            },
            "pytest": {
                "version": "==3.2.1"
            }
        }
    }


.. _initialization:
☤ Importing from requirements.txt
---------------------------------

If you only have a ``requirements.txt`` file available when running ``pipenv install``,
pipenv will automatically import the contents of this file and create a ``Pipfile`` for you.


.. _specifying_versions:

☤ Specifying Versions of a Package
----------------------------------

To tell pipenv to install a specific version of a library, the usage is simple::

    $ pipenv install requests==2.13.0

This will update your ``Pipfile`` to reflect this requirement, automatically.


☤ Specifying Versions of Python
-------------------------------

To create a new virtualenv, using a specific version of Python you have installed (and
on your ``PATH``), use the ``--python VERSION`` flag, like so:

Use Python 3.6::

   $ pipenv --python 3.6

Use Python 2.7::

    $ pipenv --python 2.7

If you don't specify a Python version, either the ``[requires]`` ``python_version`` will be selected, or
whatever your system's default Python installation is, at time of execution.


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


.. _pragmatic_installation:

☤ Pragmatic Installation of Pipenv
----------------------------------

If you have a working installation of pip, and maintain certain "toolchain" type Python modules as global utilities in your user enviornment, pip `user installs <https://pip.pypa.io/en/stable/user_guide/#user-installs>`_ allow for installation into your home directory. Note that due to interaction between dependencies, you should limit tools installed in this way to basic building blocks for a Python workflow like virtualenv, pipenv, tox, and similar software.

To install::

    $ pip install --user pipenv

For more information see the `user installs documentation <https://pip.pypa.io/en/stable/user_guide/#user-installs>`_, but to add the installed cli tools from a pip user install to your path, add the output of::

    $ python -c "import site; import os; print(os.path.join(site.USER_BASE, 'bin'))"

To upgrade pipenv at any time::

    $ pip install --user --upgrade pipenv

.. _crude_installation:

☤ Crude Installation of Pipenv
------------------------------

If you don't even have pip installed, you can use this crude installation method, which will boostrap your whole system::

    $ curl https://github.com/kennethreitz/pipenv/raw/master/get-pipenv.py | python

Congratulations, you now have pip and Pipenv installed!

.. _environment_management:

☤ Environment Management with Pipenv
------------------------------------

The three primary commands you'll use in managing your pipenv environment are
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

    .. note:: The virtualenv created by Pipenv may be different from what you were expecting.
              Dangerous characters (i.e. ``$`!*@"`` as well as space, line feed, carriage return,
              and tab) are converted to underscores. Additionally, the full path to the current
              folder is encoded into a "slug value" and appended to ensure the virtualenv name
              is unique.

    - ``--dev`` — Install both ``develop`` and ``default`` packages from ``Pipfile.lock``.
    - ``--system`` — Use the system ``pip`` command rather than the one from your virtualenv.
    - ``--lock`` — Generate a new ``Pipfile.lock`` adding the newly installed packages.
    - ``--ignore-pipfile`` — Ignore the ``Pipfile`` and install from the ``Pipfile.lock``.

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

    - ``PIPENV_TIMEOUT`` — Set to an integer for the max number of seconds pipenv will
                            wait for virtualenv creation to complete.  Defaults to 120 seconds.

    - ``PIPENV_IGNORE_VIRTUALENVS`` — Set to disable automatically using an activated virtualenv over
                                      the current project.


Also note that `pip itself supports environment variables <https://pip.pypa.io/en/stable/user_guide/#environment-variables>`_, if you need additional customization.

☤ Custom Virtual Environment Location
-------------------------------------

Pipenv's underlying ``pew`` dependency will automatically honor the ``WORKON_HOME`` environment
variable, if you have it set — so you can tell pipenv to store your virtual environments wherever you want, e.g.::

    export WORKON_HOME=~/.venvs


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
        pipenv install --dev

    test:
        pipenv run py.test tests


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
        pipenv install --dev
        pipenv run py.test tests

    [testenv:flake8-py3]
    passenv=HOME
    basepython = python3.4
    commands=
        {[testenv]deps}
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
By default, the ``Pipfile.lock`` will be generated with a sha256 hash of each downloaded
package. This will allow ``pip`` to guarantee you're installing what you intend to when
on a compromised network, or downloading dependencies from an untrusted PyPI endpoint.

We highly recommend approaching deployments with promoting projects from a development
environment into production. You can use ``pipenv lock`` to compile your dependencies on
your development environment and deploy the compiled ``Pipfile.lock`` to all of your
production environments for reproducible builds.

.. note:

    If you'd like a ``requirements.txt`` output of the lockfile, run ``$ pipenv lock -r``.
    This will include all hashes, however (which is great!). To get a ``requirements.txt``
    without hashes, use ``$ pipenv run pip freeze``.

☤ Shell Completion
------------------

Set ``_PIPENV_COMPLETE`` and then source the output of the program.
For example, with ``fish``, put this in your
``~/.config/fish/completions/pipenv.fish``::

    eval (env _PIPENV_COMPLETE=source-fish pipenv)

Magic shell completions are now enabled!

✨🍰✨
