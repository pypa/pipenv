# Environment and Shell Configuration


## Automatic Loading of .env

If a `.env` file is present in your project, `$ pipenv shell` and `$ pipenv run` will automatically load it, for you:

    $ cat .env
    HELLO=WORLD⏎

    $ pipenv run python
    Loading .env environment variables...
    Python 2.7.13 (default, Jul 18 2017, 09:17:00)
    [GCC 4.2.1 Compatible Apple LLVM 8.1.0 (clang-802.0.42)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    >>> import os
    >>> os.environ['HELLO']
    'WORLD'

Variable expansion is available in `.env` files using `${VARNAME}` syntax:

    $ cat .env
    CONFIG_PATH=${HOME}/.config/foo

    $ pipenv run python
    Loading .env environment variables...
    Python 3.7.6 (default, Dec 19 2019, 22:52:49)
    [GCC 9.2.1 20190827 (Red Hat 9.2.1-1)] on linux
    Type "help", "copyright", "credits" or "license" for more information.
    >>> import os
    >>> os.environ['CONFIG_PATH']
    '/home/kennethreitz/.config/foo'


This is very useful for keeping production credentials out of your codebase.
We do not recommend committing `.env` files into source control!

If your `.env` file is located in a different path or has a different name you may set the `PIPENV_DOTENV_LOCATION` environment variable:

    $ PIPENV_DOTENV_LOCATION=/path/to/.env pipenv shell

To prevent pipenv from loading the `.env` file, set the `PIPENV_DONT_LOAD_ENV` environment variable:

    $ PIPENV_DONT_LOAD_ENV=1 pipenv shell

See [theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) for more information on `.env` files.

## Shell Completion

To enable completion in fish, add this to your configuration:

    eval (env _PIPENV_COMPLETE=fish_source pipenv)

Alternatively, with zsh, add this to your configuration:

    eval "$(_PIPENV_COMPLETE=zsh_source pipenv)"

Alternatively, with bash, add this to your configuration:

    eval "$(_PIPENV_COMPLETE=bash_source pipenv)"

Shell completions are now enabled!

## Shell Notes (stale)

Shells are typically misconfigured for subshell use, so `$ pipenv shell --fancy` may produce unexpected results. If this is the case, try `$ pipenv shell`, which uses "compatibility mode", and will attempt to spawn a subshell despite misconfiguration.

A proper shell configuration only sets environment variables like `PATH` during a login session, not during every subshell spawn (as they are typically configured to do). In fish, this looks like this:

    if status --is-login
        set -gx PATH /usr/local/bin $PATH
    end

You should do this for your shell too, in your `~/.profile` or `~/.bashrc` or wherever appropriate.

The shell launched in interactive mode. This means that if your shell reads its configuration from a specific file for interactive mode (e.g. bash by default looks for a `~/.bashrc` configuration file for interactive mode), then you'll need to modify (or create) this file.
