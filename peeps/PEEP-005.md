# PEEP-005: Define run commands in Pipfile 

Similar to `npm run`, commands can be defined in Pipfile which are executed in a `pipenv run <command>` context.

☤

Since `pipenv` expands environment variables (`.env`) and executes commands in the venv using `pipenv run <command>`,
it would be great to allow for an `npm run`-esque way of defining commands in a Pipfile. Here's an example:

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
django = "*"
dj-database-url = "*"
celery = "*"
requests = "*"

[dev-packages]
faker = "*"
pytest-django = "*"
pytest-sugar = "*"
pytest-cov = "*"
pytest = "*"
black = "*"
pytest-mock = "*"

[commands]
blacken = "black --line-length 120 ."
scheduler = "celery -A my_project beat"
celery = "celery -A my_project worker"
tests = "pytest --cov=my_project"
lint = "git ls-files | grep '.*\.py$' | xargs pylint"
```

Now, you could do:

```
$ pipenv run blacken

All done! ✨ 🍰 ✨
64 files reformatted, 27 files left unchanged.
```
