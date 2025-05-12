# Pipenv Workflows

This document outlines common workflows and patterns for using Pipenv effectively in your Python projects. Each workflow includes step-by-step instructions and practical examples.

## Project Setup Workflows

### Starting a New Project

```bash
# Create a new project directory
$ mkdir myproject
$ cd myproject

# Initialize a new Pipenv environment with a specific Python version
$ pipenv --python 3.10

# Install your first packages
$ pipenv install requests flask
```

### Working with Existing Projects

```bash
# Clone a repository
$ git clone https://github.com/example/project.git
$ cd project

# Install from Pipfile.lock (recommended for deployment or when collaborating)
$ pipenv install --deploy

# Or install from Pipfile (for development, allowing resolution of new dependencies)
$ pipenv install
```

### Converting from requirements.txt

```bash
# If you have an existing requirements.txt file
$ pipenv install -r requirements.txt

# Review the generated Pipfile and edit as needed
$ cat Pipfile

# Lock the dependencies
$ pipenv lock
```

## Development Workflows

### Daily Development Cycle

```bash
# Activate the virtual environment
$ pipenv shell

# Work on your project...
# When you need a new package:
$ pipenv install package-name

# For development-only packages:
$ pipenv install pytest --dev

# Run your application or tests
$ python app.py
$ pytest
```

### Using the Run Command

Instead of activating the shell, you can use the `run` command to execute commands in the virtual environment:

```bash
# Run a Python script
$ pipenv run python app.py

# Run tests
$ pipenv run pytest

# Run a custom script defined in your Pipfile
$ pipenv run start
```

### Managing Development vs. Production Dependencies

```bash
# Install a production dependency
$ pipenv install flask

# Install a development dependency
$ pipenv install pytest --dev

# Install all dependencies (including dev) for development
$ pipenv install --dev

# Install only production dependencies for deployment
$ pipenv install --deploy
```

## Dependency Management Workflows

### Updating Dependencies

```bash
# Check for outdated packages
$ pipenv update --outdated

# Update all packages to their latest versions
$ pipenv update

# Update specific packages
$ pipenv update requests flask
```

### Upgrading Dependencies (Lock File Only)

```bash
# Update the lock file for a specific package without installing
$ pipenv upgrade requests

# Then install the updated dependencies when ready
$ pipenv sync
```

### Visualizing Dependencies

```bash
# Show dependency graph
$ pipenv graph

# Show a more concise output
$ pipenv graph --bare
```

### Cleaning Up Dependencies

```bash
# Remove packages not in Pipfile.lock
$ pipenv clean

# Preview what would be removed
$ pipenv clean --dry-run
```

## Deployment Workflows

### Preparing for Deployment

```bash
# Ensure Pipfile.lock is up-to-date
$ pipenv lock

# Verify the lock file is in sync with Pipfile
$ pipenv verify

# Generate a requirements.txt file for environments that don't support Pipfile
$ pipenv requirements > requirements.txt
```

### Deploying to Production

```bash
# On your production server, install only what's in the lock file
$ pipenv install --deploy

# For systems that don't support virtual environments
$ pipenv install --system --deploy
```

### Continuous Integration

```bash
# In your CI pipeline, verify the lock file is up-to-date
$ pipenv verify

# Install dependencies
$ pipenv install --dev

# Run tests
$ pipenv run pytest
```

## Security Workflows

### Checking for Vulnerabilities

```bash
# Check for security vulnerabilities
$ pipenv scan

# Output in JSON format for integration with other tools
$ pipenv scan --output json
```

### Generating Requirements with Hashes

```bash
# Generate requirements.txt with hashes for secure deployments
$ pipenv requirements --hash > requirements.txt
```

## Environment Management

### Working with .env Files

Create a `.env` file in your project directory:

```
# .env file
DEBUG=True
DATABASE_URL=sqlite:///dev.db
SECRET_KEY=your-secret-key
```

Pipenv will automatically load these environment variables when you use `pipenv shell` or `pipenv run`.

### Locating Project Resources

```bash
# Find the project root
$ pipenv --where

# Find the virtualenv location
$ pipenv --venv

# Find the Python interpreter path
$ pipenv --py
```

## Advanced Workflows

### Working with Multiple Package Categories

```bash
# Define custom package categories in your Pipfile
# [packages]
# requests = "*"
#
# [dev-packages]
# pytest = "*"
#
# [docs]
# sphinx = "*"
#
# [tests]
# pytest-cov = "*"

# Install specific categories
$ pipenv install --categories="docs,tests"

# Generate requirements for specific categories
$ pipenv requirements --categories="docs" > docs-requirements.txt
```

### Using Pipenv with Docker

```dockerfile
# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# Copy Pipfile and Pipfile.lock
COPY Pipfile Pipfile.lock ./

# Install pipenv and dependencies
RUN pip install pipenv && \
    pipenv install --system --deploy

# Copy application code
COPY . .

CMD ["python", "app.py"]
```

### Git Integration Best Practices

```bash
# Always commit both Pipfile and Pipfile.lock
$ git add Pipfile Pipfile.lock
$ git commit -m "Update dependencies"

# After pulling changes that include dependency updates
$ pipenv install
```

## Troubleshooting Workflows

### Resolving Dependency Conflicts

```bash
# Clear the cache and try again
$ pipenv lock --clear

# Install with verbose output to see what's happening
$ pipenv install --verbose
```

### Recreating the Virtual Environment

```bash
# Remove the current virtualenv
$ pipenv --rm

# Create a fresh environment
$ pipenv install
```

### Checking Environment Information

```bash
# Get detailed environment information for bug reports
$ pipenv --support
```

## Workflow Cheat Sheet

| Task | Command |
|------|---------|
| Create new project | `pipenv --python 3.10` |
| Install packages | `pipenv install [package]` |
| Install dev packages | `pipenv install [package] --dev` |
| Activate environment | `pipenv shell` |
| Run a command | `pipenv run [command]` |
| Update all packages | `pipenv update` |
| Update specific package | `pipenv update [package]` |
| Generate requirements.txt | `pipenv requirements > requirements.txt` |
| Check security | `pipenv scan` |
| Show dependency graph | `pipenv graph` |
| Remove environment | `pipenv --rm` |
| Find project/virtualenv | `pipenv --where` / `pipenv --venv` |
