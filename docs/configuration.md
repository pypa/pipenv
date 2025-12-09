# Pipenv Configuration

This document covers the various ways to configure Pipenv's behavior through environment variables, configuration files, and command-line options.

## Environment Variables

Pipenv can be customized through environment variables, which is particularly useful for CI/CD pipelines, team-wide settings, or personal preferences.

### Setting Environment Variables

#### Temporary (Session-Only)

```bash
# Unix/Linux/macOS
$ export PIPENV_VENV_IN_PROJECT=1
$ pipenv install

# Windows (Command Prompt)
> set PIPENV_VENV_IN_PROJECT=1
> pipenv install

# Windows (PowerShell)
> $env:PIPENV_VENV_IN_PROJECT=1
> pipenv install
```

#### Permanent

For Unix/Linux/macOS, add to your shell profile (e.g., `~/.bashrc`, `~/.zshrc`):

```bash
export PIPENV_VENV_IN_PROJECT=1
```

For Windows, set through System Properties > Environment Variables.

### Boolean Options

To enable boolean options, set the variable to a true value: `"1"`, `"true"`, `"yes"`, or `"on"`.

To disable a boolean option, set it to a false value: `"0"`, `"false"`, `"no"`, or `"off"`.

### Available Environment Variables

#### Virtual Environment

| Variable | Description | Default |
|----------|-------------|---------|
| `PIPENV_VENV_IN_PROJECT` | Create virtualenv in project directory | `0` |
| `PIPENV_IGNORE_VIRTUALENVS` | Ignore active virtualenvs | `0` |
| `PIPENV_CUSTOM_VENV_NAME` | Use custom virtualenv name | None |
| `PIPENV_VIRTUALENV` | Path to virtualenv executable | Detected from system |
| `PIPENV_PYTHON` | Path to Python executable | Detected from system |
| `PIPENV_DEFAULT_PYTHON_VERSION` | Default Python version to use | System default |
| `VIRTUAL_ENV` | Current active virtualenv | None |

#### Installation and Dependencies

| Variable | Description | Default |
|----------|-------------|---------|
| `PIPENV_INSTALL_DEPENDENCIES` | Install package dependencies | `1` |
| `PIPENV_RESOLVE_VCS` | Resolve VCS dependencies | `1` |
| `PIPENV_SKIP_LOCK` | Skip lock when installing | `0` |
| `PIPENV_PYPI_MIRROR` | PyPI mirror URL | None |
| `PIPENV_MAX_DEPTH` | Maximum depth for dependency resolution | `10` |
| `PIPENV_TIMEOUT` | Timeout for pip operations | `15` |
| `PIPENV_INSTALL_TIMEOUT` | Timeout for package installation | `900` |

#### File Locations

| Variable | Description | Default |
|----------|-------------|---------|
| `PIPENV_PIPFILE` | Custom Pipfile location | `./Pipfile` |
| `PIPENV_CACHE_DIR` | Custom cache directory | `~/.cache/pipenv` |
| `PIPENV_DOTENV_LOCATION` | Custom .env file location | `./.env` |

#### Behavior

| Variable | Description | Default |
|----------|-------------|---------|
| `PIPENV_DONT_LOAD_ENV` | Don't load .env files | `0` |
| `PIPENV_DONT_USE_PYENV` | Don't use pyenv | `0` |
| `PIPENV_DONT_USE_ASDF` | Don't use asdf | `0` |
| `PIPENV_SHELL_FANCY` | Use fancy shell | `0` |
| `PIPENV_NOSPIN` | Disable spinner animation | `0` |
| `PIPENV_QUIET` | Quiet mode | `0` |
| `PIPENV_VERBOSE` | Verbose mode | `0` |
| `PIPENV_YES` | Yes to all prompts | `0` |
| `PIPENV_IGNORE_PIPFILE` | Ignore Pipfile, use only lock | `0` |
| `PIPENV_REQUESTS_TIMEOUT` | Timeout for HTTP requests | `10` |
| `PIPENV_CLEAR` | Clear caches on run | `0` |
| `PIPENV_SITE_PACKAGES` | Enable site-packages for virtualenv | `0` |

#### Security

| Variable | Description | Default |
|----------|-------------|---------|
| `PIPENV_PYUP_API_KEY` | PyUp.io API key for security checks | None |

### Examples

#### Store virtualenvs in the project directory

```bash
export PIPENV_VENV_IN_PROJECT=1
```

This creates a `.venv` directory in your project, making it easier to manage and find the virtualenv.

#### Use a custom Python version by default

```bash
export PIPENV_DEFAULT_PYTHON_VERSION=3.10
```

This sets Python 3.10 as the default when creating new environments.

#### Skip lock file generation during development

```bash
export PIPENV_SKIP_LOCK=1
```

This speeds up installation during development, but should not be used in production environments.

#### Use a PyPI mirror

```bash
export PIPENV_PYPI_MIRROR=https://mirrors.aliyun.com/pypi/simple/
```

This is useful in regions where accessing the official PyPI might be slow.

#### Increase timeout for large packages

```bash
export PIPENV_INSTALL_TIMEOUT=1800
```

This increases the timeout to 30 minutes for installing large packages.

## Configuration with pip

Pipenv uses pip under the hood, so you can also use pip's configuration options. These can be set through:

1. Environment variables (e.g., `PIP_TIMEOUT`, `PIP_INDEX_URL`)
2. pip configuration files (`pip.conf` or `pip.ini`)

### Common pip Environment Variables

| Variable | Description |
|----------|-------------|
| `PIP_INDEX_URL` | Base URL of the Python Package Index |
| `PIP_EXTRA_INDEX_URL` | Additional index URLs |
| `PIP_TRUSTED_HOST` | Mark a host as trusted |
| `PIP_RETRIES` | Number of retries for network operations |
| `PIP_TIMEOUT` | Timeout for HTTP requests |
| `PIP_DEFAULT_TIMEOUT` | Default timeout for HTTP requests |
| `PIP_FIND_LINKS` | Additional locations to find packages |
| `PIP_NO_CACHE_DIR` | Disable the cache |
| `PIP_CACHE_DIR` | Cache directory |

### Examples

#### Using a private package index

```bash
export PIP_INDEX_URL=https://private-repo.example.com/simple
export PIP_TRUSTED_HOST=private-repo.example.com
```

#### Passing additional options to pip

```bash
export PIP_INSTALL_OPTION="--no-deps"
```

#### Combining with Pipenv options

```bash
export PIP_INDEX_URL=https://private-repo.example.com/simple
export PIPENV_TIMEOUT=60
pipenv install requests
```

## Project-Specific Configuration

### Using .env Files

Pipenv automatically loads environment variables from `.env` files in your project directory. This is useful for project-specific settings:

```
# .env file
PIPENV_VENV_IN_PROJECT=1
PIP_INDEX_URL=https://private-repo.example.com/simple
```

### Custom .env Location

You can specify a custom location for your `.env` file:

```bash
export PIPENV_DOTENV_LOCATION=/path/to/custom/.env
pipenv shell
```

### Disabling .env Loading

If you don't want Pipenv to load `.env` files:

```bash
export PIPENV_DONT_LOAD_ENV=1
pipenv shell
```

## Command-Line Options

Many configuration options can also be set directly via command-line arguments, which take precedence over environment variables:

```bash
pipenv install --python 3.9 --site-packages
```

## Advanced Configuration

### Changing Cache Location

The default cache location is `~/.cache/pipenv` on Unix/Linux/macOS and `%LOCALAPPDATA%\pipenv\Cache` on Windows. You can change this:

```bash
export PIPENV_CACHE_DIR=/path/to/custom/cache
```

This is useful when:
- You have limited space in your home directory
- You want to share the cache across users
- You're working in an environment with restricted permissions

### Network Configuration in Restricted Environments

For environments with network restrictions:

```bash
# Increase timeout for slow connections
export PIPENV_TIMEOUT=60
export PIP_TIMEOUT=60

# Use a proxy
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080

# Specify trusted hosts that don't need HTTPS
export PIP_TRUSTED_HOST=internal-repo.example.com
```

### CI/CD Pipeline Configuration

For continuous integration environments:

```bash
# Non-interactive mode
export PIPENV_YES=1
export PIPENV_NOSPIN=1
export PIPENV_QUIET=1

# Fail if lock file is out of date
pipenv install --deploy
```

### Development vs. Production Settings

#### Development

```bash
# Development environment
export PIPENV_VENV_IN_PROJECT=1  # Keep virtualenv with project
export PIPENV_MAX_DEPTH=20        # Allow deeper dependency resolution
```

#### Production

```bash
# Production environment
export PIPENV_IGNORE_PIPFILE=1    # Use only the lock file
export PIPENV_NOSPIN=1            # Disable spinner for cleaner logs
pipenv install --deploy           # Fail if lock file is out of date
```

## Troubleshooting Configuration Issues

### Checking Current Configuration

To see what environment variables Pipenv is using:

```bash
pipenv --support
```

This shows all active Pipenv-related environment variables and their values.

### Common Configuration Problems

#### Virtualenv Creation Fails

If virtualenv creation fails, check:
- `PIPENV_PYTHON` points to a valid Python executable
- You have permissions to write to the virtualenv directory
- `PIPENV_VENV_IN_PROJECT=1` if you're in a directory with restricted permissions

#### Package Installation Timeouts

If package installations time out:
- Increase `PIPENV_TIMEOUT` and `PIPENV_INSTALL_TIMEOUT`
- Check network connectivity to PyPI or your custom index
- Consider using a PyPI mirror with `PIPENV_PYPI_MIRROR`

#### Lock File Generation Issues

If lock file generation fails:
- Ensure there are no conflicting dependencies
- Try `PIPENV_RESOLVE_VCS=0` if you have VCS dependencies causing issues
- Increase `PIPENV_MAX_DEPTH` for complex dependency trees

## Best Practices

1. **Version Control**: Don't commit environment-specific settings to version control. Use `.env` files that are excluded via `.gitignore`.

2. **Documentation**: Document required environment variables in your project's README.

3. **Consistency**: Use the same configuration across development, testing, and production environments when possible.

4. **Minimal Configuration**: Only set the variables you need to change from defaults.

5. **Security**: Be careful with security-sensitive settings like API keys. Use environment variables rather than committing them to files.
