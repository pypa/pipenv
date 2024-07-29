# Pipenv CLI Reference

## pipenv

```bash
pipenv [OPTIONS] COMMAND [ARGS]...
```

## check

Checks for PyUp Safety security vulnerabilities and against PEP 508 markers provided in Pipfile.

```bash
pipenv check [OPTIONS]
```

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
