# Pipenv Command Line Interface

This comprehensive guide covers Pipenv's command line interface, including all available commands, options, and usage examples.

## Overview

Pipenv provides a powerful command line interface (CLI) that simplifies Python dependency management and virtual environment workflows. The CLI follows a consistent pattern:

```bash
pipenv [OPTIONS] COMMAND [ARGS]...
```

## Global Options

These options can be used with any Pipenv command:

| Option | Description |
|--------|-------------|
| `--where` | Output project home information |
| `--venv` | Output virtualenv information |
| `--py` | Output Python interpreter information |
| `--envs` | Output environment variable options |
| `--rm` | Remove the virtualenv |
| `--bare` | Minimal output |
| `--man` | Display manpage |
| `--support` | Output diagnostic information for GitHub issues |
| `--site-packages` | Enable site-packages for the virtualenv |
| `--python TEXT` | Specify which Python version to use |
| `--clear` | Clear caches (pipenv, pip) |
| `-q, --quiet` | Quiet mode |
| `-v, --verbose` | Verbose mode |
| `--pypi-mirror TEXT` | Specify a PyPI mirror |
| `--version` | Show the version and exit |
| `-h, --help` | Show help message and exit |

## Core Commands

### install

Installs packages and adds them to Pipfile, or installs all packages from Pipfile.lock if no packages are specified.

```bash
pipenv install [OPTIONS] [PACKAGES]...
```

#### Options

| Option | Description |
|--------|-------------|
| `--dev` | Install both development and default packages |
| `--categories TEXT` | Install packages to specified category groups |
| `--system` | Install to system Python instead of virtualenv |
| `--deploy` | Abort if Pipfile.lock is out-of-date |
| `--ignore-pipfile` | Install from Pipfile.lock, ignoring Pipfile |
| `--skip-lock` | Skip locking of dependencies |
| `--requirements, -r TEXT` | Import a requirements.txt file |
| `--extra-pip-args TEXT` | Pass additional arguments to pip |
| `--python TEXT` | Specify which Python version to use |
| `--dry-run` | Show what would happen without making changes |

#### Examples

Install a specific package:
```bash
$ pipenv install requests
```

Install a package with version constraint:
```bash
$ pipenv install "requests>=2.20.0"
```

Install a development dependency:
```bash
$ pipenv install pytest --dev
```

Install from requirements.txt:
```bash
$ pipenv install -r requirements.txt
```

Install with deployment check:
```bash
$ pipenv install --deploy
```

### uninstall

Uninstalls a provided package and removes it from Pipfile.

```bash
pipenv uninstall [OPTIONS] [PACKAGES]...
```

#### Options

| Option | Description |
|--------|-------------|
| `--all` | Purge all files from the virtual environment |
| `--all-dev` | Remove all development packages |
| `--skip-lock` | Skip locking of dependencies |
| `--categories TEXT` | Uninstall from specified category groups |

#### Examples

Uninstall a package:
```bash
$ pipenv uninstall requests
```

Uninstall all packages:
```bash
$ pipenv uninstall --all
```

Uninstall all development packages:
```bash
$ pipenv uninstall --all-dev
```

### lock

Generates Pipfile.lock with all dependencies and their sub-dependencies.

```bash
pipenv lock [OPTIONS]
```

#### Options

| Option | Description |
|--------|-------------|
| `--pre` | Allow pre-releases |
| `--clear` | Clear the dependency cache |
| `--verbose` | Show verbose output |
| `--categories TEXT` | Lock specified categories only |
| `--keep-outdated` | Keep outdated dependencies |
| `--python TEXT` | Specify which Python version to use for resolution |
| `--extra-pip-args TEXT` | Pass additional arguments to pip |

#### Examples

Generate a lock file:
```bash
$ pipenv lock
```

Generate a lock file with pre-releases:
```bash
$ pipenv lock --pre
```

Lock specific categories:
```bash
$ pipenv lock --categories="docs,tests"
```

### sync

Installs all packages specified in Pipfile.lock.

```bash
pipenv sync [OPTIONS]
```

#### Options

| Option | Description |
|--------|-------------|
| `--dev` | Install both development and default packages |
| `--categories TEXT` | Install packages from specified category groups |
| `--python TEXT` | Specify which Python version to use |
| `--extra-pip-args TEXT` | Pass additional arguments to pip |

#### Examples

Install packages from lock file:
```bash
$ pipenv sync
```

Install development packages too:
```bash
$ pipenv sync --dev
```

Install specific categories:
```bash
$ pipenv sync --categories="docs,tests"
```

### update

Runs lock when no packages are specified, or upgrade for specific packages, and then sync.

```bash
pipenv update [OPTIONS] [PACKAGES]...
```

#### Options

| Option | Description |
|--------|-------------|
| `--dev` | Update development packages |
| `--categories TEXT` | Update packages in specified categories |
| `--outdated` | List out-of-date dependencies |
| `--dry-run` | Show what would happen without making changes |
| `--python TEXT` | Specify which Python version to use |
| `--clear` | Clear the dependency cache |

#### Examples

Update all packages:
```bash
$ pipenv update
```

Update specific packages:
```bash
$ pipenv update requests pytest
```

Check for outdated packages:
```bash
$ pipenv update --outdated
```

### upgrade

Updates the lock file for specified dependencies without installing them.

```bash
pipenv upgrade [OPTIONS] [PACKAGES]...
```

#### Options

| Option | Description |
|--------|-------------|
| `--dev` | Upgrade development packages |
| `--categories TEXT` | Upgrade packages in specified categories |
| `--dry-run` | Show what would happen without making changes |
| `--python TEXT` | Specify which Python version to use |
| `--clear` | Clear the dependency cache |

#### Examples

Upgrade a specific package in the lock file:
```bash
$ pipenv upgrade requests
```

Upgrade development packages:
```bash
$ pipenv upgrade --dev
```

### check

Checks for security vulnerabilities and PEP 508 marker compliance.

```bash
pipenv check [OPTIONS]
```
**Note**: The check command is deprecated and will be unsupported beyond 01 June 2025. In future versions, the check command will run the scan command by default. Use the `--scan` option to run the new scan command now.

#### Options

| Option | Description |
|--------|-------------|
| `--db TEXT` | Path or URL to a PyUp Safety vulnerabilities database |
| `--ignore, -i TEXT` | Ignore specified vulnerability |
| `--output [screen\|text\|json\|bare]` | Specify output format |
| `--key TEXT` | Safety API key from PyUp.io |
| `--use-installed` | Use installed packages instead of lockfile |
| `--categories TEXT` | Check packages in specified categories |
| `--auto-install` | Automatically install safety if not already installed |
| `--scan` | Use the new scan command instead |

#### Examples

Check for vulnerabilities:
```bash
$ pipenv check
```

Check with a specific output format:
```bash
$ pipenv check --output json
```

Use the new scan command:
```bash
$ pipenv check --scan
```

### scan

Enhanced security scanning (replacement for check).

```bash
pipenv scan [OPTIONS]
```

#### Options

Similar to the `check` command, with enhanced functionality.

#### Examples

Scan for vulnerabilities:
```bash
$ pipenv scan
```

Scan with a specific output format:
```bash
$ pipenv scan --output json
```

### run

Spawns a command installed into the virtualenv.

```bash
pipenv run [OPTIONS] COMMAND [ARGS]...
```

#### Examples

Run a Python script:
```bash
$ pipenv run python app.py
```

Run tests:
```bash
$ pipenv run pytest
```

Run a custom script defined in Pipfile:
```bash
$ pipenv run start
```

### shell

Spawns a shell within the virtualenv.

```bash
pipenv shell [OPTIONS] [SHELL_ARGS]...
```

#### Options

| Option | Description |
|--------|-------------|
| `--fancy` | Use a fancy shell activation method |

#### Examples

Activate the virtual environment:
```bash
$ pipenv shell
```

Activate with fancy mode:
```bash
$ pipenv shell --fancy
```

### graph

Displays currently-installed dependency graph information.

```bash
pipenv graph [OPTIONS]
```

#### Options

| Option | Description |
|--------|-------------|
| `--bare` | Output graph in bare format |
| `--json` | Output graph in JSON format |
| `--json-tree` | Output graph as JSON tree |
| `--reverse` | Reversed dependency graph |

#### Examples

Show dependency graph:
```bash
$ pipenv graph
```

Show reverse dependencies:
```bash
$ pipenv graph --reverse
```

Show JSON output:
```bash
$ pipenv graph --json
```

### clean

Uninstalls all packages not specified in Pipfile.lock.

```bash
pipenv clean [OPTIONS]
```

#### Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Show what would be removed without removing |

#### Examples

Remove unused packages:
```bash
$ pipenv clean
```

Preview what would be removed:
```bash
$ pipenv clean --dry-run
```

### requirements

Generate a requirements.txt from Pipfile.lock.

```bash
pipenv requirements [OPTIONS]
```

#### Options

| Option | Description |
|--------|-------------|
| `--dev` | Include development packages |
| `--dev-only` | Only include development packages |
| `--hash` | Include package hashes |
| `--exclude-markers` | Exclude PEP 508 markers |
| `--categories TEXT` | Include packages from specified categories |

#### Examples

Generate requirements.txt:
```bash
$ pipenv requirements > requirements.txt
```

Include development packages:
```bash
$ pipenv requirements --dev > requirements-dev.txt
```

Include hashes:
```bash
$ pipenv requirements --hash > requirements.txt
```

### scripts

Lists scripts defined in the current environment config.

```bash
pipenv scripts [OPTIONS]
```

#### Examples

List available scripts:
```bash
$ pipenv scripts
```

### open

Opens a Python module in your editor.

```bash
pipenv open [OPTIONS] MODULE
```

#### Examples

Open the requests module:
```bash
$ pipenv open requests
```

Open with a specific editor:
```bash
$ EDITOR=code pipenv open requests
```

### verify

Verifies that the Pipfile.lock is up-to-date with the Pipfile.

```bash
pipenv verify [OPTIONS]
```

#### Examples

Verify lock file integrity:
```bash
$ pipenv verify
```

## Environment Variables

Pipenv's behavior can be customized through environment variables. Here are some commonly used ones:

| Variable | Description |
|----------|-------------|
| `PIPENV_VENV_IN_PROJECT` | Create virtualenv in project directory |
| `PIPENV_IGNORE_VIRTUALENVS` | Ignore active virtualenvs |
| `PIPENV_PIPFILE` | Custom Pipfile location |
| `PIPENV_DOTENV_LOCATION` | Custom .env file location |
| `PIPENV_CACHE_DIR` | Custom cache directory |
| `PIPENV_TIMEOUT` | Timeout for pip operations |
| `PIPENV_SKIP_LOCK` | Skip lock file generation |
| `PIPENV_PYPI_MIRROR` | PyPI mirror URL |
| `PIPENV_MAX_DEPTH` | Maximum depth for dependency resolution |
| `PIPENV_DONT_LOAD_ENV` | Don't load .env files |

For a complete list, see the [Configuration](configuration.md) page.

## Command Relationships

Understanding how Pipenv commands relate to each other can help you use them more effectively:

- `install`: Adds packages to Pipfile and updates Pipfile.lock
- `lock`: Updates Pipfile.lock without installing packages
- `sync`: Installs packages from Pipfile.lock without modifying it
- `update`: Combines `lock` and `sync` (or `upgrade` and `sync` for specific packages)
- `upgrade`: Updates Pipfile.lock for specific packages without installing them
- `uninstall`: Removes packages from virtualenv and Pipfile
- `clean`: Removes packages from virtualenv that aren't in Pipfile.lock

## Best Practices

### CI/CD Pipelines

For continuous integration and deployment:

```bash
# Verify the lock file is up-to-date
$ pipenv verify

# Install dependencies
$ pipenv sync --dev

# Run tests
$ pipenv run pytest
```

### Production Deployment

For production environments:

```bash
# Install only production dependencies
$ pipenv install --deploy

# Or for systems without virtualenv support
$ pipenv install --system --deploy
```

### Development Workflow

For daily development:

```bash
# Install dependencies including development packages
$ pipenv install --dev

# Activate environment
$ pipenv shell

# Run your application
$ python app.py
```

## Troubleshooting

### Common Issues

- **Command not found**: Ensure Pipenv is installed and in your PATH
- **Pipfile not found**: Run commands from your project directory
- **Lock file out of date**: Run `pipenv lock` to update it
- **Dependency conflicts**: Try `pipenv lock --clear` to clear the cache

For more troubleshooting tips, see the [Troubleshooting](troubleshooting.md) guide.

## Conclusion

Pipenv's CLI provides a comprehensive set of commands for managing Python dependencies and virtual environments. By understanding these commands and their options, you can streamline your Python development workflow and ensure consistent, reproducible environments.
