.. _advanced:

Advanced Usage of Pipenv
========================

.. image:: https://farm4.staticflickr.com/3672/33231486560_bff4124c9a_k_d.jpg

This document covers some of Pipenv's more glorious and advanced features.

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

Here's an example ``Pipfile``, which will only install ``pywinusb`` on Windows systems::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true
    name = "pypi"

    [packages]
    requests = "*"
    pywinusb = {version = "*", os_name = "== 'windows'"}

Voilà!

Here's a more complex example::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true

    [packages]
    unittest2 = {version = ">=1.0,<3.0", markers="python_version < '2.7.9' or (python_version >= '3.0' and python_version < '3.4')"}

Magic. Pure, unadulterated magic.


☤ Deploying System Dependencies
-------------------------------

You can tell Pipenv to install things into its parent system with the ``--system`` flag::

    $ pipenv install --system

This is useful for Docker containers, and deployment infrastructure (e.g. Heroku does this).

Also useful for deployment is the ``--deploy`` flag::

    $ pipenv install --system --deploy

This will fail a build if the ``Pipfile.lock`` is out–of–date, instead of genreating a new one.


☤ Generating a ``requirements.txt``
-----------------------------------

You can convert a ``Pipfile`` and ``Pipenv.lock`` into a ``requirements.txt`` file very easily, and get all the benefits of hashes, extras, and other goodies we have included.

Let's take this ``Pipfile``::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true

    [packages]
    requests = {version="*"}

And generate a ``requirements.txt`` out of it::

    $ pipenv lock -r
    chardet==3.0.4 --hash=sha256:fc323ffcaeaed0e0a02bf4d117757b98aed530d9ed4531e3e15460124c106691  --hash=sha256:84ab92ed1c4d4f16916e05906b6b75a6c0fb5db821cc65e70cbd64a3e2a5eaae
    requests==2.18.4 --hash=sha256:6a1b267aa90cac58ac3a765d067950e7dbbf75b1da07e895d1f594193a40a38b  --hash=sha256:9c443e7324ba5b85070c4a818ade28bfabedf16ea10206da1132edaa6dda237e
    certifi==2017.7.27.1 --hash=sha256:54a07c09c586b0e4c619f02a5e94e36619da8e2b053e20f594348c0611803704  --hash=sha256:40523d2efb60523e113b44602298f0960e900388cf3bb6043f645cf57ea9e3f5
    idna==2.6 --hash=sha256:8c7309c718f94b3a625cb648ace320157ad16ff131ae0af362c9f21b80ef6ec4  --hash=sha256:2c6a5de3089009e3da7c5dde64a141dbc8551d5b7f6cf4ed7c2568d0cc520a8f
    urllib3==1.22 --hash=sha256:06330f386d6e4b195fbfc736b297f58c5a892e4440e54d294d7004e3a9bbea1b  --hash=sha256:cc44da8e1145637334317feebd728bd869a35285b93cbb4cca2577da7e62db4f

Very fancy.

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

☤ Code Style Checking
---------------------

Pipenv has `Flake 8 <http://flake8.pycqa.org/en/latest/>`_ built into it. You can check the style of your code like so, without installing anything::

    $ cat t.py
    import requests

    $ pipenv check --style t.py
    t.py:1:1: F401 'requests' imported but unused
    t.py:1:16: W292 no newline at end of file

Super useful :)

☤ Open a Module in Your Editor
------------------------------

Pipenv allows you to open any Python module that is installed (including ones in your codebase), with the ``$ pipenv open`` command::

    $ pipenv install -e git+https://github.com/kennethreitz/background.git#egg=background
    Installing -e git+https://github.com/kennethreitz/background.git#egg=background…
    ...
    Updated Pipfile.lock!

    $ pipenv open background
    Opening '/Users/kennethreitz/.local/share/virtualenvs/hmm-mGOawwm_/src/background/background.py' in your EDITOR.

This allows you to easily read the code you're consuming, instead of looking it up on GitHub.

.. note:: The standard ``EDITOR`` environment variable is used for this. If you're using Sublime Text, for example, you'll want to ``export EDITOR=subl`` (once you've installed the command-line utility).

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
We do not recommend committing ``.env`` files into source control!

If your ``.env`` file is located in a different path or has a different name you may set the ``PIPENV_DOTENV_LOCATION`` environment variable::

    $ PIPENV_DOTENV_LOCATION=/path/to/.env pipenv shell


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

For example::

    $ PIP_INSTALL_OPTION="-- -DCMAKE_BUILD_TYPE=Release" pipenv install -e .


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

☤ Shell Completion
------------------

To enable completion in fish, add this to your config::

    eval (pipenv --completion)

Magic shell completions are now enabled!

✨🍰✨

☤ Working with platform-provided Python components
--------------------------------------------------

It's reasonably common for platform specific Python bindings for
operating system interfaces to only be available through the system
package manager, and hence unavailable for installation into virtual
environments with `pip`. In these cases, the virtual environment can
be created with access to the system `site-packages` directory::

    $ pipenv --three --site-packages

To ensure that all `pip`-installable components actually are installed
into the virtual environment and system packages are only used for
interfaces that don't participate in Python-level dependency resolution
at all, use the `PIP_IGNORE_INSTALLED` setting::

    $ PIP_IGNORE_INSTALLED=1 pipenv install --dev
