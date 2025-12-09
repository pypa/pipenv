# Pipenv: Python Development Workflow for Humans

[![pypi version](https://img.shields.io/pypi/v/pipenv.svg)](https://pypi.python.org/pypi/pipenv) [![MIT License](https://img.shields.io/pypi/l/pipenv.svg)](https://pypi.python.org/pypi/pipenv) [![Supported Versions](https://img.shields.io/pypi/pyversions/pipenv.svg)](https://pypi.python.org/pypi/pipenv)

## What is Pipenv?

**Pipenv** is a Python virtualenv management tool that combines pip, virtualenv, and Pipfile into a single unified interface. It creates and manages virtual environments for your projects automatically, while also maintaining a `Pipfile` for package requirements and a `Pipfile.lock` for deterministic builds.

*Linux, macOS, and Windows are all first-class citizens in Pipenv.*

## Why Use Pipenv?

Pipenv solves several critical problems in the Python development workflow:

- **Simplified Dependency Management**: No need to use `pip` and `virtualenv` separately—they work together seamlessly.
- **Deterministic Builds**: The `Pipfile.lock` ensures that the exact same environment can be reproduced across different systems.
- **Security First**: Package hashes are documented in the lock file and verified during installation, preventing supply chain attacks.
- **Dependency Visibility**: Easily visualize your dependency graph with `pipenv graph`.
- **Environment Isolation**: Each project gets its own isolated virtual environment, preventing dependency conflicts.
- **Development Workflow Integration**: Support for local customizations with `.env` files and development vs. production dependencies.
- **Latest Dependency Versions**: Encourages the use of up-to-date dependencies to minimize security vulnerabilities.

## Key Features

- **Deterministic Builds**: Generates and checks file hashes for locked dependencies.
- **Python Version Management**: Automatically installs required Python version when `pyenv` or `asdf` is available.
- **Project-Centric Workflow**: Automatically finds your project home by looking for a `Pipfile`.
- **Automatic Environment Creation**: Creates a virtualenv in a standard location when one doesn't exist.
- **Simplified Package Management**: Automatically adds/removes packages to a `Pipfile` when they are installed or uninstalled.
- **Environment Variable Management**: Automatically loads `.env` files to support customization and overrides.
- **Package Categories**: Support for organizing dependencies into different groups beyond just default and development packages.

## Quick Start

### Installation

The recommended way to install pipenv on most platforms is to install from PyPI using `pip`:

```bash
$ pip install --user pipenv
```

For more detailed installation instructions, see the [Installing Pipenv](installation) chapter.

### Basic Usage

Create a new project:

```bash
$ mkdir my_project && cd my_project
$ pipenv install
```

Install packages:

```bash
$ pipenv install requests
```

Create a Python file (e.g., `main.py`):

```python
import requests

response = requests.get('https://httpbin.org/ip')
print(f'Your IP is {response.json()["origin"]}')
```

Run your script:

```bash
$ pipenv run python main.py
```

Activate the virtual environment:

```bash
$ pipenv shell
```

## Pipenv Documentation

```{toctree}
---
caption: Pipenv Documentation
maxdepth: 2
---
installation
quick_start
faq
migrating
pipfile
cli
commands
configuration
virtualenv
workflows
best_practices
security
troubleshooting
specifiers
indexes
credentials
shell
docker
scripts
pylock
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

✨🍰✨
