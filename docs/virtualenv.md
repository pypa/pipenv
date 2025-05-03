# Virtual Environments

This guide explains how Pipenv manages virtual environments, including customization options, best practices, and troubleshooting tips.

## Understanding Virtual Environments

### What is a Virtual Environment?

A virtual environment is an isolated Python environment that allows you to install packages for a specific project without affecting your system Python installation or other projects. This isolation helps prevent dependency conflicts and ensures reproducible environments.

### How Pipenv Uses Virtual Environments

Pipenv automatically creates and manages virtual environments for your projects. When you run `pipenv install` for the first time in a project, Pipenv:

1. Creates a new virtual environment for your project
2. Installs the specified packages into that environment
3. Creates a `Pipfile` and `Pipfile.lock` to track dependencies

## Virtual Environment Location

### Default Location

By default, Pipenv stores virtual environments in a centralized location:

- **On Linux/macOS**: `~/.local/share/virtualenvs/`
- **On Windows**: `%USERPROFILE%\.virtualenvs\`

The virtual environment name is derived from the project directory name plus a hash of the full path to ensure uniqueness. For example, a project in `/home/user/projects/myproject` might have a virtual environment named `myproject-a1b2c3d4`.

### Finding Your Virtual Environment

To find the path to your project's virtual environment:

```bash
$ pipenv --venv
/home/user/.local/share/virtualenvs/myproject-a1b2c3d4
```

To find the Python interpreter path:

```bash
$ pipenv --py
/home/user/.local/share/virtualenvs/myproject-a1b2c3d4/bin/python
```

## Customizing Virtual Environment Location

### Project-Local Virtual Environments

You can tell Pipenv to create the virtual environment in your project directory by setting the `PIPENV_VENV_IN_PROJECT` environment variable:

```bash
$ export PIPENV_VENV_IN_PROJECT=1
$ pipenv install
```

This creates a `.venv` directory in your project, making it easier to find and manage.

Benefits of project-local virtual environments:
- Easier to locate and manage
- Self-contained project directory
- Better for version control (though you should still add `.venv` to your `.gitignore`)
- Useful for containerized environments

### Custom Virtual Environment Directory

You can specify a custom location for all virtual environments by setting the `WORKON_HOME` environment variable:

```bash
$ export WORKON_HOME=~/my-virtualenvs
$ pipenv install
```

This is useful if you want to store all virtual environments in a specific directory.

### Custom Virtual Environment Name

You can specify a custom name for your virtual environment by setting the `PIPENV_CUSTOM_VENV_NAME` environment variable:

```bash
$ export PIPENV_CUSTOM_VENV_NAME=myproject-env
$ pipenv install
```

This overrides the default naming scheme and uses your specified name instead.

## Managing Virtual Environments

### Activating the Virtual Environment

To activate the virtual environment:

```bash
$ pipenv shell
```

This spawns a new shell with the virtual environment activated. You can exit this shell with `exit` or Ctrl+D.

Alternatively, you can run commands in the virtual environment without activating it:

```bash
$ pipenv run python script.py
```

### Deactivating the Virtual Environment

If you're in a shell created by `pipenv shell`, you can deactivate the virtual environment by exiting the shell:

```bash
$ exit
```

### Removing the Virtual Environment

To remove the virtual environment:

```bash
$ pipenv --rm
```

This deletes the virtual environment but leaves your `Pipfile` and `Pipfile.lock` intact.

## Virtual Environment Naming

### Default Naming Scheme

The default virtual environment name follows this pattern:

```
{project_name}-{hash}
```

Where:
- `{project_name}` is the name of your project directory
- `{hash}` is a hash of the full path to your project

For example, a project in `/home/user/projects/myproject` might have a virtual environment named `myproject-a1b2c3d4`.

### Character Handling

Dangerous characters (i.e., ``$!*@"``, as well as space, line feed, carriage return, and tab) in the project name are converted to underscores in the virtual environment name.

## Moving or Renaming Projects

When you move or rename a project directory, Pipenv can no longer find the associated virtual environment because the path hash changes.

### Recommended Workflow for Moving/Renaming

1. Remove the virtual environment before moving or renaming:
   ```bash
   $ pipenv --rm
   ```

2. Move or rename your project directory.

3. Recreate the virtual environment in the new location:
   ```bash
   $ cd /path/to/new/location
   $ pipenv install
   ```

This ensures that Pipenv creates a new virtual environment with the correct path hash.

## Using Different Python Versions

### Specifying Python Version

You can specify which Python version to use when creating a virtual environment:

```bash
$ pipenv --python 3.10
```

This creates a virtual environment using Python 3.10.

### Using pyenv with Pipenv

If you have [pyenv](https://github.com/pyenv/pyenv) installed, Pipenv can automatically use it to find and install the required Python version:

```bash
$ pipenv --python 3.10
```

If Python 3.10 isn't installed, Pipenv will prompt you to install it with pyenv.

### Using asdf with Pipenv

Similarly, if you have [asdf](https://asdf-vm.com/) installed with the Python plugin, Pipenv can use it to find and install the required Python version.

## Advanced Configuration

### Environment Variables

Several environment variables affect how Pipenv manages virtual environments:

| Variable | Description | Default |
|----------|-------------|---------|
| `PIPENV_VENV_IN_PROJECT` | Create virtualenv in project directory | `0` (disabled) |
| `WORKON_HOME` | Custom directory for virtual environments | Platform-specific |
| `PIPENV_CUSTOM_VENV_NAME` | Custom name for the virtual environment | None |
| `PIPENV_PYTHON` | Path to Python executable to use | System default |
| `PIPENV_IGNORE_VIRTUALENVS` | Ignore active virtual environments | `0` (disabled) |

### Shell Configuration

For the best experience with `pipenv shell`, ensure your shell configuration only sets environment variables like `PATH` during login sessions, not during every subshell spawn.

For example, in fish:

```fish
if status --is-login
    set -gx PATH /usr/local/bin $PATH
end
```

In bash or zsh, you might use:

```bash
if [[ -z $PIPENV_ACTIVE ]]; then
    export PATH=/usr/local/bin:$PATH
fi
```

## Troubleshooting

### Virtual Environment Not Found

If Pipenv can't find your virtual environment:

1. Check if the virtual environment exists:
   ```bash
   $ pipenv --venv
   ```

2. If it doesn't exist, create it:
   ```bash
   $ pipenv install
   ```

3. If you've moved or renamed your project, follow the steps in the "Moving or Renaming Projects" section.

### Shell Activation Issues

If `pipenv shell` doesn't work correctly:

1. Try compatibility mode (the default):
   ```bash
   $ pipenv shell
   ```

2. If that doesn't work, try fancy mode:
   ```bash
   $ pipenv shell --fancy
   ```

3. If neither works, use `pipenv run` instead:
   ```bash
   $ pipenv run python
   ```

### Python Version Issues

If Pipenv uses the wrong Python version:

1. Specify the Python version explicitly:
   ```bash
   $ pipenv --python 3.10
   ```

2. Check your `Pipfile` for the required Python version:
   ```toml
   [requires]
   python_version = "3.10"
   ```

3. If using pyenv, ensure the required Python version is installed:
   ```bash
   $ pyenv versions
   $ pyenv install 3.10.4
   ```

## Best Practices

### Version Control

- Add `.venv/` to your `.gitignore` if using project-local virtual environments
- Commit both `Pipfile` and `Pipfile.lock` to version control
- Don't commit the virtual environment itself

### Project Organization

- Consider using project-local virtual environments (`PIPENV_VENV_IN_PROJECT=1`) for better organization
- Use a consistent approach across all your projects
- Document your virtual environment setup in your project's README

### CI/CD Integration

In CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
steps:
  - uses: actions/checkout@v3
  - uses: actions/setup-python@v4
    with:
      python-version: '3.10'
  - name: Install pipenv
    run: pip install pipenv
  - name: Install dependencies
    run: pipenv install --deploy
  - name: Run tests
    run: pipenv run pytest
```

### Docker Integration

When using Pipenv with Docker, consider using project-local virtual environments:

```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY Pipfile Pipfile.lock ./

RUN pip install pipenv && \
    PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy

COPY . .

CMD ["pipenv", "run", "python", "app.py"]
```

## Conclusion

Pipenv's virtual environment management simplifies Python project setup and dependency isolation. By understanding how Pipenv creates and manages virtual environments, you can ensure consistent, reproducible environments for your Python projects.
