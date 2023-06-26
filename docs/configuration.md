# Configuration

## Configuration With Environment Variables

Pipenv comes with a handful of options that can be set via shell environment
variables.

To enable boolean options, create the variable in your shell and assign to it a
true value. Allowed values are: `"1", "true", "yes", "on"`

    $ PIPENV_IGNORE_VIRTUALENVS=1

To explicitly disable a boolean option, assign to it a false value (i.e. `"0"`).

```{eval-rst}
.. autoclass:: pipenv.environments.Setting
    :members:
```

Also note that `pip` supports additional [environment variables](https://pip.pypa.io/en/stable/user_guide/#environment-variables), if you need additional customization.

For example:

    $ PIP_INSTALL_OPTION="-- -DCMAKE_BUILD_TYPE=Release" pipenv install -e .

## Changing Cache Location

You can force pipenv to use a different cache location by setting the environment variable `PIPENV_CACHE_DIR` to the location you wish.
This is useful in the same situations that you would change `PIP_CACHE_DIR` to a different directory.

## Changing Default Python Versions

By default, pipenv will initialize a project using whatever version of python the system has as default.
Besides starting a project with the `--python` flag, you can also use `PIPENV_DEFAULT_PYTHON_VERSION` to specify what version to use when starting a project when `--python` isn't used.
