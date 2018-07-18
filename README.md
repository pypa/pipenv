Pipenv: Python Development Workflow for Humans
==============================================

[![image](https://img.shields.io/pypi/v/pipenv.svg)](https://pypi.python.org/pypi/pipenv)
[![image](https://img.shields.io/pypi/l/pipenv.svg)](https://pypi.python.org/pypi/pipenv)
[![image](https://badge.buildkite.com/79c7eccf056b17c3151f3c4d0e4c4b8b724539d84f1e037b9b.svg?branch=master)](https://code.kennethreitz.org/source/pipenv/)
[![image](https://img.shields.io/pypi/pyversions/pipenv.svg)](https://pypi.python.org/pypi/pipenv)
[![image](https://img.shields.io/badge/Say%20Thanks-!-1EAEDB.svg)](https://saythanks.io/to/kennethreitz)

------------------------------------------------------------------------

**Pipenv** is a tool that aims to bring the best of all packaging worlds
(bundler, composer, npm, cargo, yarn, etc.) to the Python world.
*Windows is a first--class citizen, in our world.*

It automatically creates and manages a virtualenv for your projects, as
well as adds/removes packages from your `Pipfile` as you
install/uninstall packages. It also generates the ever--important
`Pipfile.lock`, which is used to produce deterministic builds.

![image](http://media.kennethreitz.com.s3.amazonaws.com/pipenv.gif)

The problems that Pipenv seeks to solve are multi-faceted:

-   You no longer need to use `pip` and `virtualenv` separately. They
    work together.
-   Managing a `requirements.txt` file [can be
    problematic](https://www.kennethreitz.org/essays/a-better-pip-workflow),
    so Pipenv uses the upcoming `Pipfile` and `Pipfile.lock` instead,
    which is superior for basic use cases.
-   Hashes are used everywhere, always. Security. Automatically expose
    security vulnerabilities.
-   Give you insight into your dependency graph (e.g. `$ pipenv graph`).
-   Streamline development workflow by loading `.env` files.

Installation
------------

If you\'re on MacOS, you can install Pipenv easily with Homebrew:

    $ brew install pipenv

Or, if you\'re using Fedora 28:

    $ sudo dnf install pipenv

Otherwise, refer to the [documentation](https://docs.pipenv.org/install/) for instructions.

✨🍰✨

☤ User Testimonials
-------------------

**Jannis Leidel**, former pip maintainer---

:   *Pipenv is the porcelain I always wanted to build for pip. It fits
    my brain and mostly replaces virtualenvwrapper and manual pip calls
    for me. Use it.*

**David Gang**---

:   *This package manager is really awesome. For the first time I know
    exactly what my dependencies are which I installed and what the
    transitive dependencies are. Combined with the fact that installs
    are deterministic, makes this package manager first class, like
    cargo*.

**Justin Myles Holmes**---

:   *Pipenv is finally an abstraction meant to engage the mind instead
    of merely the filesystem.*

☤ Features
----------

-   Enables truly *deterministic builds*, while easily specifying *only
    what you want*.
-   Generates and checks file hashes for locked dependencies.
-   Automatically install required Pythons, if `pyenv` is available.
-   Automatically finds your project home, recursively, by looking for a
    `Pipfile`.
-   Automatically generates a `Pipfile`, if one doesn\'t exist.
-   Automatically creates a virtualenv in a standard location.
-   Automatically adds/removes packages to a `Pipfile` when they are
    un/installed.
-   Automatically loads `.env` files, if they exist.

The main commands are `install`, `uninstall`, and `lock`, which
generates a `Pipfile.lock`. These are intended to replace
`$ pip install` usage, as well as manual virtualenv management (to
activate a virtualenv, run `$ pipenv shell`).

### Basic Concepts

-   A virtualenv will automatically be created, when one doesn\'t exist.
-   When no parameters are passed to `install`, all packages
    `[packages]` specified will be installed.
-   To initialize a Python 3 virtual environment, run
    `$ pipenv --three`.
-   To initialize a Python 2 virtual environment, run `$ pipenv --two`.
-   Otherwise, whatever virtualenv defaults to will be the default.

### Other Commands

-   `shell` will spawn a shell with the virtualenv activated.
-   `run` will run a given command from the virtualenv, with any
    arguments forwarded (e.g. `$ pipenv run python`).
-   `check` asserts that PEP 508 requirements are being met by the
    current environment.
-   `graph` will print a pretty graph of all your installed
    dependencies.

### Shell Completion

For example, with fish, put this in your
`~/.config/fish/completions/pipenv.fish`:

    eval (pipenv --completion)

Alternatively, with bash, put this in your `.bashrc` or `.bash_profile`:

    eval "$(pipenv --completion)"

Magic shell completions are now enabled! There is also a [fish
plugin](https://github.com/fisherman/pipenv), which will automatically
activate your subshells for you!

Fish is the best shell. You should use it.

☤ Usage
-------

    $ pipenv
    Usage: pipenv [OPTIONS] COMMAND [ARGS]...

    Options:
      --where          Output project home information.
      --venv           Output virtualenv information.
      --py             Output Python interpreter information.
      --envs           Output Environment Variable options.
      --rm             Remove the virtualenv.
      --bare           Minimal output.
      --completion     Output completion (to be eval'd).
      --man            Display manpage.
      --three / --two  Use Python 3/2 when creating virtualenv.
      --python TEXT    Specify which version of Python virtualenv should use.
      --site-packages  Enable site-packages for the virtualenv.
      --version        Show the version and exit.
      -h, --help       Show this message and exit.


    Usage Examples:
       Create a new project using Python 3.7, specifically:
       $ pipenv --python 3.7

       Remove project virtualenv (inferred from current directory):
       $ pipenv --rm

       Install all dependencies for a project (including dev):
       $ pipenv install --dev

       Create a lockfile containing pre-releases:
       $ pipenv lock --pre

       Show a graph of your installed dependencies:
       $ pipenv graph

       Check your installed dependencies for security vulnerabilities:
       $ pipenv check

       Install a local setup.py into your virtual environment/Pipfile:
       $ pipenv install -e .

       Use a lower-level pip command:
       $ pipenv run pip freeze

    Commands:
      check      Checks for security vulnerabilities and against PEP 508 markers
                 provided in Pipfile.
      clean      Uninstalls all packages not specified in Pipfile.lock.
      graph      Displays currently–installed dependency graph information.
      install    Installs provided packages and adds them to Pipfile, or (if none
                 is given), installs all packages.
      lock       Generates Pipfile.lock.
      open       View a given module in your editor.
      run        Spawns a command installed into the virtualenv.
      shell      Spawns a shell within the virtualenv.
      sync       Installs all packages specified in Pipfile.lock.
      uninstall  Un-installs a provided package and removes it from Pipfile.

Locate the project:

    $ pipenv --where
    /Users/kennethreitz/Library/Mobile Documents/com~apple~CloudDocs/repos/kr/pipenv/test

Locate the virtualenv:

    $ pipenv --venv
    /Users/kennethreitz/.local/share/virtualenvs/test-Skyy4vre

Locate the Python interpreter:

    $ pipenv --py
    /Users/kennethreitz/.local/share/virtualenvs/test-Skyy4vre/bin/python

Install packages:

    $ pipenv install
    Creating a virtualenv for this project...
    ...
    No package provided, installing all dependencies.
    Virtualenv location: /Users/kennethreitz/.local/share/virtualenvs/test-EJkjoYts
    Installing dependencies from Pipfile.lock...
    ...

    To activate this project's virtualenv, run the following:
    $ pipenv shell

Install a dev dependency:

    $ pipenv install pytest --dev
    Installing pytest...
    ...
    Adding pytest to Pipfile's [dev-packages]...

Show a dependency graph:

    $ pipenv graph
    requests==2.18.4
      - certifi [required: >=2017.4.17, installed: 2017.7.27.1]
      - chardet [required: >=3.0.2,<3.1.0, installed: 3.0.4]
      - idna [required: >=2.5,<2.7, installed: 2.6]
      - urllib3 [required: <1.23,>=1.21.1, installed: 1.22]

Generate a lockfile:

    $ pipenv lock
    Assuring all dependencies from Pipfile are installed...
    Locking [dev-packages] dependencies...
    Locking [packages] dependencies...
    Note: your project now has only default [packages] installed.
    To install [dev-packages], run: $ pipenv install --dev

Install all dev dependencies:

    $ pipenv install --dev
    Pipfile found at /Users/kennethreitz/repos/kr/pip2/test/Pipfile. Considering this to be the project home.
    Pipfile.lock out of date, updating...
    Assuring all dependencies from Pipfile are installed...
    Locking [dev-packages] dependencies...
    Locking [packages] dependencies...

Uninstall everything:

    $ pipenv uninstall --all
    No package provided, un-installing all dependencies.
    Found 25 installed package(s), purging...
    ...
    Environment now purged and fresh!

Use the shell:

    $ pipenv shell
    Loading .env environment variables…
    Launching subshell in virtual environment. Type 'exit' or 'Ctrl+D' to return.
    $ ▯

☤ Documentation
---------------

Documentation resides over at [pipenv.org](http://pipenv.org/).
