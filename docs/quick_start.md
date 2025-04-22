# Pipenv Quick Start Guide

This guide will help you get started with Pipenv quickly. It covers installation, basic usage, and common workflows to help you become productive with Pipenv in minutes.

## Installation

### Install Pipenv

```bash
# Install for the current user
$ pip install --user pipenv
```

Verify the installation:

```bash
$ pipenv --version
pipenv, version 2024.0.0
```

If the command isn't found, you may need to add the user site-packages bin directory to your PATH. See the [Installation](installation.md) page for detailed instructions.

## Creating a New Project

### Initialize a New Project

```bash
# Create a project directory
$ mkdir my_project
$ cd my_project

# Initialize a Pipenv environment
$ pipenv install
```

This creates a `Pipfile` in your project directory and a virtual environment for your project.

### Specify Python Version

To use a specific Python version:

```bash
$ pipenv --python 3.10
```

## Managing Dependencies

### Installing Packages

```bash
# Install a package
$ pipenv install requests

# Install a package with version constraint
$ pipenv install "django>=4.0.0"

# Install a development dependency
$ pipenv install pytest --dev
```

### Viewing Installed Packages

```bash
# Show dependency graph
$ pipenv graph

# List installed packages
$ pipenv run pip list
```

### Uninstalling Packages

```bash
# Uninstall a package
$ pipenv uninstall requests
```

## Using Your Environment

### Activating the Environment

```bash
# Activate the virtual environment
$ pipenv shell

# Now you're in the virtual environment
(my_project) $ python --version
Python 3.10.0

# Exit the environment
(my_project) $ exit
```

### Running Commands

Without activating the environment:

```bash
# Run a Python script
$ pipenv run python app.py

# Run a command
$ pipenv run pytest
```

## Working with Pipfiles

### Understanding the Pipfile

After installing packages, your `Pipfile` will look something like this:

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"
django = ">=4.0.0"

[dev-packages]
pytest = "*"

[requires]
python_version = "3.10"
```

### Locking Dependencies

Generate a `Pipfile.lock` with exact versions and hashes:

```bash
$ pipenv lock
```

### Installing from Pipfile.lock

Install the exact versions specified in `Pipfile.lock`:

```bash
$ pipenv sync
```

This is useful for deployment or when you want to ensure exact package versions.

## Common Workflows

### Development Workflow

```bash
# Clone a repository
$ git clone https://github.com/example/project.git
$ cd project

# Install dependencies including development packages
$ pipenv install --dev

# Activate environment
$ pipenv shell

# Run tests
$ pytest

# Add a new dependency
$ pipenv install new-package
```

### Deployment Workflow

```bash
# Ensure Pipfile.lock is up-to-date
$ pipenv lock

# Install only production dependencies
$ pipenv install --deploy
```

### Checking for Security Vulnerabilities

```bash
# Scan for security vulnerabilities
$ pipenv scan
```

## Environment Variables

### Using .env Files

Create a `.env` file in your project directory:

```
# .env
DEBUG=True
API_KEY=your_secret_key
```

Pipenv automatically loads these variables when you use `pipenv shell` or `pipenv run`.

Access them in your Python code:

```python
import os

debug = os.environ.get("DEBUG")
api_key = os.environ.get("API_KEY")
```

## Project Examples

### Web Application with Django

```bash
# Create project
$ mkdir django_project
$ cd django_project

# Initialize with Python 3.10
$ pipenv --python 3.10

# Install Django
$ pipenv install django

# Create Django project
$ pipenv run django-admin startproject mysite .

# Run development server
$ pipenv run python manage.py runserver
```

### Data Science Project

```bash
# Create project
$ mkdir data_analysis
$ cd data_analysis

# Install data science packages
$ pipenv install numpy pandas matplotlib jupyter

# Start Jupyter notebook
$ pipenv run jupyter notebook
```

### CLI Tool

```bash
# Create project
$ mkdir cli_tool
$ cd cli_tool

# Install dependencies
$ pipenv install click

# Create main.py
$ echo 'import click

@click.command()
@click.option("--name", default="World", help="Who to greet")
def hello(name):
    """Simple CLI tool that greets you."""
    click.echo(f"Hello, {name}!")

if __name__ == "__main__":
    hello()' > main.py

# Run the tool
$ pipenv run python main.py --name Friend
Hello, Friend!
```

## Tips and Tricks

### Locate the Virtual Environment

```bash
# Show virtualenv location
$ pipenv --venv
/home/user/.local/share/virtualenvs/my_project-a1b2c3d4
```

### Locate the Python Interpreter

```bash
# Show Python interpreter path
$ pipenv --py
/home/user/.local/share/virtualenvs/my_project-a1b2c3d4/bin/python
```

### Generate requirements.txt

```bash
# Generate requirements.txt from Pipfile.lock
$ pipenv requirements > requirements.txt
```

### Store Virtualenv in Project Directory

```bash
# Set environment variable
$ export PIPENV_VENV_IN_PROJECT=1

# Install dependencies
$ pipenv install

# The virtualenv is now in .venv in your project directory
```

### Custom Script Shortcuts

Add custom scripts to your Pipfile:

```toml
[scripts]
start = "python app.py"
test = "pytest"
lint = "flake8"
```

Run them with:

```bash
$ pipenv run start
$ pipenv run test
```

## Next Steps

Now that you're familiar with the basics of Pipenv, you can explore more advanced topics:

- [Detailed Commands Reference](commands.md)
- [Pipfile Format](pipfile.md)
- [Best Practices](best_practices.md)
- [Workflows](workflows.md)
- [Configuration](configuration.md)
- [Troubleshooting](troubleshooting.md)

For a complete reference of all Pipenv features, check out the [full documentation](index.md).
