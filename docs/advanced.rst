.. _advanced:

Advanced Usage of Pipenv
========================

.. image:: https://farm4.staticflickr.com/3672/33231486560_bff4124c9a_k_d.jpg

This document covers some of Pipenv's more glorious and advanced features.

☤ Caveats
---------

- Dependencies of wheels provided in a ``Pipfile`` will not be captured by ``$ pipenv lock``.
- There are some known issues with using private indexes, related to hashing. We're actively working to solve this problem. You may have great luck with this, however.
- Installation is intended to be as deterministic as possible — use the ``--sequential`` flag to increase this, if experiencing issues.

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

☤ Using a PyPI Mirror
----------------------------

If you'd like to override the default PyPI index urls with the url for a PyPI mirror, you can use the following::

    $ pipenv install --pypi-mirror <mirror_url>

    $ pipenv update --pypi-mirror <mirror_url>

    $ pipenv sync --pypi-mirror <mirror_url>

    $ pipenv lock --pypi-mirror <mirror_url>

    $ pipenv uninstall --pypi-mirror <mirror_url>

Alternatively, you can set the ``PIPENV_PYPI_MIRROR`` environment variable.

☤ Injecting credentials into Pipfiles via environment variables
-----------------------------------------------------------------


Pipenv will expand environment variables (if defined) in your Pipfile. Quite
useful if you need to authenticate to a private PyPI::

    [[source]]
    url = "https://$USERNAME:${PASSWORD}@mypypi.example.com/simple"
    verify_ssl = true
    name = "pypi"

Luckily - pipenv will hash your Pipfile *before* expanding environment
variables (and, helpfully, will substitute the environment variables again when
you install from the lock file - so no need to commit any secrets! Woo!)


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

☤ Using pipenv for Deployments
------------------------------

You may want to use ``pipenv`` as part of a deployment process.

You can enforce that your ``Pipfile.lock`` is up to date using the ``--deploy`` flag::

    $ pipenv install --deploy

This will fail a build if the ``Pipfile.lock`` is out–of–date, instead of generating a new one.

Or you can install packages exactly as specified in ``Pipfile.lock`` using the ``sync`` command::

    $ pipenv sync

.. note::

    ``pipenv install --ignore-pipfile`` is nearly equivalent to ``pipenv sync``, but ``pipenv sync`` will *never* attempt to re-lock your dependencies as it is considered an atomic operation.  ``pipenv install`` by default does attempt to re-lock unless using the ``--deploy`` flag.

Deploying System Dependencies
/////////////////////////////

You can tell Pipenv to install a Pipfile's contents into its parent system with the ``--system`` flag::

    $ pipenv install --system

This is useful for managing the system Python, and deployment infrastructure (e.g. Heroku does this).

☤ Pipenv and Other Python Distributions
---------------------------------------

To use Pipenv with a third-party Python distribution (e.g. Anaconda), you simply provide the path to the Python binary::

    $ pipenv install --python=/path/to/python

Anaconda uses Conda to manage packages. To reuse Conda–installed Python packages, use the ``--site-packages`` flag::

    $ pipenv --python=/path/to/python --site-packages

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

   In order to enable this functionality while maintaining its permissive
   copyright license, `pipenv` embeds an API client key for the backend
   Safety API operated by pyup.io rather than including a full copy of the
   CC-BY-NC-SA licensed Safety-DB database. This embedded client key is
   shared across all `pipenv check` users, and hence will be subject to
   API access throttling based on overall usage rather than individual
   client usage.

   You can also use your own safety API key by setting the
   environment variable ``PIPENV_PYUP_API_KEY``.


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
- `PyCharm <https://www.jetbrains.com/pycharm/download/>`_ (Editor Integration)

Works in progress:

- `Sublime Text <https://github.com/kennethreitz/pipenv-sublime>`_ (Editor Integration)
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

☤ Custom Script Shortcuts
-------------------------

Pipenv supports creating custom shortcuts in the (optional) ``[scripts]`` section of your Pipfile. 

You can then run ``pipenv run <shortcut name>`` in your terminal to run the command in the
context of your pipenv virtual environment even if you have not activated the pipenv shell first. 

For example, in your Pipfile:: 

    [scripts]
    printspam = "python -c \"print('I am a silly example, no one would need to do this')\""

And then in your terminal::

    $ pipenv run printspam
    I am a silly example, no one would need to do this

Commands that expect arguments will also work.
For example::

    [scripts]
    echospam = "echo I am really a very silly example"

    $ pipenv run echospam "indeed"
    I am really a very silly example indeed

☤ Support for Environment Variables
-----------------------------------

Pipenv supports the usage of environment variables in values. For example::

    [[source]]
    url = "https://${PYPI_USERNAME}:${PYPI_PASSWORD}@my_private_repo.example.com/simple"
    verify_ssl = true
    name = "pypi"

    [dev-packages]

    [packages]
    requests = {version="*", index="home"}
    maya = {version="*", index="pypi"}
    records = "*"

Environment variables may be specified as ``${MY_ENVAR}`` or ``$MY_ENVAR``.
On Windows, ``%MY_ENVAR%`` is supported in addition to ``${MY_ENVAR}`` or ``$MY_ENVAR``.


☤ Configuration With Environment Variables
------------------------------------------

Pipenv comes with a handful of options that can be enabled via shell environment
variables. To activate them, simply create the variable in your shell and pipenv
will detect it.

.. automodule:: pipenv.environments
    :members:

If you'd like to set these environment variables on a per-project basis, I recommend utilizing the fantastic `direnv <https://direnv.net>`_ project, in order to do so.

Also note that `pip itself supports environment variables <https://pip.pypa.io/en/stable/user_guide/#environment-variables>`_, if you need additional customization.

For example::

    $ PIP_INSTALL_OPTION="-- -DCMAKE_BUILD_TYPE=Release" pipenv install -e .


☤ Custom Virtual Environment Location
-------------------------------------

Pipenv automatically honors the ``WORKON_HOME`` environment variable, if you
have it set — so you can tell pipenv to store your virtual environments
wherever you want, e.g.::

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
    deps = pipenv
    commands=
        pipenv install --dev
        pipenv run py.test tests

    [testenv:flake8-py3]
    basepython = python3.4
    commands=
        pipenv install --dev
        pipenv run flake8 --version
        pipenv run flake8 setup.py docs project test

Pipenv will automatically use the virtualenv provided by ``tox``. If ``pipenv install --dev`` installs e.g. ``pytest``, then installed command ``py.test`` will be present in given virtualenv and can be called directly by ``py.test tests`` instead of ``pipenv run py.test tests``.

You might also want to add ``--ignore-pipfile`` to ``pipenv install``, as to
not accidentally modify the lock-file on each test run. This causes Pipenv
to ignore changes to the ``Pipfile`` and (more importantly) prevents it from
adding the current environment to ``Pipfile.lock``. This might be important as
the current environment (i.e. the virtualenv provisioned by tox) will usually
contain the current project (which may or may not be desired) and additional
dependencies from ``tox``'s ``deps`` directive. The initial provisioning may
alternatively be disabled by adding ``skip_install = True`` to tox.ini.

This method requires you to be explicit about updating the lock-file, which is
probably a good idea in any case.

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


.. _pipfile-vs-setuppy:

☤ Pipfile vs setup.py
---------------------

There is a subtle but very important distinction to be made between **applications** and **libraries**. This is a very common source of confusion in the Python community.

Libraries provide reusable functionality to other libraries and applications (let's use the umbrella term **projects** here). They are required to work alongside other libraries, all with their own set of subdependencies. They define **abstract dependencies**. To avoid version conflicts in subdependencies of different libraries within a project, libraries should never ever pin dependency versions. Although they may specify lower or (less frequently) upper bounds, if they rely on some specific feature/fix/bug. Library dependencies are specified via ``install_requires`` in ``setup.py``.

Libraries are ultimately meant to be used in some **application**. Applications are different in that they usually are not depended on by other projects. They are meant to be deployed into some specific environment and only then should the exact versions of all their dependencies and subdependencies be made concrete. To make this process easier is currently the main goal of Pipenv.

To summarize:

- For libraries, define **abstract dependencies** via ``install_requires`` in ``setup.py``. The decision of which version exactly to be installed and where to obtain that dependency is not yours to make!
- For applications, define **dependencies and where to get them** in the `Pipfile` and use this file to update the set of **concrete dependencies** in ``Pipfile.lock``. This file defines a specific idempotent environment that is known to work for your project. The ``Pipfile.lock`` is your source of truth. The ``Pipfile`` is a convenience for you to create that lock-file, in that it allows you to still remain somewhat vague about the exact version of a dependency to be used. Pipenv is there to help you define a working conflict-free set of specific dependency-versions, which would otherwise be a very tedious task.
- Of course, ``Pipfile`` and Pipenv are still useful for library developers, as they can be used to define a development or test environment.
- And, of course, there are projects for which the distinction between library and application isn't that clear. In that case, use ``install_requires`` alongside Pipenv and ``Pipfile``.

You can also do this::

    $ pipenv install -e .

This will tell Pipenv to lock all your ``setup.py``–declared dependencies.

☤ Changing Pipenv's Cache Location
----------------------------------

You can force Pipenv to use a different cache location by setting the environment variable ``PIPENV_CACHE_DIR`` to the location you wish. This is useful in the same situations that you would change ``PIP_CACHE_DIR`` to a different directory.

☤ Changing Default Python Versions
----------------------------------

By default, Pipenv will initialize a project using whatever version of python the python3 is. Besides starting a project with the ``--three`` or ``--two`` flags, you can also use ``PIPENV_DEFAULT_PYTHON_VERSION`` to specify what version to use when starting a project when ``--three`` or ``--two`` aren't used.
