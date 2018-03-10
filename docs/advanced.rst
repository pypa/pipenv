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
    pywinusb = {version = "*", sys_platform = "== 'win32'"}

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

You can tell Pipenv to install a Pipfile's contents into its parent system with the ``--system`` flag::

    $ pipenv install --system

This is useful for Docker containers, and deployment infrastructure (e.g. Heroku does this).

Also useful for deployment is the ``--deploy`` flag::

    $ pipenv install --system --deploy

This will fail a build if the ``Pipfile.lock`` is out–of–date, instead of generating a new one.


☤ ``pipenv`` and ``conda``
--------------------------

To use Pipenv with a Conda–provided Python, you simply provide the path to the Python binary::

    $ pipenv install --python=/path/to/anaconda/python

To reuse Conda–installed Python packages, use the ``--site-packages`` flag::

    $ pipenv --python=/path/to/anaconda/python --site-packages

☤ Generating a ``requirements.txt``
-----------------------------------

You can convert a ``Pipfile`` and ``Pipfile.lock`` into a ``requirements.txt`` file very easily, and get all the benefits of extras and other goodies we have included.

Let's take this ``Pipfile``::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true

    [packages]
    requests = {version="*"}

And generate a ``requirements.txt`` out of it::

    $ pipenv lock -r
    chardet==3.0.4
    requests==2.18.4
    certifi==2017.7.27.1
    idna==2.6
    urllib3==1.22

If you wish to generate a ``requirements.txt`` with only the development requirements you can do that too!  Let's take the following ``Pipfile``::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true

    [dev-packages]
    pytest = {version="*"}

And generate a ``requirements.txt`` out of it::

    $ pipenv lock -r --dev
    py==1.4.34
    pytest==3.2.3

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

.. note::

   Commercial users and redistributors of `pipenv` should be aware that the public
   `Safety-DB` project backing this feature is licensed as CC-BY-NC-SA. Non-commercial
   use of this feature and use by organisations with their own pyup.io commercial license
   are thus both clearly fine, but other commercial redistributors and end users may want
   to perform their own legal assessment before relying on the capability.


☤ Community Integrations
------------------------

There are a range of community-maintained plugins and extensions available for a range of editors and IDEs, as well as
different products which integrate with Pipenv projects:

- `Heroku <https://heroku.com/python>`_ (Cloud Hosting)
- `Platform.sh <https://platform.sh/hosting/python>`_ (Cloud Hosting)
- `PyUp <https://pyup.io>`_ (Security Notification)
- `Emacs <https://github.com/pwalsh/pipenv.el>`_ (Editor Integration)
- `Fish Shell <https://github.com/fisherman/pipenv>`_ (Automatic ``$ pipenv shell``!)
- `VS Code <https://code.visualstudio.com/docs/python/environments>`_ (Editor Integration)

Works in progress:

- `Sublime Text <https://github.com/kennethreitz/pipenv-sublime>`_ (Editor Integration)
- `PyCharm <https://www.jetbrains.com/pycharm/download/>`_ (Editor Integration)
- Mysterious upcoming Google Cloud product (Cloud Hosting)



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

.. note:: The standard ``EDITOR`` environment variable is used for this. If you're using VS Code, for example, you'll want to ``export EDITOR=code`` (if you're on macOS you will want to `install the command <https://code.visualstudio.com/docs/setup/mac#_launching-from-the-command-line>`_ on to your ``PATH`` first).

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

To prevent pipenv from loading the ``.env`` file, set the ``PIPENV_DONT_LOAD_ENV`` environment variable::

    $ PIPENV_DONT_LOAD_ENV=1 pipenv shell

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

    - ``PIPENV_MAX_DEPTH`` — Set to an integer for the maximum number of directories to recursively
      search for a Pipfile.

    - ``PIPENV_TIMEOUT`` — Set to an integer for the max number of seconds Pipenv will
      wait for virtualenv creation to complete.  Defaults to 120 seconds.

    - ``PIPENV_IGNORE_VIRTUALENVS`` — Set to disable automatically using an activated virtualenv over
      the current project's own virtual environment.

    - ``PIPENV_PIPFILE`` — When running pipenv from a $PWD other than the same
      directory where the Pipfile is located, instruct pipenv to find the
      Pipfile in the location specified by this environment variable.

If you'd like to set these environment variables on a per-project basis, I recommend utilizing the fantastic `direnv <https://direnv.net>`_ project, in order to do so.

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
        - "3.7-dev"

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

A 3rd party plugin, `tox-pipenv`_ is also available to use Pipenv natively with tox.

.. _Requests: https://github.com/kennethreitz/requests
.. _tox: https://tox.readthedocs.io/en/latest/
.. _tox-pipenv: https://tox-pipenv.readthedocs.io/en/latest/
.. _Travis-CI: https://travis-ci.org/

☤ Shell Completion
------------------

To enable completion in fish, add this to your config::

    eval (pipenv --completion)

Alternatively, with bash or zsh, add this to your config::

    eval "$(pipenv --completion)"

Magic shell completions are now enabled!

✨🍰✨

☤ Working with Platform-Provided Python Components
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
