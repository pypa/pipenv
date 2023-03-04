.. _advanced:

Advanced Usage of Pipenv
========================

.. image:: https://farm4.staticflickr.com/3672/33231486560_bff4124c9a_k_d.jpg

This document is current in the process of being broken apart into more granular sections so that we may provide better overall documentation.


☤ Supplying additional arguments to pip
------------------------------------------------

There may be cases where you wish to supply additional arguments to pip to be used during the install phase.
For example, you may want to enable the pip feature for using
`system certificate stores <https://pip.pypa.io/en/latest/topics/https-certificates/#using-system-certificate-stores>`_

In this case you can supply these additional arguments to ``pipenv sync`` or ``pipenv install`` by passing additional
argument ``--extra-pip-args="--use-feature=truststore"``.   It is possible to supply multiple arguments in the ``--extra-pip-args``.
Example usage::

    pipenv sync --extra-pip-args="--use-feature=truststore --proxy=127.0.0.1"


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

You may only wish to verify your ``Pipfile.lock`` is up-to-date with dependencies specified in the ``Pipfile``, without installing::

    $ pipenv verify

The command will perform a verification, and return an exit code ``1`` when dependency locking is needed. This may be useful for cases when the ``Pipfile.lock`` file is subject to version control, so this command can be used within your CI/CD pipelines.

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

Sometimes, you would want to generate a requirements file based on your current
environment, for example to include tooling that only supports requirements.txt.
You can convert a ``Pipfile.lock`` into a ``requirements.txt``
file very easily.

Let's take this ``Pipfile``::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true
    name = "pypi"

    [packages]
    requests = {version="==2.18.4"}

    [dev-packages]
    pytest = {version="==3.2.3"}

Which generates a ``Pipfile.lock`` upon completion of running ``pipenv lock``` similar to::

    {
            "_meta": {
                    "hash": {
                            "sha256": "4b81df812babd4e54ba5a4086714d7d303c1c3f00d725c76e38dd58cbd360f4e"
                    },
                    "pipfile-spec": 6,
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
			... snipped ...
                    "requests": {
                            "hashes": [
                                    "sha256:6a1b267aa90cac58ac3a765d067950e7dbbf75b1da07e895d1f594193a40a38b",
                                    "sha256:9c443e7324ba5b85070c4a818ade28bfabedf16ea10206da1132edaa6dda237e"
                            ],
                            "index": "pypi",
                            "version": "==2.18.4"
                    },
			... snipped ...
            },
            "develop": {
                    ... snipped ...
                    "pytest": {
                            "hashes": [
                                    "sha256:27fa6617efc2869d3e969a3e75ec060375bfb28831ade8b5cdd68da3a741dc3c",
                                    "sha256:81a25f36a97da3313e1125fce9e7bbbba565bc7fec3c5beb14c262ddab238ac1"
                            ],
                            "index": "pypi",
                            "version": "==3.2.3"
                    }
                    ... snipped ...
    }

Given the ``Pipfile.lock`` exists, you may generate a set of requirements out of it with the default dependencies::

    $ pipenv requirements
    -i https://pypi.python.org/simple
    certifi==2022.9.24 ; python_version >= '3.6'
    chardet==3.0.4
    idna==2.6
    requests==2.18.4
    urllib3==1.22

As with other commands, passing ``--dev`` will include both the default and
development dependencies::

    $ pipenv requirements --dev
    -i https://pypi.python.org/simple
    colorama==0.4.5 ; sys_platform == 'win32'
    py==1.11.0 ; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'
    pytest==3.2.3
    setuptools==65.4.1 ; python_version >= '3.7'
    certifi==2022.9.24 ; python_version >= '3.6'
    chardet==3.0.4
    idna==2.6
    requests==2.18.4
    urllib3==1.22

If you wish to generate a requirements file with only the
development requirements you can do that too, using the ``--dev-only``
flag::

    $ pipenv requirements --dev-only
    -i https://pypi.python.org/simple
    colorama==0.4.5 ; sys_platform == 'win32'
    py==1.11.0 ; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'
    pytest==3.2.3
    setuptools==65.4.1 ; python_version >= '3.7'

Adding the ``--hash`` flag adds package hashes to the output for extra security.
Adding the ``--exclude-markers`` flag excludes the markers from the output.

The locked requirements are written to stdout, with shell output redirection
used to write them to a file::

    $ pipenv requirements > requirements.txt
    $ pipenv requirements --dev-only > dev-requirements.txt
    $ cat requirements.txt
    -i https://pypi.python.org/simple
    certifi==2022.9.24 ; python_version >= '3.6'
    chardet==3.0.4
    idna==2.6
    requests==2.18.4
    urllib3==1.22
    $ cat dev-requirements.txt
    -i https://pypi.python.org/simple
    colorama==0.4.5 ; sys_platform == 'win32'
    py==1.11.0 ; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'
    pytest==3.2.3
    setuptools==65.4.1 ; python_version >= '3.7'

If you have multiple categories in your Pipfile and wish to generate
a requirements file for only some categories, you can do that too,
using the ``--categories`` option::

    $ pipenv requirements --categories="tests" > requirements-tests.txt
    $ pipenv requirements --categories="docs" > requirements-docs.txt
    $ cat requirements-tests.txt
    -i https://pypi.org/simple
    attrs==22.1.0 ; python_version >= '3.5'
    iniconfig==1.1.1
    packaging==21.3 ; python_version >= '3.6'
    pluggy==1.0.0 ; python_version >= '3.6'
    py==1.11.0 ; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'
    pyparsing==3.0.9 ; python_full_version >= '3.6.8'
    pytest==7.1.3
    tomli==2.0.1 ; python_version >= '3.7'

It can be used to specify multiple categories also.

    $ pipenv requirements --categories="tests,docs"

☤ Detection of Security Vulnerabilities
---------------------------------------

Pipenv includes the `safety <https://github.com/pyupio/safety>`_ package, and will use it to scan your dependency graph
for known security vulnerabilities!

By default ``pipenv check`` will scan the Pipfile.lock default packages group and use this as the input to the safety command.
To scan other package categories pass the specific ``--categories`` you want to check against.
To have ``pipenv check`` scan the virtualenv packages for what is installed and use this as the input to the safety command,
run``pipenv check --use-installed``.
Note:  ``--use-installed`` was the default behavior in ``pipenv<=2023.2.4``

Example::

    $ pipenv install wheel==0.37.1
    $ cat Pipfile.lock
    ...
    "default": {
        "wheel": {
            "hashes": [
                "sha256:4bdcd7d840138086126cd09254dc6195fb4fc6f01c050a1d7236f2630db1d22a",
                "sha256:e9a504e793efbca1b8e0e9cb979a249cf4a0a7b5b8c9e8b65a5e39d49529c1c4"
            ],
            "index": "pypi",
            "version": "==0.37.1"
        }
    },
    ...

    $ pipenv check --use-lock
    ...
    -> Vulnerability found in wheel version 0.37.1
       Vulnerability ID: 51499
       Affected spec: <0.38.1
       ADVISORY: Wheel 0.38.1 includes a fix for CVE-2022-40898: An issue discovered in Python Packaging Authority (PyPA) Wheel 0.37.1 and earlier allows remote attackers to cause a denial of service
       via attacker controlled input to wheel cli.https://pyup.io/posts/pyup-discovers-redos-vulnerabilities-in-top-python-packages
       CVE-2022-40898
       For more information, please visit https://pyup.io/v/51499/742

     Scan was completed. 1 vulnerability was found.
     ...


.. note::

    Each month, `PyUp.io <https://pyup.io>`_ updates the ``safety`` database of
    insecure Python packages and `makes it available to the open source
    community for free <https://pyup.io/safety/>`__. Each time
    you run ``pipenv check`` to show you vulnerable dependencies,
    Pipenv makes an API call to retrieve and use those results.

    For more up-to-date vulnerability data, you may also use your own safety
    API key by setting the environment variable ``PIPENV_PYUP_API_KEY``.


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


☤ Open a Module in Your Editor
------------------------------

Pipenv allows you to open any Python module that is installed (including ones in your codebase), with the ``$ pipenv open`` command::

    $ pipenv install -e git+https://github.com/kennethreitz/background.git#egg=background
    Installing -e git+https://github.com/kennethreitz/background.git#egg=background...
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
    Warning: Python 3.6 was not found on your system...
    Would you like us to install latest CPython 3.6 with pyenv? [Y/n]: y
    Installing CPython 3.6.2 with pyenv (this may take a few minutes)...
    ...
    Making Python installation global...
    Creating a virtualenv for this project...
    Using /Users/kennethreitz/.pyenv/shims/python3 to create virtualenv...
    ...
    No package provided, installing all dependencies.
    ...
    Installing dependencies from Pipfile.lock...
    🐍   ❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒ 5/5 — 00:00:03
    To activate this project's virtualenv, run the following:
     $ pipenv shell

Pipenv automatically honors both the ``python_full_version`` and ``python_version`` `PEP 508 <https://www.python.org/dev/peps/pep-0508/>`_ specifiers.

💫✨🍰✨💫

☤ Custom Script Shortcuts
-------------------------

Pipenv supports creating custom shortcuts in the (optional) ``[scripts]`` section of your Pipfile.

You can then run ``pipenv run <shortcut name>`` in your terminal to run the command in the
context of your pipenv virtual environment even if you have not activated the pipenv shell first.

For example, in your Pipfile:

.. code-block:: toml

    [scripts]
    printspam = "python -c \"print('I am a silly example, no one would need to do this')\""

And then in your terminal::

    $ pipenv run printspam
    I am a silly example, no one would need to do this

Commands that expect arguments will also work.
For example:

.. code-block:: toml

    [scripts]
    echospam = "echo I am really a very silly example"

::

    $ pipenv run echospam "indeed"
    I am really a very silly example indeed

You can also specify pacakge functions as callables such as: ``<pathed.module>:<func>``. These can also take arguments.
For exaple:

.. code-block:: toml

    [scripts]
    my_func_with_args = {call = "package.module:func('arg1', 'arg2')"}
    my_func_no_args = {call = "package.module:func()"}

::
    $ pipenv run my_func_with_args
    $ pipenv run my_func_no_args

You can display the names and commands of your shortcuts by running ``pipenv scripts`` in your terminal.

::

    $ pipenv scripts
    command   script
    echospam  echo I am really a very silly example

.. _configuration-with-environment-variables:

☤ Configuration With Environment Variables
------------------------------------------

Pipenv comes with a handful of options that can be set via shell environment
variables.

To enable boolean options, create the variable in your shell and assign to it a
truthy value (i.e. ``"1"``)::

    $ PIPENV_IGNORE_VIRTUALENVS=1

To explicitly disable a boolean option, assign to it a falsey value (i.e. ``"0"``).

.. autoclass:: pipenv.environments.Setting
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

☤ Virtual Environment Name
-------------------------------------

The virtualenv name created by Pipenv may be different from what you were expecting.
Dangerous characters (i.e. ``$`!*@"`` as well as space, line feed, carriage return,
and tab) are converted to underscores. Additionally, the full path to the current
folder is encoded into a "slug value" and appended to ensure the virtualenv name
is unique.

Pipenv supports a arbitrary custom name for the virtual environment set at ``PIPENV_CUSTOM_VENV_NAME``.

The logical place to specify this would be in a user's ``.env`` file in the root of the project, which gets loaded by pipenv when it is invoked.


☤ Testing Projects
------------------

Pipenv is being used in projects like `Requests`_ for declaring development dependencies and running the test suite.

We have currently tested deployments with both `Travis-CI`_ and `tox`_ with success.

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
        pipenv run pytest tests


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
        pipenv run pytest tests

    [testenv:flake8-py3]
    basepython = python3.4
    commands=
        pipenv install --dev
        pipenv run flake8 --version
        pipenv run flake8 setup.py docs project test

Pipenv will automatically use the virtualenv provided by ``tox``. If ``pipenv install --dev`` installs e.g. ``pytest``, then installed command ``pytest`` will be present in given virtualenv and can be called directly by ``pytest tests`` instead of ``pipenv run pytest tests``.

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

.. _Requests: https://github.com/psf/requests
.. _tox: https://tox.readthedocs.io/en/latest/
.. _tox-pipenv: https://tox-pipenv.readthedocs.io/en/latest/
.. _Travis-CI: https://travis-ci.org/



✨🍰✨

☤ Working with Platform-Provided Python Components
--------------------------------------------------

It's reasonably common for platform specific Python bindings for
operating system interfaces to only be available through the system
package manager, and hence unavailable for installation into virtual
environments with ``pip``. In these cases, the virtual environment can
be created with access to the system ``site-packages`` directory::

    $ pipenv --site-packages

To ensure that all ``pip``-installable components actually are installed
into the virtual environment and system packages are only used for
interfaces that don't participate in Python-level dependency resolution
at all, use the ``PIP_IGNORE_INSTALLED`` setting::

    $ PIP_IGNORE_INSTALLED=1 pipenv install --dev


.. _pipfile-vs-setuppy:

☤ Pipfile vs setup.py
---------------------

There is a subtle but very important distinction to be made between **applications** and **libraries**. This is a very common source of confusion in the Python community.

Libraries provide reusable functionality to other libraries and applications (let's use the umbrella term **projects** here). They are required to work alongside other libraries, all with their own set of sub-dependencies. They define **abstract dependencies**. To avoid version conflicts in sub-dependencies of different libraries within a project, libraries should never ever pin dependency versions. Although they may specify lower or (less frequently) upper bounds, if they rely on some specific feature/fix/bug. Library dependencies are specified via ``install_requires`` in ``setup.py``.

Libraries are ultimately meant to be used in some **application**. Applications are different in that they usually are not depended on by other projects. They are meant to be deployed into some specific environment and only then should the exact versions of all their dependencies and sub-dependencies be made concrete. To make this process easier is currently the main goal of Pipenv.

To summarize:

- For libraries, define **abstract dependencies** via ``install_requires`` in ``setup.py``. The decision of which version exactly to be installed and where to obtain that dependency is not yours to make!
- For applications, define **dependencies and where to get them** in the ``Pipfile`` and use this file to update the set of **concrete dependencies** in ``Pipfile.lock``. This file defines a specific idempotent environment that is known to work for your project. The ``Pipfile.lock`` is your source of truth. The ``Pipfile`` is a convenience for you to create that lock-file, in that it allows you to still remain somewhat vague about the exact version of a dependency to be used. Pipenv is there to help you define a working conflict-free set of specific dependency-versions, which would otherwise be a very tedious task.
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

By default, Pipenv will initialize a project using whatever version of python the system has as default. Besides starting a project with the ``--python`` flag, you can also use ``PIPENV_DEFAULT_PYTHON_VERSION`` to specify what version to use when starting a project when ``--python`` isn't used.
