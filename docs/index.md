# Pipenv: Python Dev Workflow for Humans
[![pypi version](https://img.shields.io/pypi/v/pipenv.svg)](https://pypi.python.org/pypi/pipenv) [![MIT License](https://img.shields.io/pypi/l/pipenv.svg)](https://pypi.python.org/pypi/pipenv) [![Supported Versions](https://img.shields.io/pypi/pyversions/pipenv.svg)](https://pypi.python.org/pypi/pipenv)

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


## Install Pipenv Today!

The recommended way to install pipenv on most platforms is to install from pypi using `pip`:

    $ pip install --user pipenv

More detailed installation instructions can be found in the [installing Pipenv](installation) chapter.

✨🍰✨

## Pipenv Features

- Enables truly *deterministic builds*, while easily specifying *only what you want*.
- Generates and checks file hashes for locked dependencies when installing from `Pipfile.lock`.
- Automatically installs required Python version when `pyenv` is available.
- Automatically finds your project home, recursively, by looking for a `Pipfile`.
- Automatically generates a `Pipfile`, if one doesn't exist.
- Automatically creates a virtualenv in a standard customizable location.
- Automatically adds/removes packages to a `Pipfile` when they are installed or uninstalled.
- Automatically loads `.env` files to support customization and overrides.



## Pipenv Documentation

```{toctree}
---
caption: Pipenv Documentation
maxdepth: 2
---
installation
pipfile
cli
commands
configuration
virtualenv
workflows
specifiers
indexes
credentials
shell
docker
scripts
advanced
diagnose
changelog
```

## Contribution Guides

```{toctree}
---
caption: Contributing to Pipenv
maxdepth: 2
---
dev/contributing
```
