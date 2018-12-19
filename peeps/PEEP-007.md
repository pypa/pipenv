# PEEP-007: Use dotenv to manage Pipenv environments

This PEEP proposes to make use of dotenv file to manage Pipenv enviroments.

☤

At present Pipenv supports [multiple environment variables][1] to change its behavior.
To use one or more of them, users have to specify the variables in their shell. As a workaround,
people can use the awesome [direnv][2] tool to detect and activate what are present in `.envrc`
automatically, but it does not work on Windows platform. We need built-in support for environment
files in Pipenv. Pipenv integrates with support of `dotenv` and `.env` files, however,
it is only used in `pipenv shell` and `pipenv run`.

[1]: https://pipenv.readthedocs.io/en/latest/advanced/#configuration-with-environment-variables
[2]: https://direnv.net/

## Desired Behavior

This PEEP proposes to detect `.env` and activate it when launching Pipenv. With this change, users
will be able to set multiple `PIPENV_` prefixed environment variables in `.env` file under the
project directory.


Author: frostming <mianghong@gmail.com>
