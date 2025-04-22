# Migrating to Pipenv

This guide provides step-by-step instructions for migrating to Pipenv from other Python dependency management tools. Whether you're coming from requirements.txt, pip, conda, or other tools, this guide will help you transition smoothly.

## Migrating from requirements.txt

The `requirements.txt` file is a common way to specify Python dependencies. Pipenv provides a straightforward path to migrate from requirements.txt.

### Basic Migration

1. Navigate to your project directory:
   ```bash
   $ cd your-project
   ```

2. Import your requirements.txt file:
   ```bash
   $ pipenv install -r requirements.txt
   ```

   This command:
   - Creates a new virtual environment if one doesn't exist
   - Creates a Pipfile with your dependencies
   - Installs all packages from requirements.txt

3. Verify the generated Pipfile:
   ```bash
   $ cat Pipfile
   ```

4. Generate a lock file:
   ```bash
   $ pipenv lock
   ```

5. Test that everything works:
   ```bash
   $ pipenv run python your_script.py
   ```

### Handling Development Dependencies

If you have separate requirements files for development and production:

1. Import production dependencies:
   ```bash
   $ pipenv install -r requirements.txt
   ```

2. Import development dependencies:
   ```bash
   $ pipenv install -r dev-requirements.txt --dev
   ```

### Handling Complex Requirements Files

For requirements files with complex constraints or comments:

1. Import the basic requirements:
   ```bash
   $ pipenv install -r requirements.txt
   ```

2. Review the Pipfile and adjust as needed:
   - Remove unnecessary constraints
   - Add missing constraints
   - Organize dependencies logically

3. For packages with complex installation options, you may need to add them manually:
   ```bash
   $ pipenv install package-name
   ```

4. Regenerate the lock file:
   ```bash
   $ pipenv lock
   ```

### Example: Converting a Django Project

```bash
# Start with a Django project using requirements.txt
$ cd django-project

# Import production requirements
$ pipenv install -r requirements.txt

# Import development requirements
$ pipenv install -r requirements-dev.txt --dev

# Review and adjust the Pipfile
$ nano Pipfile

# Generate the lock file
$ pipenv lock

# Test that Django works
$ pipenv run python manage.py runserver
```

## Migrating from pip

If you've been using pip directly without requirements.txt files, you'll need to identify your dependencies first.

### Identifying Current Dependencies

1. List installed packages:
   ```bash
   $ pip freeze > requirements.txt
   ```

2. Review the requirements.txt file and remove packages that aren't direct dependencies of your project.

3. Follow the steps in the "Migrating from requirements.txt" section above.

### Alternative Approach: Fresh Start

If your environment has many packages and it's hard to identify direct dependencies:

1. Create a new Pipenv environment:
   ```bash
   $ mkdir temp-project
   $ cd temp-project
   $ pipenv --python 3.x  # Use your current Python version
   ```

2. Install your main dependencies one by one:
   ```bash
   $ pipenv install django
   $ pipenv install requests
   # etc.
   ```

3. Install development dependencies:
   ```bash
   $ pipenv install pytest --dev
   $ pipenv install black --dev
   # etc.
   ```

4. Copy the Pipfile and Pipfile.lock to your original project:
   ```bash
   $ cp Pipfile Pipfile.lock /path/to/original/project/
   $ cd /path/to/original/project/
   $ pipenv install
   ```

## Migrating from virtualenv/venv

If you're using virtualenv or venv with pip:

1. Activate your existing virtual environment:
   ```bash
   $ source venv/bin/activate  # or equivalent for your OS
   ```

2. Generate a requirements file:
   ```bash
   $ pip freeze > requirements.txt
   ```

3. Deactivate the virtual environment:
   ```bash
   $ deactivate
   ```

4. Initialize Pipenv and import requirements:
   ```bash
   $ pipenv install -r requirements.txt
   ```

5. Optionally, remove the old virtual environment:
   ```bash
   $ rm -rf venv/  # Use appropriate command for your OS
   ```

## Migrating from Poetry

Poetry is another modern Python dependency management tool. Migrating from Poetry to Pipenv requires a few steps.

### Basic Migration

1. Export Poetry dependencies to requirements.txt:
   ```bash
   $ poetry export -f requirements.txt --output requirements.txt
   $ poetry export -f requirements.txt --dev --output dev-requirements.txt
   ```

2. Initialize Pipenv and import requirements:
   ```bash
   $ pipenv install -r requirements.txt
   $ pipenv install -r dev-requirements.txt --dev
   ```

3. Review the Pipfile and adjust as needed:
   ```bash
   $ nano Pipfile
   ```

4. Generate the lock file:
   ```bash
   $ pipenv lock
   ```

### Handling Poetry-Specific Features

Some Poetry features don't have direct equivalents in Pipenv:

1. **Scripts**: Poetry's `[tool.poetry.scripts]` can be converted to Pipenv's `[scripts]` section.

2. **Package building**: If you're developing a library, you'll still need a `setup.py` or `pyproject.toml` for distribution.

3. **Extra dependencies**: Convert Poetry's extras to Pipenv's package options.

   Poetry:
   ```toml
   [tool.poetry.extras]
   docs = ["sphinx"]
   ```

   Pipenv:
   ```toml
   [packages]
   your-package = {path = ".", extras = ["docs"]}
   ```

## Migrating from Conda

Conda is a package manager that handles both Python and non-Python packages. Migrating from Conda to Pipenv requires some additional steps.

### Basic Migration

1. Export Conda environment to a file:
   ```bash
   $ conda env export --from-history > environment.yml
   ```

2. Extract Python packages from the environment file:
   ```bash
   $ grep -v "prefix:" environment.yml | grep -v "^name:" > conda_env.yml
   ```

3. Convert Conda packages to pip requirements (you may need to do this manually):
   ```bash
   # Create a requirements.txt file with Python packages from conda_env.yml
   ```

4. Initialize Pipenv and import requirements:
   ```bash
   $ pipenv install -r requirements.txt
   ```

### Handling Non-Python Dependencies

Conda often manages non-Python dependencies that Pipenv can't handle. For these:

1. Document the non-Python dependencies separately.

2. Consider using Docker to manage system-level dependencies.

3. For development, you might need to install these dependencies using your system package manager.

## Migrating from pipenv-setup

If you're using pipenv-setup to maintain both Pipfile and setup.py:

1. Keep your setup.py or convert it to pyproject.toml.

2. Use Pipenv for development dependencies and environment management.

3. Continue to use pip/setuptools for package distribution.

## Best Practices After Migration

After migrating to Pipenv, follow these best practices:

### 1. Clean Up Old Files

Remove old dependency management files that are no longer needed:

```bash
$ rm -f requirements.txt dev-requirements.txt requirements-dev.txt
```

Keep setup.py or pyproject.toml if you're developing a library.

### 2. Update Documentation

Update your project documentation to reflect the new workflow:

- Installation instructions
- Development setup
- Contribution guidelines

### 3. Update CI/CD Pipelines

Update your continuous integration and deployment pipelines:

```yaml
# Example GitHub Actions workflow
steps:
  - uses: actions/checkout@v3
  - uses: actions/setup-python@v4
    with:
      python-version: '3.10'
  - name: Install pipenv
    run: pip install pipenv
  - name: Install dependencies
    run: pipenv install --dev
  - name: Run tests
    run: pipenv run pytest
```

### 4. Commit Both Pipfile and Pipfile.lock

Ensure both files are committed to version control:

```bash
$ git add Pipfile Pipfile.lock
$ git commit -m "Migrate to Pipenv"
```

### 5. Review and Optimize Dependencies

After migration, review your dependencies:

1. Remove unnecessary dependencies:
   ```bash
   $ pipenv uninstall unnecessary-package
   ```

2. Update outdated packages:
   ```bash
   $ pipenv update --outdated
   $ pipenv update
   ```

3. Check for security vulnerabilities:
   ```bash
   $ pipenv scan
   ```

## Common Migration Issues and Solutions

### Issue: Dependency Resolution Conflicts

**Problem**: Pipenv can't resolve dependencies due to conflicts.

**Solution**:
1. Identify conflicting dependencies:
   ```bash
   $ pipenv graph
   ```
2. Relax version constraints in your Pipfile.
3. Try clearing the cache:
   ```bash
   $ pipenv lock --clear
   ```

### Issue: Missing System Dependencies

**Problem**: Packages with C extensions fail to install due to missing system dependencies.

**Solution**:
1. Install required system packages:
   ```bash
   # Ubuntu/Debian
   $ sudo apt-get install build-essential python3-dev

   # macOS
   $ xcode-select --install
   ```
2. Consider using a Docker container with all required system dependencies.

### Issue: Different Package Versions

**Problem**: Pipenv resolves to different package versions than your previous tool.

**Solution**:
1. Specify exact versions in your Pipfile:
   ```toml
   [packages]
   requests = "==2.28.1"
   ```
2. Use `pipenv install --ignore-pipfile` to install exactly what's in the lock file.

### Issue: Private Repositories

**Problem**: Can't access private repositories.

**Solution**:
1. Configure additional sources in your Pipfile:
   ```toml
   [[source]]
   name = "private"
   url = "https://private-repo.example.com/simple"
   verify_ssl = true
   ```
2. Use environment variables for authentication:
   ```bash
   $ export PIP_EXTRA_INDEX_URL=https://user:password@private-repo.example.com/simple
   ```

## Migration Checklist

Use this checklist to ensure a successful migration:

- [ ] Export dependencies from existing tool
- [ ] Initialize Pipenv environment
- [ ] Import dependencies into Pipenv
- [ ] Review and adjust the Pipfile
- [ ] Generate Pipfile.lock
- [ ] Test that the application works
- [ ] Update documentation
- [ ] Update CI/CD pipelines
- [ ] Commit Pipfile and Pipfile.lock to version control
- [ ] Remove old dependency files
- [ ] Train team members on Pipenv workflow

## Conclusion

Migrating to Pipenv provides several benefits:

- Simplified dependency management
- Deterministic builds with lock files
- Better security through hash verification
- Improved development workflow

While the migration process requires some effort, the long-term benefits make it worthwhile for most Python projects.

If you encounter issues during migration, refer to the [Troubleshooting](troubleshooting.md) guide or seek help from the Pipenv community.
