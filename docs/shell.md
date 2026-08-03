# Shell Integration and Environment Management

This guide covers Pipenv's shell integration features, environment variable management, and best practices for configuring your development environment.

## Shell Integration

Pipenv provides robust shell integration that allows you to work within your project's virtual environment seamlessly.

### Activating the Virtual Environment

To activate your project's virtual environment, use the `shell` command:

```bash
$ pipenv shell
```

This spawns a new shell subprocess with the virtual environment activated. You'll notice your shell prompt changes to indicate the active environment:

```bash
(project-a1b2c3) $
```

To exit the virtual environment and return to your normal shell, simply type:

```bash
$ exit
```

or press `Ctrl+D`.

### Shell Activation Modes

Pipenv supports two shell activation modes:

1. **Compatibility Mode** (default): Uses a simpler approach that works in most shell environments
2. **Fancy Mode**: Uses more advanced shell features for a better experience in properly configured shells

To use fancy mode:

```bash
$ pipenv shell --fancy
```

### Running Commands Without Activation

If you don't want to activate the full shell, you can run individual commands within the virtual environment:

```bash
$ pipenv run python script.py
$ pipenv run pytest
```

This is particularly useful for one-off commands or in CI/CD pipelines.

## Environment Variable Management

### Automatic Loading of .env Files

Pipenv automatically loads environment variables from `.env` files in your project directory when you use `pipenv shell` or `pipenv run`. This feature helps you manage environment-specific configuration without hardcoding values in your code.

A typical `.env` file might look like this:

```
# .env
DEBUG=True
DATABASE_URL=postgresql://user:password@localhost/dbname
SECRET_KEY=your-secret-key-here
API_KEY=1234567890abcdef
```

When you run a command with Pipenv, these variables are automatically loaded:

```bash
$ pipenv run python
Loading .env environment variables...
Python 3.10.4 (default, Mar 23 2022, 17:29:05)
[GCC 9.4.0] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> import os
>>> os.environ['DEBUG']
'True'
>>> os.environ['DATABASE_URL']
'postgresql://user:password@localhost/dbname'
```

### Variable Expansion in .env Files

You can use variable expansion in your `.env` files using the `${VARNAME}` syntax:

```
# .env
HOME_DIR=${HOME}
CONFIG_PATH=${HOME_DIR}/.config/myapp
LOG_DIR=${HOME_DIR}/logs
```

This allows you to define variables in terms of other variables, including system environment variables:

```bash
$ pipenv run python -c "import os; print(os.environ['CONFIG_PATH'])"
Loading .env environment variables...
/home/user/.config/myapp
```

### Custom .env File Location

If your `.env` file is located in a different path or has a different name, you can specify its location:

```bash
$ PIPENV_DOTENV_LOCATION=/path/to/custom/.env pipenv shell
```

Or set it permanently in your shell configuration:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PIPENV_DOTENV_LOCATION=/path/to/custom/.env
```

### Disabling .env Loading

In some cases, you might want to prevent Pipenv from loading `.env` files:

```bash
$ PIPENV_DONT_LOAD_ENV=1 pipenv shell
```

This is useful when you want to use system environment variables instead of those defined in the `.env` file.

## Shell Completion

Pipenv supports tab completion for commands, options, and arguments via
[argcomplete](https://kislyuk.github.io/argcomplete/).

### Installation

Shell completion is an optional feature. Install it alongside pipenv:

```bash
pip install "pipenv[completion]"
```

Or install `argcomplete` separately:

```bash
pip install argcomplete
```

### Activation

#### Bash

Add the following line to your `~/.bashrc` (or `~/.bash_profile` on macOS):

```bash
eval "$(register-python-argcomplete pipenv)"
```

Then reload your shell:

```bash
source ~/.bashrc
```

#### Zsh

Add to your `~/.zshrc`:

```zsh
autoload -U bashcompinit
bashcompinit
eval "$(register-python-argcomplete pipenv)"
```

Then reload:

```zsh
source ~/.zshrc
```

#### Fish

```fish
register-python-argcomplete --shell fish pipenv | source
```

To make it permanent, add the line above to `~/.config/fish/config.fish`.

#### Global activation (all argcomplete-enabled tools at once)

If you use multiple tools that support argcomplete, you can activate completion
for all of them in one step:

```bash
activate-global-python-argcomplete
```

This installs a shell hook that handles any package that calls
`argcomplete.autocomplete()`.

### Verifying completion works

After reloading your shell, type `pipenv ` and press `Tab` — you should see the
list of available subcommands. Pressing `Tab` again after a partial subcommand
name (e.g. `pipenv ins<Tab>`) completes it to `pipenv install`.

#### Git Bash (Windows)

Git Bash supports bash completion. Add to your `~/.bashrc` (typically
`C:\Users\<you>\.bashrc`):

```bash
eval "$(register-python-argcomplete pipenv)"
```

Then restart Git Bash or run `source ~/.bashrc`.

### Migrating from pipenv < 2026.5.0

In older versions of pipenv (before 2026.5.0), shell completion was powered by
Click and activated with the `_PIPENV_COMPLETE` environment variable:

```bash
# OLD method — no longer works in pipenv >= 2026.5.0
eval "$(_PIPENV_COMPLETE=bash_source pipenv)"    # bash
eval "$(_PIPENV_COMPLETE=zsh_source pipenv)"     # zsh
_PIPENV_COMPLETE=fish_source pipenv | source     # fish
```

Starting with pipenv 2026.5.0, shell completion uses
[argcomplete](https://kislyuk.github.io/argcomplete/) instead. **Replace** the
lines above with the `register-python-argcomplete` commands shown in the
[Activation](#activation) section and make sure the `argcomplete` package is
installed (`pip install "pipenv[completion]"`).

### Troubleshooting

If completion is not working:

1. **Confirm argcomplete is installed** in the same environment as pipenv:
   ```bash
   pip show argcomplete
   ```

2. **Verify the activation line** is present in your shell startup file and
   that the file is being sourced for interactive sessions.

3. **Restart your shell** completely (not just `source`) if the hook was
   recently added.

4. **Check for errors** by running the registration command directly:
   ```bash
   register-python-argcomplete pipenv
   ```
   It should print a shell function definition without errors.

5. **If you see a migration message** about `_PIPENV_COMPLETE`, you are using
   the old activation method. See [Migrating from pipenv < 2026.5.0](#migrating-from-pipenv--202650)
   above.

## Best Practices for Shell Configuration

### Proper PATH Configuration

A common issue with shell integration is improper PATH configuration. Many shell configurations add to the PATH in every subshell, which can cause problems with virtual environments.

The correct approach is to set environment variables like PATH only during login sessions, not in every subshell:

#### Fish Shell

```fish
# ~/.config/fish/config.fish
if status --is-login
    set -gx PATH /usr/local/bin $PATH
end
```

#### Bash/Zsh

```bash
# ~/.bashrc or ~/.zshrc
if [[ -z $PIPENV_ACTIVE ]]; then
    export PATH=/usr/local/bin:$PATH
fi
```

### Environment-Specific Configuration

For different environments (development, staging, production), use separate `.env` files:

```bash
# Development
$ PIPENV_DOTENV_LOCATION=.env.development pipenv shell

# Staging
$ PIPENV_DOTENV_LOCATION=.env.staging pipenv shell

# Production
$ PIPENV_DOTENV_LOCATION=.env.production pipenv shell
```

### Security Considerations

1. **Never commit `.env` files to version control**. Add them to your `.gitignore`:
   ```
   # .gitignore
   .env
   .env.*
   ```

2. **Provide a template** for required environment variables:
   ```
   # .env.example (safe to commit)
   DEBUG=
   DATABASE_URL=
   SECRET_KEY=
   ```

3. **Use different variables for different environments** to prevent accidental use of development settings in production.

## Advanced Shell Integration

### Custom Scripts in Pipfile

You can define custom scripts in your Pipfile for common tasks:

```toml
[scripts]
start = "python app.py"
test = "pytest"
lint = "flake8 ."
```

Then run them with:

```bash
$ pipenv run start
$ pipenv run test
```

### Shell Hooks

Some shells support hooks that can automatically activate virtual environments when entering a directory:

#### Direnv Integration

[direnv](https://direnv.net/) is a tool that can automatically load/unload environment variables based on the current directory:

```bash
# .envrc
layout pipenv
```

This automatically activates the Pipenv environment when entering the directory.

#### Zsh Autoenv

For zsh users, [zsh-autoenv](https://github.com/Tarrasch/zsh-autoenv) can automatically activate/deactivate environments:

```bash
# .autoenv.zsh
pipenv shell
```

```bash
# .autoenv_leave.zsh
exit
```

## Troubleshooting Shell Integration

### Shell Activation Issues

If `pipenv shell` doesn't work correctly:

1. **Check your shell configuration** for conflicts with Pipenv
2. **Try compatibility mode** (the default) if fancy mode doesn't work
3. **Use `pipenv run`** as an alternative to shell activation

### Environment Variable Problems

If environment variables aren't being loaded correctly:

1. **Check your `.env` file syntax** for errors
2. **Verify the file location** is correct
3. **Ensure the file is readable** by your user
4. **Check for conflicting environment variables** in your shell

### Shell Completion Issues

See the [Troubleshooting](#troubleshooting) section under *Shell Completion* above.

## Using Python-Dotenv

Pipenv uses [python-dotenv](https://github.com/theskumar/python-dotenv) internally to load `.env` files. For more advanced usage, you can use this library directly in your code:

```python
# app.py
from dotenv import load_dotenv
import os

# Load .env file manually (Pipenv does this automatically)
load_dotenv()

# Access environment variables
debug = os.environ.get("DEBUG", "False") == "True"
database_url = os.environ["DATABASE_URL"]
```

This gives you more control over how environment variables are loaded and used in your application.

## Conclusion

Pipenv's shell integration and environment variable management features provide a powerful way to manage your Python development environment. By understanding and using these features effectively, you can create a more productive and secure development workflow.

Remember to follow best practices for shell configuration and environment variable management to avoid common issues and ensure a smooth experience with Pipenv.
