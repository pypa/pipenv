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

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true
    name = "pypi"

    [packages]
    requests = "*"


    [dev-packages]
    pytest = "*"


Example Pipfile.lock
////////////////////

::

    {
        "_meta": {
            "hash": {
                "sha256": "8d14434df45e0ef884d6c3f6e8048ba72335637a8631cc44792f52fd20b6f97a"
            },
            "host-environment-markers": {
                "implementation_name": "cpython",
                "implementation_version": "3.6.1",
                "os_name": "posix",
                "platform_machine": "x86_64",
                "platform_python_implementation": "CPython",
                "platform_release": "16.7.0",
                "platform_system": "Darwin",
                "platform_version": "Darwin Kernel Version 16.7.0: Thu Jun 15 17:36:27 PDT 2017; root:xnu-3789.70.16~2/RELEASE_X86_64",
                "python_full_version": "3.6.1",
                "python_version": "3.6",
                "sys_platform": "darwin"
            },
            "pipfile-spec": 5,
            "requires": {},
            "sources": [
                {
                    "name": "pypi",
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
                "hashes": [
                    "sha256:2ccb79b01769d99115aa600d7eed99f524bf752bba8f041dc1c184853514655a",
                    "sha256:0f2d585d22050e90c7d293b6451c83db097df77871974d90efd5a30dc12fcde3"
                ],
                "version": "==1.4.34"
            },
            "pytest": {
                "hashes": [
                    "sha256:b84f554f8ddc23add65c411bf112b2d88e2489fd45f753b1cae5936358bdf314",
                    "sha256:f46e49e0340a532764991c498244a60e3a37d7424a532b3ff1a6a7653f1a403a"
                ],
                "version": "==3.2.2"
            }
        }
    }


.. _initialization:
☤ Importing from requirements.txt
---------------------------------

If you only have a ``requirements.txt`` file available when running ``pipenv install``,
pipenv will automatically import the contents of this file and create a ``Pipfile`` for you.

You can also specify ``$ pipenv install -r path/to/requirements.txt`` to import a requirements file.

Note, that when importing a requirements file, they often have version numbers pinned, which you likely won't want
in your ``Pipfile``, so you'll have to manually update your ``Pipfile`` afterwards to reflect this.


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

When given a Python version, like this, Pipenv will automatically scan your system for a Python that matches that given version.

If a ``Pipfile`` hasn't been created yet, one will be created for you, that looks like this::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true

    [dev-packages]

    [packages]

    [requires]
    python_version = "3.6"

Note the inclusion of ``[requires] python_version = "3.6"``. This specifies that your application requires this version
of Python, and will be used automatically when running ``pipenv install`` against this ``Pipfile`` in the future
(e.g. on other machines). If this is not true, feel free to simply remove this section.

If you don't specify a Python version on the command–line, either the ``[requires]`` ``python_full_version`` or ``python_version`` will be selected
automatically, falling back to whatever your system's default ``python`` installation is, at time of execution.

☤ Specifying Package Indexes
----------------------------

If you'd like a specific package to be installed with a specific package index, you can do the following::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true
    name = "pypi"

    [[source]]
    url = "http://pypi.home.kennethreitz.org/simple"
    verify_ssl = false
    name = "home"

    [dev-packages]

    [packages]
    requests = {version="*", index="home"}
    maya = {version="*", index="pypi"}
    records = "*"

Very fancy.

☤ Specifying Basically Anything
-------------------------------

If you'd like to specify that a specific package only be installed on certain systems,
you can use `PEP 508 specifiers <https://www.python.org/dev/peps/pep-0508/>`_ to accomplish this.

Here's an example ``Pipfile``, which will only install ``pywinusb`` on Windows systems:

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true
    name = "pypi"

    [packages]
    requests = "*"
    pywinusb = {version = "*", os_name = "== 'windows'"}

Voilà!


☤ Detection of Security Vulnerabilities
---------------------------------------

Pipenv includes the `safety <https://github.com/pyupio/safety>`_ package, and will use it to scan your dependency graph
for known security vulnerabilities!

Example::

    $ cat Pipfile
    [packages]
    django = "==1.10.1"

    $ pipenv check
    Checking PEP 508 requirements…
    Passed!
    Checking installed package safety…

    33075: django >=1.10,<1.10.3 resolved (1.10.1 installed)!
    Django before 1.8.x before 1.8.16, 1.9.x before 1.9.11, and 1.10.x before 1.10.3, when settings.DEBUG is True, allow remote attackers to conduct DNS rebinding attacks by leveraging failure to validate the HTTP Host header against settings.ALLOWED_HOSTS.

    33076: django >=1.10,<1.10.3 resolved (1.10.1 installed)!
    Django 1.8.x before 1.8.16, 1.9.x before 1.9.11, and 1.10.x before 1.10.3 use a hardcoded password for a temporary database user created when running tests with an Oracle database, which makes it easier for remote attackers to obtain access to the database server by leveraging failure to manually specify a password in the database settings TEST dictionary.

    33300: django >=1.10,<1.10.7 resolved (1.10.1 installed)!
    CVE-2017-7233: Open redirect and possible XSS attack via user-supplied numeric redirect URLs
    ============================================================================================

    Django relies on user input in some cases  (e.g.
    :func:`django.contrib.auth.views.login` and :doc:`i18n </topics/i18n/index>`)
    to redirect the user to an "on success" URL. The security check for these
    redirects (namely ``django.utils.http.is_safe_url()``) considered some numeric
    URLs (e.g. ``http:999999999``) "safe" when they shouldn't be.

    Also, if a developer relies on ``is_safe_url()`` to provide safe redirect
    targets and puts such a URL into a link, they could suffer from an XSS attack.

    CVE-2017-7234: Open redirect vulnerability in ``django.views.static.serve()``
    =============================================================================

    A maliciously crafted URL to a Django site using the
    :func:`~django.views.static.serve` view could redirect to any other domain. The
    view no longer does any redirects as they don't provide any known, useful
    functionality.

    Note, however, that this view has always carried a warning that it is not
    hardened for production use and should be used only as a development aid.

✨🍰✨

☤ Automatic Python Installation
-------------------------------

If you have `pyenv <https://github.com/pyenv/pyenv#simple-python-version-management-pyenv>`_ installed and configured, Pipenv will automatically ask you if you want to install a required version of Python if you don't already have it available.

This is a very fancy feature, and we're very proud of it::

    $ cat Pipfile
    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true

    [dev-packages]

    [packages]
    requests = "*"

    [requires]
    python_version = "3.6"

    $ pipenv install
    Warning: Python 3.6 was not found on your system…
    Would you like us to install latest CPython 3.6 with pyenv? [Y/n]: y
    Installing CPython 3.6.2 with pyenv (this may take a few minutes)…
    ...
    Making Python installation global…
    Creating a virtualenv for this project…
    Using /Users/kennethreitz/.pyenv/shims/python3 to create virtualenv…
    ...
    No package provided, installing all dependencies.
    ...
    Installing dependencies from Pipfile.lock…
    🐍   ❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒ 5/5 — 00:00:03
    To activate this project's virtualenv, run the following:
     $ pipenv shell

Pipenv automatically honors both the ``python_full_version`` and ``python_version`` `PEP 508 <https://www.python.org/dev/peps/pep-0508/>`_ specifiers.

💫✨🍰✨💫

☤ Automatic Loading of ``.env``
-------------------------------

If a ``.env`` file is present in your project, ``$ pipenv shell`` and ``$ pipenv run`` will automatically load it, for you::

    $ cat .env
    HELLO=WORLD⏎

    $ pipenv run python
    Loading .env environment variables…
    Python 2.7.13 (default, Jul 18 2017, 09:17:00)
    [GCC 4.2.1 Compatible Apple LLVM 8.1.0 (clang-802.0.42)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    >>> import os
    >>> os.environ['HELLO']
    'WORLD'

This is very useful for keeping production credentials out of your codebase.
We do not recommend comitting ``.env`` files into source control!

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

    $ curl https://raw.githubusercontent.com/kennethreitz/pipenv/master/get-pipenv.py | python

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
    - ``--ignore-pipfile`` — Ignore the ``Pipfile`` and install from the ``Pipfile.lock``.
    - ``--skip-lock`` — Ignore the ``Pipfile.lock`` and install from the ``Pipfile``. In addition, do not write out a ``Pipfile.lock`` reflecting changes to the ``Pipfile``.

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

``$ pipenv lock`` is used to create a ``Pipfile.lock``, which declares **all** dependencies (and sub-dependencies) of your project, their latest available versions, and the current hashes for the downloaded files. This ensures repeatable, and most importantly *deterministic*, builds.

☤ About Shell Configuration
---------------------------

Shells are typically misconfigured for subshell use, so ``$ pipenv shell`` may produce unexpected results. If this is the case, try ``$ pipenv shell -c``, which uses "compatibility mode", and will attempt to spawn a subshell despite misconfiguration.

A proper shell configuration only sets environment variables like ``PATH`` during a login session, not during every subshell spawn (as they are typically configured to do). In fish, this looks like this::

    if status --is-login

        set -gx PATH /usr/local/bin $PATH

    end

You should do this for your shell too, in your ``~/.profile`` or ``~/.bashrc`` or wherever appropriate.


☤ Configuration With Environment Variables
------------------------------------------

``pipenv`` comes with a handful of options that can be enabled via shell environment
variables. To activate them, simply create the variable in your shell and pipenv
will detect it.

    - ``PIPENV_DEFAULT_PYTHON_VERSION`` — Use this version of Python when creating new virtual environments, by default (e.g. ``3.6``).

    - ``PIPENV_SHELL_FANCY`` — Always use fancy mode when invoking ``pipenv shell``.

    - ``PIPENV_VENV_IN_PROJECT`` — If set, use ``.venv`` in your project directory
      instead of the global virtualenv manager ``pew``.

    - ``PIPENV_COLORBLIND`` — Disable terminal colors, for some reason.

    - ``PIPENV_NOSPIN`` — Disable terminal spinner, for cleaner logs. Automatically set in CI environments.

    - ``PIPENV_MAX_DEPTH`` — Set to an integer for the maximum number of directories to resursively
      search for a Pipfile.

    - ``PIPENV_TIMEOUT`` — Set to an integer for the max number of seconds Pipenv will
      wait for virtualenv creation to complete.  Defaults to 120 seconds.

    - ``PIPENV_IGNORE_VIRTUALENVS`` — Set to disable automatically using an activated virtualenv over
      the current project's own virtual environment.


Also note that `pip itself supports environment variables <https://pip.pypa.io/en/stable/user_guide/#environment-variables>`_, if you need additional customization.


☤ A Note about VCS Dependencies
-------------------------------

Pipenv will resolve the sub–depencies of VCS dependencies, but only if they are editable, like so::

    [packages]
    requests = {git = "https://github.com/requests/requests.git", editable=true}

If editable is not true, sub–dependencies will not get resolved.

☤ Custom Virtual Environment Location
-------------------------------------

Pipenv's underlying ``pew`` dependency will automatically honor the ``WORKON_HOME`` environment
variable, if you have it set — so you can tell pipenv to store your virtual environments wherever you want, e.g.::

    export WORKON_HOME=~/.venvs

In addition, you can also have Pipenv stick the virtualenv in ``project/.venv`` by setting the ``PIPENV_VENV_IN_PROJECT`` environment variable.


☤ Testing Projects
------------------

Pipenv is being used in projects like `Requests`_ for declaring development dependencies and running the test suite.

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
By default, the ``Pipfile.lock`` will be generated with the sha256 hashes of each downloaded
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
