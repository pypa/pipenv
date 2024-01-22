Pipenv: Python Development Workflow for Humans
==============================================

[![image](https://img.shields.io/pypi/v/pipenv.svg)](https://python.org/pypi/pipenv)
[![image](https://img.shields.io/pypi/l/pipenv.svg)](https://python.org/pypi/pipenv)
[![CI](https://github.com/pypa/pipenv/actions/workflows/ci.yaml/badge.svg)](https://github.com/pypa/pipenv/actions/workflows/ci.yaml)
[![image](https://img.shields.io/pypi/pyversions/pipenv.svg)](https://python.org/pypi/pipenv)

------------------------------------------------------------------------

**Pipenv** is a Python virtualenv management tool that supports a multitude of systems and nicely bridges the gaps between pip, python (using system python, pyenv or asdf) and virtualenv.
*Linux, macOS, and Windows are all first-class citizens in pipenv.*

Pipenv automatically creates and manages a virtualenv for your projects, as well as adds/removes packages from your `Pipfile` as you install/uninstall packages. It also generates a project `Pipfile.lock`, which is used to produce deterministic builds.

Pipenv is primarily meant to provide users and developers of applications with an easy method to arrive at a consistent working project environment.

The problems that Pipenv seeks to solve are multi-faceted:

- You no longer need to use `pip` and `virtualenv` separately: they work together.
- Managing a `requirements.txt` file with package hashes can be problematic.  Pipenv uses `Pipfile` and `Pipfile.lock` to separate abstract dependency declarations from the last tested combination.
- Hashes are documented in the lock file which are verified during install. Security considerations are put first.
- Strongly encourage the use of the latest versions of dependencies to minimize security risks [arising from outdated components](https://www.owasp.org/index.php/Top_10-2017_A9-Using_Components_with_Known_Vulnerabilities).
- Gives you insight into your dependency graph (e.g. `$ pipenv graph`).
- Streamline development workflow by supporting local customizations with `.env` files.

Table Of Contents
------------------

- [Pipenv](#pipenv-python-development-workflow-for-humans)

- [Installation](#installation)

- [Features](#features)

- [Basic Concepts](#basic-concepts)

- [Other Commands](#other-commands)

- [Shell Completion](#shell-completion)

- [Usage](#usage)

    - [Usage Examples](#usage-examples)

    - [Commands](#commands)

    - [Locate the Project](#locate-the-project)

    - [Locate the virtualenv](#locate-the-virtualenv)

    - [Locate the Python Interpreter](#locate-the-python-interpreter)

    - [Install Packages](#install-packages)

    - [Installing from git](#installing-from-git)

    - [Install a dev dependency](#install-a-dev-dependency)

    - [Show a dependency graph](#show-a-dependency-graph)

    - [Generate a lockfile](#generate-a-lockfile)

    - [Install all dev dependencies](#install-all-dev-dependencies)

    - [Uninstall everything](#uninstall-everything)

    - [Use the shell](#use-the-shell)

- [Documentation](#documentation)

Installation
------------

**Pipenv can be installed with Python 3.7 and above.**

For most users, we recommend installing Pipenv using `pip`:

    pip install --user pipenv

Or, if you\'re using Fedora:

    sudo dnf install pipenv

Or, if you\'re using FreeBSD:

    pkg install py39-pipenv

Or, if you\'re using Gentoo:

    sudo emerge pipenv

Or, if you\'re using Void Linux:

    sudo xbps-install -S python3-pipenv

Alternatively, some users prefer to use [Pipx](https://pypi.org/p/pipx):

    pipx install pipenv

Or, some users prefer to use Python pip module

    python -m pip install pipenv

Refer to the [documentation](https://pipenv.pypa.io/en/latest/#install-pipenv-today) for latest instructions.

✨🍰✨

Features
----------

-   Enables truly *deterministic builds*, while easily specifying *only
    what you want*.
-   Generates and checks file hashes for locked dependencies.
-   Automatically install required Pythons, if `pyenv` or `asdf` is available.
-   Automatically finds your project home, recursively, by looking for a
    `Pipfile`.
-   Automatically generates a `Pipfile`, if one doesn\'t exist.
-   Automatically creates a virtualenv in a standard location.
-   Automatically adds/removes packages to a `Pipfile` when they are installed/uninstalled.
-   Automatically loads `.env` files, if they exist.

For command reference, see [Commands](https://pipenv.pypa.io/en/latest/commands/).

### Basic Concepts

-   A virtualenv will automatically be created, when one doesn\'t exist.
-   When no parameters are passed to `install`, all packages
    `[packages]` specified will be installed.
-   Otherwise, whatever virtualenv defaults to will be the default.


### Shell Completion

To enable completion in fish, add this to your configuration `~/.config/fish/completions/pipenv.fish`:

    eval (env _PIPENV_COMPLETE=fish_source pipenv)

There is also a [fish plugin](https://github.com/fisherman/pipenv), which will automatically
activate your subshells for you!

Alternatively, with zsh, add this to your configuration `~/.zshrc`:

    eval "$(_PIPENV_COMPLETE=zsh_source pipenv)"

Alternatively, with bash, add this to your configuration `~/.bashrc` or `~/.bash_profile`:

    eval "$(_PIPENV_COMPLETE=bash_source pipenv)"

Magic shell completions are now enabled!

Usage
-------

    $ pipenv --help
    Usage: pipenv [OPTIONS] COMMAND [ARGS]...

    Options:
      --where                         Output project home information.
      --venv                          Output virtualenv information.
      --py                            Output Python interpreter information.
      --envs                          Output Environment Variable options.
      --rm                            Remove the virtualenv.
      --bare                          Minimal output.
      --man                           Display manpage.
      --support                       Output diagnostic information for use in
                                      GitHub issues.
      --site-packages / --no-site-packages
                                      Enable site-packages for the virtualenv.
                                      [env var: PIPENV_SITE_PACKAGES]
      --python TEXT                   Specify which version of Python virtualenv
                                      should use.
      --clear                         Clears caches (pipenv, pip).  [env var:
                                      PIPENV_CLEAR]
      -q, --quiet                     Quiet mode.
      -v, --verbose                   Verbose mode.
      --pypi-mirror TEXT              Specify a PyPI mirror.
      --version                       Show the version and exit.
      -h, --help                      Show this message and exit.


   ### Usage Examples:

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

   ### Commands:

      check         Checks for PyUp Safety security vulnerabilities and against
                    PEP 508 markers provided in Pipfile.
      clean         Uninstalls all packages not specified in Pipfile.lock.
      graph         Displays currently-installed dependency graph information.
      install       Installs provided packages and adds them to Pipfile, or (if no
                    packages are given), installs all packages from Pipfile.
      lock          Generates Pipfile.lock.
      open          View a given module in your editor.
      requirements  Generate a requirements.txt from Pipfile.lock.
      run           Spawns a command installed into the virtualenv.
      scripts       Lists scripts in current environment config.
      shell         Spawns a shell within the virtualenv.
      sync          Installs all packages specified in Pipfile.lock.
      uninstall     Uninstalls a provided package and removes it from Pipfile.
      update        Runs lock, then sync.
      upgrade       Update the lock of the specified dependency / sub-dependency,
                    but does not actually install the packages.
      verify        Verify the hash in Pipfile.lock is up-to-date.


### Locate the project:

    $ pipenv --where
    /Users/kennethreitz/Library/Mobile Documents/com~apple~CloudDocs/repos/kr/pipenv/test

### Locate the virtualenv:

    $ pipenv --venv
    /Users/kennethreitz/.local/share/virtualenvs/test-Skyy4vre

### Locate the Python interpreter:

    $ pipenv --py
    /Users/kennethreitz/.local/share/virtualenvs/test-Skyy4vre/bin/python

### Install packages:

    $ pipenv install
    Creating a virtualenv for this project...
    ...
    No package provided, installing all dependencies.
    Virtualenv location: /Users/kennethreitz/.local/share/virtualenvs/test-EJkjoYts
    Installing dependencies from Pipfile.lock...
    ...

    To activate this project's virtualenv, run the following:
    $ pipenv shell

### Installing from git:

You can install packages with pipenv from git and other version control systems using URLs formatted according to the following rule:

    <vcs_type>+<scheme>://<location>/<user_or_organization>/<repository>@<branch_or_tag>#<package_name>

The only optional section is the `@<branch_or_tag>` section.  When using git over SSH, you may use the shorthand vcs and scheme alias `git+git@<location>:<user_or_organization>/<repository>@<branch_or_tag>#<package_name>`. Note that this is translated to `git+ssh://git@<location>` when parsed.

Valid values for `<vcs_type>` include `git`, `bzr`, `svn`, and `hg`.  Valid values for `<scheme>` include `http,`, `https`, `ssh`, and `file`.  In specific cases you also have access to other schemes: `svn` may be combined with `svn` as a scheme, and `bzr` can be combined with `sftp` and `lp`.

Note that it is **strongly recommended** that you install any version-controlled dependencies in editable mode, using `pipenv install -e`, in order to ensure that dependency resolution can be performed with an up to date copy of the repository each time it is performed, and that it includes all known dependencies.

Below is an example usage which installs the git repository located at `https://github.com/requests/requests.git` from tag `v2.19.1` as package name `requests`:

    $ pipenv install -e git+https://github.com/requests/requests.git@v2.19#egg=requests
    Creating a Pipfile for this project...
    Installing -e git+https://github.com/requests/requests.git@v2.19.1#egg=requests...
    [...snipped...]
    Adding -e git+https://github.com/requests/requests.git@v2.19.1#egg=requests to Pipfile's [packages]...
    [...]

You can read more about [pip's implementation of vcs support here](https://pip.pypa.io/en/stable/topics/vcs-support/).

### Install a dev dependency:

    $ pipenv install pytest --dev
    Installing pytest...
    ...
    Adding pytest to Pipfile's [dev-packages]...

### Show a dependency graph:

    $ pipenv graph
    requests==2.18.4
      - certifi [required: >=2017.4.17, installed: 2017.7.27.1]
      - chardet [required: >=3.0.2,<3.1.0, installed: 3.0.4]
      - idna [required: >=2.5,<2.7, installed: 2.6]
      - urllib3 [required: <1.23,>=1.21.1, installed: 1.22]

### Generate a lockfile:

    $ pipenv lock
    Assuring all dependencies from Pipfile are installed...
    Locking [dev-packages] dependencies...
    Locking [packages] dependencies...
    Note: your project now has only default [packages] installed.
    To install [dev-packages], run: $ pipenv install --dev

### Install all dev dependencies:

    $ pipenv install --dev
    Pipfile found at /Users/kennethreitz/repos/kr/pip2/test/Pipfile. Considering this to be the project home.
    Pipfile.lock out of date, updating...
    Assuring all dependencies from Pipfile are installed...
    Locking [dev-packages] dependencies...
    Locking [packages] dependencies...

### Uninstall everything:

    $ pipenv uninstall --all
    No package provided, un-installing all dependencies.
    Found 25 installed package(s), purging...
    ...
    Environment now purged and fresh!

### Use the shell:

    $ pipenv shell
    Loading .env environment variables...
    Launching subshell in virtual environment. Type 'exit' or 'Ctrl+D' to return.
    $ ▯


### PURPOSE AND ADVANTAGES OF PIPENV

To understand the problems that Pipenv solves, it's useful to show how Python package management has evolved.

Take yourself back to the first Python iteration. We had Python, but there was no clean way to install packages.

Then came Easy Install, a package that installs other Python packages with relative ease. But it came with a catch: it wasn't easy to uninstall packages that were no longer needed.

Enter pip, which most Python users are familiar with. pip lets us install and uninstall packages. We could specify versions, run pip freeze > requirements.txt to output a list of installed packages to a text file, and use that same text file to install everything an app needed with pip install -r requirements.txt.

But pip didn't include a way to isolate packages from each other. We might work on apps that use different versions of the same libraries, so we needed a way to enable that.


Pipenv aims to solve several problems.
First, the problem of needing the pip library for package installation, plus a library for creating a virtual environment, plus a library for managing virtual environments, plus all the commands associated with those libraries. That's a lot to manage. Pipenv ships with package management and virtual environment support, so you can use one tool to install, uninstall, track, and document your dependencies and to create, use, and organize your virtual environments. When you start a project with it, Pipenv will automatically create a virtual environment for that project if you aren't already using one.

Pipenv accomplishes this dependency management by abandoning the requirements.txt norm and trading it for a new document called a Pipfile. When you install a library with Pipenv, a Pipfile for your project is automatically updated with the details of that installation, including version information and possibly the Git repository location, file path, and other information.

Second, Pipenv wants to make it easier to manage complex interdependencies.

Using Pipenv, which gives you Pipfile, lets you avoid these problems by managing dependencies for different environments for you. This command will install the main project dependencies:

 pipenv install

Adding the --dev tag will install the dev/testing requirements:

 pipenv install --dev
To generate a Pipfile.lock file, run:

pipenv lock

You can also run Python scripts with Pipenv. To run a top-level Python script called hello.py, run:

pipenv run python hello.py

And you will see your expected result in the console.

To start a shell, run:

pipenv shell

If you would like to convert a project that currently uses a requirements.txt file to use Pipenv, install Pipenv and run:

pipenv install requirements.txt

This will create a Pipfile and install the specified requirements.


Documentation
---------------

Documentation resides over at [pipenv.pypa.io](https://pipenv.pypa.io/en/latest/).

## Star History

<a href="https://star-history.com/#pypa/pipenv&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=pypa/pipenv&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=pypa/pipenv&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=pypa/pipenv&type=Date" />
  </picture>
</a>
