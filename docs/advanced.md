# Advanced Pipenv Usage

This guide covers advanced features and techniques for using Pipenv effectively in complex scenarios. These topics build on the basic functionality covered in other documentation sections.

## Passing Additional Arguments to pip

When you need more control over the underlying pip commands that Pipenv executes, you can pass additional arguments directly to pip.

### Using --extra-pip-args

The `--extra-pip-args` option allows you to supply additional arguments to pip during installation:

```bash
$ pipenv install --extra-pip-args="--use-feature=truststore --proxy=127.0.0.1"
```

This is particularly useful for:

- Using experimental pip features
- Configuring proxies
- Setting build options for packages with C extensions
- Controlling cache behavior
- Specifying platform-specific wheels

### Common Use Cases

#### Using System Certificate Stores

```bash
$ pipenv install --extra-pip-args="--use-feature=truststore"
```

#### Installing Platform-Specific Packages

```bash
$ pipenv install --extra-pip-args="--platform=win_amd64 --only-binary=:all:"
```

#### Setting Build Options

```bash
$ pipenv install pycurl --extra-pip-args="--global-option=--with-openssl-dir=/usr/local/opt/openssl"
```

## Deployment Strategies

Pipenv provides several approaches for deploying applications in production environments.

### Using --deploy Flag

The `--deploy` flag ensures that your `Pipfile.lock` is up-to-date with your `Pipfile` before installation:

```bash
$ pipenv install --deploy
```

This will fail if:
- The `Pipfile.lock` is out of date
- The `Pipfile.lock` is missing
- The hash in `Pipfile.lock` doesn't match the `Pipfile`

This is crucial for production deployments to ensure you're installing exactly what you expect.

### System-Wide Installation

For some deployment scenarios (like containerized applications), you may want to install packages directly to the system Python rather than in a virtual environment:

```bash
$ pipenv install --system --deploy
```

This installs all packages specified in `Pipfile.lock` to the system Python. Use this approach with caution, as it can potentially conflict with system packages.

### Verifying Lock File Without Installing

To verify that your `Pipfile.lock` is up-to-date without installing packages:

```bash
$ pipenv verify
```

This is useful in CI/CD pipelines to ensure the lock file has been properly updated after changes to the `Pipfile`.

### Docker Deployment

For Docker deployments, a multi-stage build approach is recommended:

```dockerfile
FROM python:3.10-slim AS builder

WORKDIR /app

# Copy dependency files
COPY Pipfile Pipfile.lock ./

# Install pipenv and dependencies
RUN pip install pipenv && \
    pipenv install --deploy --system

FROM python:3.10-slim

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages

# Copy application code
COPY . .

# Run the application
CMD ["python", "app.py"]
```

This approach:
1. Installs dependencies in a builder stage
2. Copies only the necessary files to the final image
3. Results in a smaller, more secure image

## Working with Different Python Distributions

Pipenv can work with various Python distributions and installations.

### Using Specific Python Interpreters

To use a specific Python interpreter:

```bash
$ pipenv --python /path/to/python
```

This is useful when you have multiple Python versions installed or need to use a specific distribution.

### Anaconda/Conda Integration

To use Pipenv with Anaconda:

```bash
$ pipenv --python /path/to/anaconda/bin/python
```

To reuse Conda-installed packages:

```bash
$ pipenv --python /path/to/anaconda/bin/python --site-packages
```

The `--site-packages` flag allows the virtual environment to access packages installed in the system Python.

### pyenv Integration

Pipenv automatically detects and works with pyenv:

```bash
# Set local Python version with pyenv
$ pyenv local 3.10.4

# Pipenv will use this version automatically
$ pipenv install
```

If the specified Python version isn't installed, Pipenv will prompt you to install it with pyenv:

```bash
$ pipenv --python 3.11
Warning: Python 3.11 was not found on your system...
Would you like us to install latest CPython 3.11 with pyenv? [Y/n]: y
Installing CPython 3.11.0 with pyenv...
```

### asdf Integration

Similar to pyenv, Pipenv also works with asdf:

```bash
# Install Python with asdf
$ asdf install python 3.10.4

# Use this version with Pipenv
$ pipenv --python 3.10.4
```

## Generating Requirements Files

While Pipenv uses `Pipfile` and `Pipfile.lock`, you may need to generate traditional `requirements.txt` files for compatibility with other tools.

### Basic Requirements Generation

```bash
$ pipenv requirements > requirements.txt
```

This generates a `requirements.txt` file from your `Pipfile.lock` with exact versions.

### Including Development Dependencies

```bash
$ pipenv requirements --dev > requirements-dev.txt
```

### Development Dependencies Only

```bash
$ pipenv requirements --dev-only > dev-requirements.txt
```

### Including Hashes

```bash
$ pipenv requirements --hash > requirements.txt
```

This includes package hashes for additional security.

### Excluding PEP 508 Markers

```bash
$ pipenv requirements --exclude-markers > requirements.txt
```

This removes environment markers (like `python_version >= '3.7'`).

### Specific Package Categories

```bash
$ pipenv requirements --categories="docs,tests" > requirements-docs-tests.txt
```

This generates requirements for specific custom package categories.

## Security Features

Pipenv includes several advanced security features to help protect your projects.

### Vulnerability Scanning

Pipenv integrates with the [safety](https://github.com/pyupio/safety) package to scan for known vulnerabilities:

```bash
$ pipenv scan
```

This checks your dependencies against the PyUp Safety database of known vulnerabilities.

#### Using a Custom Vulnerability Database

```bash
$ pipenv scan --db /path/to/custom/db
```

#### Ignoring Specific Vulnerabilities

```bash
$ pipenv scan --ignore 12345
```

#### Different Output Formats

```bash
$ pipenv scan --output json > vulnerabilities.json
```

### Automatic Python Installation

Pipenv can automatically install the required Python version if you have pyenv or asdf installed:

```toml
# Pipfile
[requires]
python_version = "3.11"
```

When you run `pipenv install`, it will check if Python 3.11 is available and prompt to install it if needed.

## Custom Scripts

Pipenv allows you to define custom scripts in your `Pipfile` for common tasks.

### Defining Scripts

```toml
[scripts]
start = "python app.py"
test = "pytest"
lint = "flake8 ."
format = "black ."
```

### Running Scripts

```bash
$ pipenv run start
$ pipenv run test
```

### Script with Arguments

```bash
$ pipenv run test tests/test_api.py -v
```

### Complex Script Definitions

You can define more complex scripts using the extended syntax:

```toml
[scripts]
start = {cmd = "python app.py"}
complex = {call = "package.module:function('arg1', 'arg2')"}
```

## Environment Variables and Configuration

### Automatic Loading of .env

Pipenv automatically loads environment variables from `.env` files in your project directory:

```
# .env
DEBUG=True
DATABASE_URL=postgresql://user:password@localhost/dbname
```

These variables are available when you run `pipenv shell` or `pipenv run`.

### Custom .env Location

```bash
$ PIPENV_DOTENV_LOCATION=/path/to/.env pipenv shell
```

### Variable Expansion in .env

You can use variable expansion in your `.env` files:

```
# .env
HOME_DIR=${HOME}
CONFIG_PATH=${HOME_DIR}/.config/app
```

## Working with Air-Gapped Environments

In environments without internet access, you can still use Pipenv by preparing packages in advance.

### Downloading Packages

On a connected system:

```bash
# Generate requirements with hashes
$ pipenv requirements --hash > requirements.txt

# Download packages
$ pip download -r requirements.txt -d ./packages
```

### Installing in Air-Gapped Environment

Transfer the packages directory to the air-gapped environment, then:

```bash
$ pip install --no-index --find-links=./packages -r requirements.txt
```

## Testing and CI/CD Integration

### Using Pipenv with tox

Here's an example `tox.ini` for testing with multiple Python versions:

```ini
[tox]
envlist = py37, py38, py39, py310, py311

[testenv]
deps = pipenv
commands =
    pipenv install --dev
    pipenv run pytest {posargs:tests}
```

### GitHub Actions Integration

```yaml
name: Python Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.8', '3.9', '3.10', '3.11']

    steps:
    - uses: actions/checkout@v3
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install pipenv
        pipenv install --dev
    - name: Verify lock file
      run: pipenv verify
    - name: Run tests
      run: pipenv run pytest
    - name: Security scan
      run: pipenv scan
```

## Performance Optimization

### Caching

Pipenv maintains a cache to speed up installations. You can control this cache:

```bash
# Clear the cache
$ pipenv lock --clear

# Set a custom cache location
$ export PIPENV_CACHE_DIR=/path/to/custom/cache
```

### Speeding Up Installations

For faster installations during development:

```bash
# Skip lock file generation
$ export PIPENV_SKIP_LOCK=1
$ pipenv install package-name
```

```{warning}
Only use PIPENV_SKIP_LOCK during development, not in production environments.
```

### Handling Large Dependency Trees

For projects with many dependencies:

```bash
# Increase the maximum depth for dependency resolution
$ export PIPENV_MAX_DEPTH=20
$ pipenv lock
```

## Community Integrations

Pipenv works well with various tools and services in the Python ecosystem:

- **Heroku**: Automatically detects and uses Pipfile/Pipfile.lock
- **Platform.sh**: Native support for Pipenv projects
- **PyUp**: Security monitoring for Pipenv projects
- **VS Code**: Built-in support for Pipenv environments
- **PyCharm**: Supports Pipenv for project environments
- **Emacs**: Integration via pipenv.el
- **Fish Shell**: Automatic shell activation

## Opening Modules in Your Editor

Pipenv allows you to quickly open installed packages in your editor:

```bash
$ pipenv open requests
```

This opens the source code of the requests package in your default editor (defined by the `EDITOR` environment variable).

You can specify a different editor for a one-time use:

```bash
$ EDITOR=code pipenv open flask
```

This is useful for:
- Exploring package source code
- Debugging issues
- Understanding how a package works
- Adding temporary patches

## Conclusion

These advanced features make Pipenv a powerful tool for Python dependency management in complex scenarios. By leveraging these capabilities, you can create more efficient, secure, and maintainable Python projects.

Remember that while these advanced features provide additional flexibility and power, they should be used judiciously. Always follow best practices for security and reproducibility, especially in production environments.
