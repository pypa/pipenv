# PEEP-006: Change the behavior of `-d` flag when generating requirement.txt

Make the behavior of `pipenv lock -r -d` consistent with those in other commands: convert all dependencies.

☤

If you type `pipenv lock --help` the help document says:

```bash
-d, --dev           Install both develop and default packages.  [env var:PIPENV_DEV]
```

That is not accurate and confusing for `pipenv lock -r`, which only produces the develop requirments.

This PEEP proposes to change the behavior of `pipenv lock -r -d` to produce **all** requirements, both develop
and default. Also, change the help string of `-d/--dev` to **"Generate both develop and default requirements"**.

Introduce a new flag `--only` to restrict to develop requirements only. The flag does nothing when not combined with
`-d/--dev` flag.

Display a warning message to remind users of the new `--only` flag and the behavior change, for the next several releases.

## Impact

The users relying on the old behavior will get more requirements listed in the ``dev-requirements.txt`` file,
which in most cases is harmless. They can just add `--only` flag to achieve the same thing before.

## Related issues:

- #3316
