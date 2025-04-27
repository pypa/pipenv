# Pipenv Commands Reference

This document provides a comprehensive reference for all Pipenv commands, including detailed explanations, options, and practical examples.

## Core Commands Overview

| Command | Description |
|---------|-------------|
| `install` | Install packages or create/update virtual environment |
| `uninstall` | Remove packages from virtual environment and Pipfile |
| `lock` | Generate Pipfile.lock with dependencies and hashes |
| `sync` | Install packages from Pipfile.lock without modifying the lockfile |
| `update` | Update dependencies and install them (lock + sync) |
| `upgrade` | Update the lock of specified dependencies without installing |
| `check` | Check for security vulnerabilities and PEP 508 compliance (use `--scan` for enhanced scanning) |
| `shell` | Spawn a shell within the virtual environment |
| `run` | Run a command within the virtual environment |
| `graph` | Display dependency graph information |
| `clean` | Remove packages not specified in Pipfile.lock |
| `verify` | Verify the Pipfile.lock hash is up-to-date |
| `requirements` | Generate a requirements.txt from Pipfile.lock |
| `scripts` | List scripts defined in the environment |
| `open` | Open a Python module in your editor |

## install

The `install` command is used for installing packages into the Pipenv virtual environment and updating your Pipfile and Pipfile.lock.

### Basic Usage

```bash
$ pipenv install [package_name]
```

When run without arguments, `pipenv install` will create a virtual environment if one doesn't exist, and install all packages specified in the Pipfile.

When a package name is provided, it will install that package, add it to the Pipfile, and update the Pipfile.lock.

### Examples

Install a specific package:

```bash
$ pipenv install requests
```

Install a package with version constraint:

```bash
$ pipenv install "requests>=2.20.0"
```

Install a package from a Git repository:

```bash
$ pipenv install -e git+https://github.com/requests/requests.git@master#egg=requests
```

Install a package as a development dependency:

```bash
$ pipenv install pytest --dev
```

Install packages from a requirements.txt file:

```bash
$ pipenv install -r requirements.txt
```

### Options

| Option | Description |
|--------|-------------|
| `--dev` | Install both development and default packages from Pipfile |
| `--categories` | Install packages to the specified category groups |
| `--deploy` | Abort if Pipfile.lock is out-of-date |
| `--ignore-pipfile` | Install from Pipfile.lock, ignoring Pipfile |
| `--system` | Install to system Python instead of virtual environment |
| `--python` | Specify which Python version to use |
| `--requirements, -r` | Import a requirements.txt file |
| `--extra-pip-args` | Pass additional arguments to pip |

### Important Note

Prior to Pipenv 2024, the `install` command would relock the lock file every time it was run. Based on user feedback, this behavior was changed so that `install` only updates the lock when adding or changing a package. To relock the entire set of Pipfile specifiers, use `pipenv lock`.

## sync

The `sync` command installs dependencies from the Pipfile.lock without making any changes to the lockfile. This is useful for deployment scenarios where you want to ensure exact package versions are installed.

### Basic Usage

```bash
$ pipenv sync
```

### Examples

Install only default packages:

```bash
$ pipenv sync
```

Install both default and development packages:

```bash
$ pipenv sync --dev
```

Install specific package categories:

```bash
$ pipenv sync --categories="tests,docs"
```

### Options

| Option | Description |
|--------|-------------|
| `--dev` | Install both development and default packages |
| `--categories` | Install packages from specified category groups |

## uninstall

The `uninstall` command removes packages from your virtual environment and Pipfile.

### Basic Usage

```bash
$ pipenv uninstall [package_name]
```

### Examples

Uninstall a specific package:

```bash
$ pipenv uninstall requests
```

Uninstall multiple packages:

```bash
$ pipenv uninstall requests pytest
```

Uninstall all packages:

```bash
$ pipenv uninstall --all
```

Uninstall all development packages:

```bash
$ pipenv uninstall --all-dev
```

Uninstall a dev package using --dev flag:

```bash
$ pipenv uninstall ruff --dev
```

### Options

| Option | Description |
|--------|-------------|
| `--all` | Remove all packages from virtual environment |
| `--all-dev` | Remove all development packages |
| `--dev` | Uninstall package from dev-packages section |
| `--categories` | Specify which categories to uninstall from |
| `--skip-lock` | Don't update Pipfile.lock after uninstalling |

## lock

The `lock` command generates a Pipfile.lock file, which contains all dependencies (including sub-dependencies) with their exact versions and hashes.

### Basic Usage

```bash
$ pipenv lock
```

### Examples

Generate a lockfile including pre-release versions:

```bash
$ pipenv lock --pre
```

Generate a lockfile for a specific Python version:

```bash
$ pipenv lock --python 3.9
```

### Options

| Option | Description |
|--------|-------------|
| `--pre` | Allow pre-releases to be pinned |
| `--clear` | Clear the dependency cache |
| `--python` | Specify which Python version to use for resolution |
| `--categories` | Lock specified categories only |

## update

The `update` command runs `lock` when no packages are specified, or `upgrade` for specific packages, and then runs `sync` to install the updated packages.

### Basic Usage

```bash
$ pipenv update [package_name]
```

### Examples

Update all packages:

```bash
$ pipenv update
```

Update specific packages:

```bash
$ pipenv update requests pytest
```

Check for outdated packages without updating:

```bash
$ pipenv update --outdated
```

### Options

| Option | Description |
|--------|-------------|
| `--outdated` | List out-of-date dependencies |
| `--dev` | Update development packages |
| `--categories` | Update packages in specified categories |

## upgrade

The `upgrade` command updates the lock file for specified dependencies and their sub-dependencies, but does not install the updated packages.

### Basic Usage

```bash
$ pipenv upgrade [package_name]
```

### Examples

Upgrade a specific package in the lock file:

```bash
$ pipenv upgrade requests
```

Upgrade multiple packages:

```bash
$ pipenv upgrade requests pytest
```

### Options

| Option | Description |
|--------|-------------|
| `--dev` | Upgrade development packages |
| `--categories` | Upgrade packages in specified categories |

## check

The `check` command checks for security vulnerabilities in your dependencies and verifies that your environment meets PEP 508 requirements.

### Basic Usage

```bash
$ pipenv check
```

### Examples

Check with a specific vulnerability database:

```bash
$ pipenv check --db /path/to/db
```

Check with a specific output format:

```bash
$ pipenv check --output json
```

### Options

| Option | Description |
|--------|-------------|
| `--db` | Path or URL to a PyUp Safety vulnerabilities database |
| `--ignore, -i` | Ignore specified vulnerability |
| `--output` | Specify output format (screen, text, json, bare) |
| `--key` | Safety API key from PyUp.io |
| `--use-installed` | Use installed packages instead of lockfile |
| `--categories` | Check packages in specified categories |
| `--auto-install` | Automatically install safety if not already installed |
| `--scan` | Enable the newer version of the check command with improved functionality. |

**Note**: The check command is deprecated and will be unsupported beyond June 1, 2025. Use `pipenv check --scan` for enhanced security scanning.

## run

The `run` command executes a command within the context of the virtual environment.

### Basic Usage

```bash
$ pipenv run [command]
```

### Examples

Run a Python script:

```bash
$ pipenv run python main.py
```

Run a test suite:

```bash
$ pipenv run pytest
```

Run a custom script defined in Pipfile:

```bash
$ pipenv run start
```

## shell

The `shell` command spawns a shell within the virtual environment, allowing you to interact with your installed packages.

### Basic Usage

```bash
$ pipenv shell
```

### Examples

Activate the shell with a specific shell program:

```bash
$ pipenv shell --fancy
```

### Options

| Option | Description |
|--------|-------------|
| `--fancy` | Use a fancy shell activation method |

## graph

The `graph` command displays a dependency graph of your installed packages.

### Basic Usage

```bash
$ pipenv graph
```


### Examples

Show a dependency graph with reverse dependencies:

```bash
$ pipenv graph --reverse
```

### Options

| Option | Description |
|--------|-------------|
| `--bare` | Output graph in bare format |
| `--json` | Output graph in JSON format |
| `--json-tree` | Output graph as JSON tree |
| `--reverse` | Reversed dependency graph |

## requirements

The `requirements` command generates a requirements.txt file from your Pipfile.lock.

### Basic Usage

```bash
$ pipenv requirements
```

### Examples

Generate requirements with hashes:

```bash
$ pipenv requirements --hash
```

Generate requirements for development packages only:

```bash
$ pipenv requirements --dev-only
```

Generate requirements for specific categories:

```bash
$ pipenv requirements --categories="tests,docs"
```

### Options

| Option | Description |
|--------|-------------|
| `--dev` | Include development packages |
| `--dev-only` | Only include development packages |
| `--hash` | Include package hashes |
| `--exclude-markers` | Exclude PEP 508 markers |
| `--categories` | Include packages from specified categories |

## clean

The `clean` command uninstalls all packages not specified in Pipfile.lock.

### Basic Usage

```bash
$ pipenv clean
```

### Examples

Dry run to see what would be removed:

```bash
$ pipenv clean --dry-run
```

### Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Show what would be removed without removing |

## verify

The `verify` command checks that the Pipfile.lock is up-to-date with the Pipfile.

### Basic Usage

```bash
$ pipenv verify
```

This command is useful in CI/CD pipelines to ensure that the lock file is synchronized with the Pipfile before deployment.

## scripts

The `scripts` command lists scripts defined in the current environment configuration.

### Basic Usage

```bash
$ pipenv scripts
```

## open

The `open` command opens a Python module in your editor.

### Basic Usage

```bash
$ pipenv open [module_name]
```

### Examples

Open the requests module in your editor:

```bash
$ pipenv open requests
```

**Note**: This command uses the `EDITOR` environment variable to determine which editor to use.
