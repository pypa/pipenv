Be sure to check the existing issues (both open and closed!), and make sure you are running the latest version of Pipenv.

If you're requesting a new feature, please use the PEEP process:

    https://github.com/pypa/pipenv/blob/master/peeps/PEEP-000.md

Check the [diagnose documentation](https://docs.pipenv.org/diagnose/) for common issues before posting! We may close your issue if it is very similar to one of them. Please be considerate, or be on your way.

Make sure to mention your debugging experience if the documented solution failed.


### Issue description

Describe the issue briefly here.

### Expected result

Describe what you expected.

### Actual result

When possible, provide the verbose output (`--verbose`), especially for locking and dependencies resolving issues.

### Steps to replicate

Provide the steps to replicate (which usually at least includes the commands and the Pipfile).

-------------------------------------------------------------------------------

Please run `$ pipenv --support`, and paste the results here. Don't put backticks (`` ` ``) around it! The output already contains Markdown formatting.

If you're on macOS, run the following:

    $ pipenv --support | pbcopy

If you're on Windows, run the following:

    > pipenv --support | clip

If you're on Linux, run the following:

    $ pipenv --support | xclip
