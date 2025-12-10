# Custom Script Shortcuts in Pipenv

This guide covers how to define and use custom script shortcuts in Pipenv, including basic and advanced usage patterns, best practices, and troubleshooting tips.

## Understanding Pipenv Scripts

Pipenv allows you to define custom script shortcuts in your `Pipfile`, providing a convenient way to run common commands within your project's virtual environment. These shortcuts can simplify development workflows, standardize commands across team members, and document common operations.

## Basic Script Definition

### Defining Simple Scripts

You can define scripts in the `[scripts]` section of your `Pipfile`:

```toml
[scripts]
start = "python app.py"
test = "pytest"
lint = "flake8 ."
format = "black ."
```

Each script consists of a name (the key) and a command (the value) that will be executed in the context of your virtual environment.

### Running Scripts

To run a script, use the `pipenv run` command followed by the script name:

```bash
$ pipenv run start
```

This executes the command `python app.py` within your project's virtual environment, even if you haven't activated the shell first.

### Passing Arguments to Scripts

You can pass additional arguments to your scripts:

```bash
$ pipenv run test tests/test_api.py -v
```

This appends the arguments to the command defined in your script, resulting in `pytest tests/test_api.py -v` in this example.

## Advanced Script Definitions

### Extended Script Syntax

For more complex scripts, you can use the extended syntax with a dictionary:

```toml
[scripts]
start = {cmd = "python app.py"}
```

This is functionally equivalent to the simple syntax but allows for additional options.

### Calling Python Functions

You can call Python functions directly from your scripts using the `call` option:

```toml
[scripts]
my_function = {call = "package.module:function()"}
my_function_with_args = {call = "package.module:function('arg1', 'arg2')"}
```

When you run `pipenv run my_function`, Pipenv will import the specified module and call the function.

### Combining Commands

You can combine multiple commands using shell syntax:

```toml
[scripts]
setup = "mkdir -p data logs && touch .env && echo 'Setup complete'"
```

For more complex combinations, consider using platform-specific syntax:

```toml
[scripts]
# Unix-like systems
build_and_run = "npm run build && python app.py"

# Windows
build_and_run_win = "npm run build & python app.py"
```

### Environment-Specific Scripts

You can define scripts that set environment variables using standard shell syntax:

```toml
[scripts]
dev = "FLASK_ENV=development FLASK_DEBUG=1 flask run"
prod = "FLASK_ENV=production gunicorn app:app"
```

```{note}
**Important Limitation**: Inline environment variable assignment (like `VAR=value command`) works because the entire command string is passed to the shell. However, more complex shell features like command substitution (`$(command)`) or environment variable expansion within the script definition may not work as expected.

This is because Pipenv parses the script command and executes it directly, rather than always passing it through a full shell interpreter.
```

### Setting Environment Variables for Scripts

For more reliable environment variable handling, use one of these approaches:

#### Using .env Files (Recommended)

Create a `.env` file in your project directory:

```
# .env
PROJECT_DIR=/path/to/project
FLASK_ENV=development
```

Pipenv automatically loads these variables before running scripts:

```toml
[scripts]
dev = "flask run"
```

#### Using Extended Script Syntax with env

You can also define environment variables directly in the script definition using the extended table syntax. However, note that these values are static and cannot use shell expansion:

```toml
[scripts.dev]
cmd = "flask run"
env = {FLASK_ENV = "development", DEBUG = "1"}
```

#### Calling Shell Scripts

For complex scripts that require shell features, call an external shell script:

```toml
[scripts]
dev = "bash scripts/dev.sh"
```

Then in `scripts/dev.sh`:
```bash
#!/bin/bash
export PROJECT_DIR="$(pipenv --where)"
python "$PROJECT_DIR/src/main.py"
```

## Listing Available Scripts

To see all available scripts defined in your `Pipfile`, use the `pipenv scripts` command:

```bash
$ pipenv scripts
command   script
start     python app.py
test      pytest
lint      flake8 .
format    black .
```

This provides a convenient way to discover available commands, especially in projects you're not familiar with.

## Common Script Patterns

### Web Development

```toml
[scripts]
server = "python manage.py runserver"
migrations = "python manage.py makemigrations"
migrate = "python manage.py migrate"
shell = "python manage.py shell"
```

### Data Science

```toml
[scripts]
notebook = "jupyter notebook"
lab = "jupyter lab"
preprocess = "python scripts/preprocess_data.py"
train = "python scripts/train_model.py"
```

### Testing and Quality Assurance

```toml
[scripts]
test = "pytest"
test_cov = "pytest --cov=app tests/"
lint = "flake8 ."
type_check = "mypy ."
format = "black ."
check_format = "black --check ."
security = "pipenv scan"
```

### Build and Deployment

```toml
[scripts]
build = "python setup.py build"
dist = "python setup.py sdist bdist_wheel"
publish = "twine upload dist/*"
docs = "mkdocs build"
serve_docs = "mkdocs serve"
```

## Integration with Other Tools

### npm-style Scripts

If you're familiar with npm scripts, you can create similar workflows:

```toml
[scripts]
start = "python app.py"
dev = "python app.py --debug"
build = "python build.py"
postbuild = "python scripts/post_build.py"
```

### Make-style Tasks

You can emulate Makefile targets:

```toml
[scripts]
all = "pipenv run clean && pipenv run build"
build = "python setup.py build"
clean = "rm -rf build/ dist/ *.egg-info"
install = "pip install -e ."
```

### CI/CD Integration

Define scripts that can be used in CI/CD pipelines:

```toml
[scripts]
ci_test = "pytest --junitxml=test-results.xml"
ci_lint = "flake8 . --output-file=flake8.txt"
ci_type_check = "mypy . --txt-report reports"
```

## Best Practices

### Script Organization

1. **Group related scripts** with consistent naming conventions:
   ```toml
   [scripts]
   test = "pytest"
   test_cov = "pytest --cov=app"
   test_watch = "ptw"
   ```

2. **Use prefixes** for different categories of scripts:
   ```toml
   [scripts]
   db_migrate = "alembic upgrade head"
   db_rollback = "alembic downgrade -1"
   db_reset = "alembic downgrade base"
   ```

3. **Document complex scripts** with comments in your README or documentation.

### Script Composition

1. **Keep scripts focused** on a single responsibility
2. **Compose complex workflows** from simpler scripts
3. **Consider platform compatibility** for scripts that need to run on different operating systems

### Security Considerations

1. **Avoid hardcoding secrets** in scripts; use environment variables instead
2. **Be cautious with scripts** that modify data or perform destructive actions
3. **Consider adding confirmation prompts** for dangerous operations:
   ```toml
   [scripts]
   dangerous_reset = "python -c \"input('Are you sure? [y/N] ') == 'y' or exit(1)\" && python reset_database.py"
   ```

## Troubleshooting

### Common Issues

#### Script Not Found

If you get "Command 'script-name' not found":
- Verify the script is defined in your `Pipfile`
- Check for typos in the script name
- Ensure you're in the correct project directory

#### Script Execution Fails

If a script fails to execute:
- Run with `pipenv run --verbose script-name` for more information
- Check if all required packages are installed
- Verify the command works when run directly in the virtual environment

#### Path-Related Issues

If your script can't find files or executables:
- Use absolute paths or paths relative to the project root
- Set the working directory explicitly in your script
- Print the current directory (`import os; print(os.getcwd())`) for debugging

### Platform-Specific Considerations

#### Windows-Specific Issues

On Windows:
- Use double quotes inside script commands if you need quotes
- Replace Unix-style path separators (`/`) with Windows-style (`\\`) or use raw strings
- Use `&&` for command chaining in CMD or `;&` in PowerShell

#### Unix-Specific Issues

On Unix-like systems:
- Ensure script files have executable permissions if they're being called directly
- Use single quotes for strings that contain double quotes
- Consider using shebang lines in script files

## Advanced Examples

### Dynamic Script Generation

You can generate scripts dynamically using Python:

```python
# build_scripts.py
import toml

# Load existing Pipfile
with open("Pipfile", "r") as f:
    pipfile = toml.load(f)

# Ensure scripts section exists
if "scripts" not in pipfile:
    pipfile["scripts"] = {}

# Add scripts for each module
modules = ["users", "products", "orders"]
for module in modules:
    pipfile["scripts"][f"test_{module}"] = f"pytest tests/{module}"
    pipfile["scripts"][f"lint_{module}"] = f"flake8 app/{module}"

# Write updated Pipfile
with open("Pipfile", "w") as f:
    toml.dump(pipfile, f)
```

### Complex Script Examples

#### Database Management Script

```toml
[scripts]
db_setup = {cmd = "python -c \"from app import db; db.create_all()\""}
db_seed = "python scripts/seed_database.py"
db_migrate = "flask db migrate -m 'Auto-migration'"
db_upgrade = "flask db upgrade"
db_downgrade = "flask db downgrade"
db_reset = "pipenv run db_downgrade && pipenv run db_upgrade && pipenv run db_seed"
```

#### Development Workflow Script

```toml
[scripts]
dev = {cmd = "concurrently \"pipenv run backend\" \"pipenv run frontend\""}
backend = "flask run --port=5000"
frontend = "cd frontend && npm start"
setup = "pipenv install && cd frontend && npm install"
```

#### Deployment Script

```toml
[scripts]
deploy = {cmd = "pipenv run test && pipenv run build && pipenv run publish"}
build = "python setup.py sdist bdist_wheel"
publish = "twine upload dist/*"
```

## Conclusion

Custom script shortcuts in Pipenv provide a powerful way to standardize and simplify common development tasks. By defining scripts in your `Pipfile`, you can create a consistent interface for project-specific commands, improve developer productivity, and document important workflows.

Whether you're using simple command shortcuts or complex function calls, Pipenv scripts help create a more streamlined and maintainable development environment for Python projects.
