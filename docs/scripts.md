# Custom Script Shortcuts

It is possible to create custom shortcuts in the optional `[scripts]` section of your Pipfile.

You can then run `pipenv run <shortcut name>` in your terminal to run the command in the
context of your pipenv virtual environment even if you have not activated the pipenv shell first.

For example, in your Pipfile:

```{code-block}
    [scripts]
    printspam = "python -c \"print('I am a silly example, no one would need to do this')\""
---
toml
```
And then in your terminal:

    $ pipenv run printspam
    I am a silly example, no one would need to do this

Commands that expect arguments will also work.

```{code-block}
    [scripts]
    echospam = "echo I am really a very silly example"
---
toml
```

Invoke script:

    $ pipenv run echospam "indeed"
    I am really a very silly example indeed

You can also specify package functions as callables such as: `<pathed.module>:<func>`. These can also take arguments.
For example:

    [scripts]
    my_func_with_args = {call = "package.module:func('arg1', 'arg2')"}
    my_func_no_args = {call = "package.module:func()"}

To run the script:

    $ pipenv run my_func_with_args
    $ pipenv run my_func_no_args

You can display the names and commands of your shortcuts by running `pipenv scripts` in your terminal.

    $ pipenv scripts
    command   script
    echospam  echo I am really a very silly example
