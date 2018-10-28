# PEEP-003: Local option in pipenv install to create VENV within project

This PEEP proposes to add `--local` / `-l` option to `pipenv install` command to create the VENV directory within the project.

☤

This `--local` option will be helpful incase the user wants to skip the dotenv creation and quickly try installing dependencies to a new VENV within project.

Existing approach to create VENV within project:
```
PIPENV_VENV_IN_PROJECT=true
C:\TEMP> pipenv install

>>> C:\TEMP\.venv
```

Suggested alternate approach to create VENV within project:
```
C:\TEMP> pipenv install --local
or
C:\TEMP> pipenv install -l

>>> C:\TEMP\.venv
```


### Suggested fix:
Create .venv directory within project when `--local` / `-l` option is encountered.

`ensure_virtualenv` will try to reuse this existing .venv directory for installing dependencies.

