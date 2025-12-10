# Installing Pipenv

This guide provides comprehensive instructions for installing Pipenv on various platforms and environments. Follow the approach that best suits your system and requirements.

## Prerequisites

Before installing Pipenv, ensure you have Python and pip available on your system.

### Verifying Python Installation

Check that Python is installed and available from your command line:

```bash
$ python --version
Python 3.10.4
```

You should see output showing your Python version. If you don't have Python installed, download and install the latest version from [python.org](https://python.org).

### Verifying pip Installation

Ensure pip is available:

```bash
$ pip --version
pip 22.1.2
```

If pip is not installed, you can install it following the [pip installation guide](https://pip.pypa.io/en/stable/installation/).

## Installation Methods

### Recommended: Isolated Virtual Environment Installation

Modern Python installations (Python 3.11+ on recent Linux distributions like Ubuntu 24.04, Fedora 38+) enforce [PEP 668](https://peps.python.org/pep-0668/), which prevents installing packages with `pip install --user`. The recommended approach is to install Pipenv in its own isolated virtual environment.

#### Option 1: Dedicated Pipenv Virtual Environment (Recommended)

Create a dedicated virtual environment for pipenv that auto-activates in your shell:

```bash
# Create a dedicated venv for pipenv
$ python3 -m venv ~/.pipenv-venv

# Install pipenv in this venv
$ ~/.pipenv-venv/bin/pip install pipenv

# Add to your shell configuration (~/.bashrc, ~/.zshrc, or ~/.profile)
$ echo 'export PIPENV_IGNORE_VIRTUALENVS=1' >> ~/.bashrc
$ echo 'export PATH="$HOME/.pipenv-venv/bin:$PATH"' >> ~/.bashrc

# Reload your shell
$ source ~/.bashrc
```

The `PIPENV_IGNORE_VIRTUALENVS=1` setting ensures pipenv still creates and manages separate virtual environments for your projects.

#### Option 2: Per-Project Bootstrap

For CI/CD or when you want pipenv isolated per-project:

```bash
$ python3 -m venv .venv
$ source .venv/bin/activate  # On Windows: .venv\Scripts\activate
$ pip install pipenv
$ pipenv install
```

### Legacy: User Installation

On older systems that don't enforce PEP 668, you can still use user installation:

```bash
$ pip install --user pipenv
```

```{warning}
This method no longer works on modern Linux distributions (Ubuntu 24.04+, Fedora 38+) due to PEP 668. Use the isolated virtual environment approach above instead.
```

### Adding Pipenv to PATH

If you used the legacy `--user` installation, you may need to add the user site-packages binary directory to your PATH.

#### On Linux and macOS

Find the user base binary directory:

```bash
$ python -m site --user-base
/home/username/.local
```

Add the `bin` directory to your PATH by adding this line to your shell configuration file (e.g., `~/.bashrc`, `~/.zshrc`, or `~/.profile`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then reload your shell configuration:

```bash
$ source ~/.bashrc  # or ~/.zshrc, ~/.profile, etc.
```

#### On Windows

Find the user site-packages directory:

```powershell
> python -m site --user-site
C:\Users\Username\AppData\Roaming\Python\Python310\site-packages
```

Replace `site-packages` with `Scripts` in the path, and add it to your PATH environment variable:

1. Press `Win + X` and select "System"
2. Click "Advanced system settings"
3. Click "Environment Variables"
4. Under "User variables", select "Path" and click "Edit"
5. Add the path (e.g., `C:\Users\Username\AppData\Roaming\Python\Python310\Scripts`)
6. Click "OK" to save changes

You may need to restart your terminal or computer for the PATH changes to take effect.

### Alternative: System-Wide Installation

If you have administrator privileges and want to install Pipenv system-wide:

```bash
# On Linux/macOS
$ sudo pip install pipenv

# On Windows (in an Administrator command prompt)
> pip install pipenv
```

```{warning}
System-wide installation is not recommended for most users as it can lead to conflicts with your system package manager.
```

### Using Package Managers

#### macOS with Homebrew

```bash
$ brew install pipenv
```

```{note}
Homebrew installation is discouraged because it works better to install pipenv using pip on macOS.
```

#### Debian/Ubuntu

```bash
$ sudo apt update
$ sudo apt install pipenv
```

#### Fedora

```bash
$ sudo dnf install pipenv
```

#### FreeBSD

```bash
$ pkg install py39-pipenv
```

#### Gentoo

```bash
$ sudo emerge pipenv
```

#### Void Linux

```bash
$ sudo xbps-install -S python3-pipenv
```

### Using pipx

[pipx](https://pypa.github.io/pipx/) is a tool to install and run Python applications in isolated environments:

```bash
# Install pipx
$ pip install --user pipx
$ python -m pipx ensurepath

# Install Pipenv using pipx
$ pipx install pipenv
```

This is a good alternative to the `--user` installation method, especially if you use multiple Python command-line tools.

### Using Python Module

You can also run Pipenv as a Python module:

```bash
$ python -m pip install pipenv
$ python -m pipenv
```

This approach is useful when you have multiple Python versions installed and want to ensure you're using a specific one.

## Verifying Installation

After installation, verify that Pipenv is working correctly:

```bash
$ pipenv --version
pipenv, version 2022.5.2
```

If you see the version number, Pipenv is installed correctly.

## Upgrading Pipenv

To upgrade an existing Pipenv installation:

```bash
# User installation
$ pip install --user --upgrade pipenv

# System-wide installation
$ sudo pip install --upgrade pipenv

# Homebrew
$ brew upgrade pipenv

# pipx
$ pipx upgrade pipenv
```

## Installing Specific Versions

If you need a specific version of Pipenv:

```bash
$ pip install --user pipenv==2022.1.8
```

## Installation in Virtual Environments

You can install Pipenv inside a virtual environment, although this is less common:

```bash
$ python -m venv pipenv-venv
$ source pipenv-venv/bin/activate  # On Windows: pipenv-venv\Scripts\activate
(pipenv-venv) $ pip install pipenv
```

## Docker Installation

For Docker environments, you can install Pipenv in your Dockerfile:

```dockerfile
FROM python:3.10-slim

# Install pipenv
RUN pip install pipenv

# Set working directory
WORKDIR /app

# Copy Pipfile and Pipfile.lock
COPY Pipfile Pipfile.lock ./

# Install dependencies
RUN pipenv install --system --deploy

# Copy application code
COPY . .

# Run the application
CMD ["python", "app.py"]
```

## CI/CD Installation

For continuous integration environments:

```yaml
# GitHub Actions example
name: Python CI

on: [push, pull_request]

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    - name: Install pipenv
      run: |
        python -m pip install --upgrade pip
        pip install pipenv
    - name: Install dependencies
      run: |
        pipenv install --dev
    - name: Run tests
      run: |
        pipenv run pytest
```

## Troubleshooting

### Command Not Found

If you get a "command not found" error after installation:

1. Check if Pipenv is installed in your user site-packages:
   ```bash
   $ python -m pipenv --version
   ```

2. If that works, add the user site-packages bin directory to your PATH as described above.

3. Try restarting your terminal or computer.

### Permission Errors

If you encounter permission errors during installation:

1. Use the `--user` flag to install in your home directory:
   ```bash
   $ pip install --user pipenv
   ```

2. If using sudo, ensure you're using it correctly:
   ```bash
   $ sudo pip install pipenv
   ```

3. Check file permissions in your installation directories.

### Python Version Compatibility

Pipenv requires Python 3.7 or newer. If you're using an older version, you'll need to upgrade Python first.

### pip Not Found

If pip is not found:

1. Install pip:
   ```bash
   # Download get-pip.py
   $ curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py

   # Install pip
   $ python get-pip.py --user
   ```

2. Ensure pip is in your PATH.

## Best Practices

1. **Use isolated virtual environment installation** on modern systems to avoid PEP 668 restrictions.

2. **Keep Pipenv updated** to benefit from the latest features and bug fixes.

3. **Set `PIPENV_IGNORE_VIRTUALENVS=1`** if you install pipenv in a dedicated venv, so it still manages project-specific environments.

4. **Add Pipenv to your project's development setup instructions** to ensure all developers use the same environment.

5. **Use version control** for your `Pipfile` and `Pipfile.lock` to ensure consistent environments across your team.

## Next Steps

Now that you have Pipenv installed, you can:

1. Create a new project: `pipenv --python 3.10`
2. Install packages: `pipenv install requests`
3. Activate the environment:
   - Spawn a subshell: `pipenv shell`
   - Or activate in current shell: `eval $(pipenv activate)`
4. Run commands: `pipenv run python script.py`

For more detailed usage instructions, see the [Quick Start Guide](quick_start.md) and [Commands Reference](commands.md).
