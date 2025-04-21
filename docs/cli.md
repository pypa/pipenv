# Pipenv CLI Reference

## pipenv

```bash
pipenv [OPTIONS] COMMAND [ARGS]...
```

## check

Checks and scans project for PyUp Safety security vulnerabilities and against PEP 508 markers.

```bash
pipenv check [OPTIONS]
```

Options:
```
--db TEXT                       Path or URL to a PyUp Safety vulnerabilities database.
--ignore, -i TEXT               Ignore specified vulnerability during PyUp Safety checks.
--output [default|json|full-report|bare|screen|text|minimal]
                                Translates to --json, --full-report or --bare from PyUp Safety check.
--key TEXT                      Safety API key from PyUp.io for scanning dependencies against a live
                                vulnerabilities database.
--quiet                         Quiet standard output, except vulnerability report.
--policy-file TEXT              Define the policy file to be used.
--exit-code / --continue-on-error
                                Output standard exit codes. Default: --exit-code.
--audit-and-monitor / --disable-audit-and-monitor
                                Send results back to pyup.io for viewing on your dashboard.
--project TEXT                  Project to associate this scan with on pyup.io.
--save-json TEXT                Path to where output file will be placed.
--use-installed                 Whether to use the lockfile as input to check.
--categories TEXT               Use the specified categories from the lockfile as input to check.
--auto-install                  Automatically install safety if not already installed.
--scan                          Use the new scan command instead of the deprecated check command.
```

**Note**: The check command is deprecated and will be unsupported beyond 01 June 2024. In future versions, the check command will run the scan command by default. Use the `--scan` option to run the new scan command now.

When using the `--scan` option, you'll need to obtain an API key from https://pyup.io to access the full vulnerability database.

## clean

Uninstalls all packages not specified in Pipfile.lock.

```bash
pipenv clean [OPTIONS]
```

## graph

Displays currently–installed dependency graph information.

```bash
pipenv graph [OPTIONS]
```

## install

Installs provided packages and adds them to Pipfile, or (if no packages are given), installs all packages from Pipfile.lock

```bash
pipenv install [OPTIONS] [PACKAGES]...
```

Environment Variables

PIP_INDEX_URL

```bash
   Provide a default for -i
```

## lock

Generates Pipfile.lock.

```bash
pipenv lock [OPTIONS]
```

## open

View a given module in your editor.

This uses the EDITOR environment variable. You can temporarily override it, for example:

EDITOR=atom pipenv open requests

```bash
pipenv open [OPTIONS] MODULE
```

## requirements

Generate a requirements.txt from Pipfile.lock.

```bash
pipenv requirements [OPTIONS]
```

## run

Spawns a command installed into the virtualenv.

```bash
pipenv run [OPTIONS] COMMAND [ARGS]...
```

## scripts

Lists scripts in current environment config.

```bash
pipenv scripts [OPTIONS]
```

## shell

Spawns a shell within the virtualenv.

```bash
pipenv shell [OPTIONS] [SHELL_ARGS]...
```

## sync

Installs all packages specified in Pipfile.lock.

```bash
pipenv sync [OPTIONS]
```

## uninstall

Un-installs a provided package and removes it from Pipfile.

```bash
pipenv uninstall [OPTIONS] [PACKAGES]...
```

## update

Runs lock when no packages are specified, or upgrade, and then sync.

```bash
pipenv update [OPTIONS] [PACKAGES]...
```

Environment Variables

PIP_INDEX_URL

```bash
   Provide a default for -i
```

## upgrade

Resolves provided packages and adds them to Pipfile, or (if no packages are given), merges results to Pipfile.lock

```bash
pipenv upgrade [OPTIONS] [PACKAGES]...
```

Environment Variables

PIP_INDEX_URL

```bash
   Provide a default for -i
```

## verify

Verify the hash in Pipfile.lock is up-to-date.

```bash
pipenv verify [OPTIONS]
```
