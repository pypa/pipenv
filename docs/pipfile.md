# Pipfile & Pipfile.lock

Pipenv uses two files to manage project dependencies: `Pipfile` and `Pipfile.lock`. This document explains their purpose, structure, and best practices for working with them.

## Overview

| File | Purpose | Managed By | Format |
|------|---------|------------|--------|
| `Pipfile` | Declares top-level project dependencies and constraints | Developers | [TOML](https://toml.io/en/latest) |
| `Pipfile.lock` | Records exact versions and hashes of all resolved dependencies | Pipenv automatically | JSON |

Both files should be committed to version control to ensure consistent environments across development and deployment.

## Pipfile

The `Pipfile` is a human-readable, TOML-formatted file that declares your project's dependencies. It replaces the traditional `requirements.txt` file with a more powerful and flexible format.

### Pipfile Structure

A typical `Pipfile` contains the following sections:

```toml
[[source]]
# Package sources (PyPI, private repositories, etc.)

[packages]
# Production dependencies

[dev-packages]
# Development dependencies

[requires]
# Python version requirements

[scripts]
# Custom script definitions

[pipenv]
# Pipenv configuration directives

[custom-category]
# Custom package categories (e.g., docs, tests)
```

### Source Section

The `[[source]]` section defines where packages should be downloaded from:

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

# You can specify multiple sources
[[source]]
url = "https://private-repo.example.com/simple"
verify_ssl = true
name = "private"
```

### Packages Section

The `[packages]` section lists production dependencies:

```toml
[packages]
# Simple version specification
requests = "*"                # Any version
flask = "==2.0.1"             # Exact version
numpy = ">=1.20.0,<2.0.0"     # Version range
pandas = "~=1.3.0"            # Compatible release

# Extended syntax with additional options
django = {version = ">=3.2", extras = ["bcrypt"]}
sentry-sdk = {version = ">=1.0.0", extras = ["flask"]}

# Git repositories
flask-login = {git = "https://github.com/maxcountryman/flask-login.git", ref = "master"}

# Local paths (relative filesystem path)
my-package = { path = "./path/to/local/package" }

# Remote file URLs (wheel or sdist hosted over HTTP/HTTPS)
my-package = { file = "https://example.com/packages/my-package-1.0.tar.gz" }

# Platform-specific dependencies
gunicorn = {version = "*", markers = "sys_platform == 'linux'"}
waitress = {version = "*", markers = "sys_platform == 'win32'"}

# Index-specific packages
private-package = {version = "*", index = "private"}
```

Local path dependencies use the `path` attribute, and remote file URL dependencies
use the `file` attribute.

**`path`** — a relative (or absolute) filesystem path to a local package directory
or archive:

By default, Pipenv performs a standard (non-editable) installation:

```toml
[packages]
my-package = { path = "./path/to/local/package" }
```

To install the package in development (editable) mode (`pipenv install -e ./my-package`):

```toml
[packages]
my-package = { path = "./my-package", editable = true }
```

Editable installs mirror `pip install -e` behavior and reflect changes to
the source immediately.  Pipenv writes `{ path = "./my-package", editable = true }`
when you run `pipenv install -e ./my-package`.

> **Compatibility note**: Older Pipfiles may store the same entry without the
> `./` prefix (e.g. `path = "my-package"`) or without the `editable = true`
> flag.  Both forms are still accepted — Pipenv normalises them internally.
> Older Pipenv versions also implicitly treated every path dependency as
> editable; newer versions require `editable = true` to be explicit.

**`file`** — an HTTP or HTTPS URL pointing to a remote wheel (`.whl`) or source
distribution (`.tar.gz`, `.zip`):

```toml
[packages]
my-package = { file = "https://example.com/packages/my-package-1.0.tar.gz" }
```

> **`path` vs `file`**: use `path` for local filesystem locations (directories or
> archives on disk) and `file` for remote HTTP/HTTPS URLs.  Running
> `pipenv install -e ./my-package` always writes
> `{ path = "./my-package", editable = true }` to your Pipfile.

### Development Packages Section

The `[dev-packages]` section lists dependencies needed only for development:

```toml
[dev-packages]
pytest = ">=6.0.0"
black = "==21.5b2"
mypy = "*"
sphinx = {version = ">=4.0.0", extras = ["docs"]}
```

#### Pinning a Package in `dev-packages` That Is Also a Production Dependency

If a package is required by a production dependency (listed under `[packages]`) *and*
you also pin it explicitly in `[dev-packages]`, the resolver treats both sections as
part of a single unified dependency graph. The production dependency's constraints
take precedence when they conflict.

For example:

```toml
[packages]
apispec = "*"       # apispec depends on `packaging` (any version)

[dev-packages]
packaging = "==21.3"  # Pinned to an older version
```

Here, `packaging` will be resolved to whatever version satisfies `apispec`'s
requirement (e.g. `==22.0`), **not** necessarily `==21.3`. No resolution error
is raised because `apispec = "*"` allows any version of `packaging`.

```{note}
This is intentional behaviour: Pipenv uses a single resolver for all categories and
there is only one installed version of each package per environment. To enforce a
specific version, add the pin to `[packages]` as well, or tighten the constraint on
the package that requires it (e.g. `apispec = {version = "*", dependencies = {packaging = "==21.3"}}`
is not valid Pipfile syntax; instead use `pipenv install "packaging==21.3"` so the
pin appears in `[packages]`).
```

### Python Version Requirements

The `[requires]` section specifies Python version constraints:

```toml
[requires]
python_version = "3.9"        # Requires Python 3.9.x
# OR
python_full_version = "3.9.6" # Requires exactly Python 3.9.6
```

### Custom Scripts

The `[scripts]` section defines shortcuts for common commands:

```toml
[scripts]
start = "python app.py"
test = "pytest tests/"
lint = "flake8 ."
docs = "sphinx-build -b html docs/ docs/_build"
```

You can run these scripts using `pipenv run <script-name>`.

### Pipenv Directives

The `[pipenv]` section controls Pipenv's behavior:

```toml
[pipenv]
allow_prereleases = true       # Allow pre-release versions
disable_pip_input = true       # Prevent pipenv from asking for input
install_search_all_sources = true  # Search all sources when installing from lock
sort_pipfile = true            # Sort packages alphabetically
```

### Custom Package Categories

You can define custom package categories beyond the standard `packages` and `dev-packages`:

```toml
[docs]
sphinx = ">=4.0.0"
sphinx-rtd-theme = "*"

[tests]
pytest = "*"
pytest-cov = "*"
```

## Pipfile.lock

The `Pipfile.lock` file is automatically generated by Pipenv when you run `pipenv lock` or when you install/uninstall packages. It contains:

1. Exact versions of all direct and transitive dependencies
2. Cryptographic hashes for each package
3. Package metadata and requirements

### Pipfile.lock Structure

```json
{
    "_meta": {
        "hash": {
            "sha256": "<hash-of-pipfile-contents>"
        },
        "pipfile-spec": 6,
        "requires": {
            "python_version": "3.9"
        },
        "sources": [
            {
                "name": "pypi",
                "url": "https://pypi.org/simple",
                "verify_ssl": true
            }
        ]
    },
    "default": {
        // Production dependencies and their sub-dependencies
        "package-name": {
            "hashes": [
                "sha256:hash1",
                "sha256:hash2"
            ],
            "index": "pypi",
            "version": "==1.2.3"
        },
        // ...
    },
    "develop": {
        // Development dependencies and their sub-dependencies
        // ...
    },
    "docs": {
        // Custom category dependencies
        // ...
    }
}
```

### Package Categories in Pipfile.lock

Note the naming difference between Pipfile and Pipfile.lock:

- `[packages]` in Pipfile corresponds to `"default"` in Pipfile.lock
- `[dev-packages]` in Pipfile corresponds to `"develop"` in Pipfile.lock
- Custom categories use the same name in both files

## Best Practices

### Version Specifiers

Choose appropriate version specifiers based on your needs:

| Specifier | Example | Meaning |
|-----------|---------|---------|
| `*` | `requests = "*"` | Any version (not recommended for production) |
| `==` | `flask = "==2.0.1"` | Exact version |
| `>=` | `django = ">=3.2"` | Minimum version |
| `<=` | `numpy = "<=1.20.0"` | Maximum version |
| `>=,<` | `pandas = ">=1.3.0,<2.0.0"` | Version range |
| `~=` | `pytest = "~=6.2.0"` | Compatible release (equivalent to `>=6.2.0,<6.3.0`) |

For production environments, it's recommended to use specific version constraints to ensure reproducibility.

### Dependency Management Workflow

1. **Initial setup**: Create a `Pipfile` with your top-level dependencies
   ```bash
   $ pipenv install requests flask
   $ pipenv install pytest --dev
   ```

2. **Lock dependencies**: Generate a `Pipfile.lock` with exact versions
   ```bash
   $ pipenv lock
   ```

3. **Install from lock**: Install the exact versions from `Pipfile.lock`
   ```bash
   $ pipenv sync
   ```

4. **Update dependencies**: Update to newer versions when needed
   ```bash
   $ pipenv update
   ```

### Importing from requirements.txt

If you're migrating from a project that uses `requirements.txt`, you can import it:

```bash
$ pipenv install -r requirements.txt
```

This will create a `Pipfile` and install all packages from the requirements file.

### Generating requirements.txt

You can generate a `requirements.txt` file from your `Pipfile.lock`:

```bash
$ pipenv requirements > requirements.txt
```

This is useful for environments that don't support Pipenv directly.

### Security Considerations

The `Pipfile.lock` includes cryptographic hashes for each package, which are verified during installation. This prevents supply chain attacks where a malicious package could be substituted.

For CI/CD deployments:

1. Use `pipenv verify` to ensure the lock file is up-to-date
2. Use `pipenv install --deploy` to fail if the lock file is out of sync
3. Never run commands that modify the lock file in CI/CD (like `lock`, `update`, or `upgrade`)

## Advanced Usage

### Package Markers

You can use [PEP 508](https://www.python.org/dev/peps/pep-0508/) markers to specify environment-specific dependencies:

```toml
[packages]
gunicorn = {version = "*", markers = "sys_platform == 'linux'"}
waitress = {version = "*", markers = "sys_platform == 'win32'"}
colorama = {version = "*", markers = "python_version >= '3.7'"}
```

Pipenv also supports shorthand keys for common markers. These are equivalent to using the full `markers` syntax:

```toml
[packages]
# Shorthand form — these marker keys are recognized directly:
gunicorn = {version = "*", sys_platform = "== 'linux'"}
arm-optimized = {version = "*", platform_machine = "== 'arm64'"}
```

All [PEP 508 environment marker](https://peps.python.org/pep-0508/#environment-markers) keys are supported, including `sys_platform`, `platform_machine`, `platform_system`, `os_name`, `python_version`, `python_full_version`, `platform_python_implementation`, and `implementation_name`.

For more details and architecture-specific examples, see [Platform-Specific Dependencies](specifiers.md#platform-specific-dependencies).

### Package Extras

Many packages provide optional features as "extras":

```toml
[packages]
requests = {version = "*", extras = ["socks", "security"]}
django = {version = "*", extras = ["bcrypt"]}
```

### Git Dependencies

You can install packages directly from Git repositories:

```toml
[packages]
flask-login = {git = "https://github.com/maxcountryman/flask-login.git", ref = "master"}
custom-package = {git = "https://github.com/user/repo.git", editable = true}
```

### Local and Remote File Dependencies

For local development of packages, use the `path` attribute with a filesystem path:

```toml
[packages]
my-package = { path = "./path/to/package" }
```

This performs a regular (non-editable) installation.

To install in development (editable) mode:

```toml
[packages]
my-package = { path = "./path/to/package", editable = true }
```

The `editable` flag installs the package in development mode, so changes to the source code are immediately reflected.

> If `editable` is omitted, Pipenv will perform a standard installation
> instead of a development install.

For packages hosted at a remote URL (wheel or sdist), use the `file` attribute:

```toml
[packages]
my-package = { file = "https://example.com/packages/my-package-1.0-py3-none-any.whl" }
```

> **`path` vs `file`**: use `path` for local filesystem locations and `file` for
> remote HTTP/HTTPS URLs. Running `pipenv install -e .` always writes
> `{ path = ".", editable = true }` to your Pipfile.

#### Migrating from older Pipfile formats

Older Pipenv versions wrote editable local installs without the `./` prefix or
(in some releases) using the `file` key instead of `path`:

```toml
# Older format — still accepted by Pipenv
my-package = { path = "my-package", editable = true }
```

These are equivalent to the canonical modern form:

```toml
# Modern canonical form — written by current Pipenv
my-package = { path = "./my-package", editable = true }
```

Pipenv normalises both forms at install and lock time, so no manual migration
is required.  If you want your Pipfile to reflect the current canonical format,
simply run `pipenv install -e ./my-package` again and Pipenv will rewrite the
entry.

#### Editable installs and build isolation

By default, pip builds each package in an isolated environment.  When you have
many editable local packages that share the same build dependencies (e.g.
`setuptools`), this results in those dependencies being installed once per
package, which can be slow.

Setting `PIP_NO_BUILD_ISOLATION=0` (or `--no-build-isolation` in
`PIPENV_EXTRA_PIP_ARGS`) tells pip to reuse the virtual environment for all
builds.  **However, this introduces a race condition when pipenv installs
packages in parallel**: if `setuptools` (or another build backend) is being
upgraded at the same time as an editable package is being built, the build can
fail with a `BackendUnavailable` error.

Recommended mitigations:

1. **Use named categories to stage build dependencies first.**  Install build
   backends (e.g. `setuptools`, `wheel`) in a dedicated category and sync that
   category before the main packages:

   ```toml
   [build-deps]
   setuptools = "*"
   wheel = "*"
   ```

   ```bash
   pipenv sync --categories="build-deps packages"
   ```

2. **Pin your build backend version** in `[packages]` so it is never upgraded
   in parallel with an editable install:

   ```toml
   [packages]
   setuptools = "*"
   my-editable-pkg = { path = "./my-editable-pkg", editable = true }
   ```

   Because named (non-editable) packages are installed before editable ones in
   the same category, `setuptools` will always be present and stable before
   `my-editable-pkg` is built.

3. **Keep `PIP_NO_BUILD_ISOLATION=1`** (the default) unless you have a
   compelling performance reason.  Isolated builds are slower but immune to
   the race condition described above.

## Troubleshooting

### Lock File Hash Mismatch

If you see an error about the Pipfile.lock hash not matching:

```
Pipfile.lock out of date, update it with "pipenv lock" or "pipenv update".
```

This means your `Pipfile` has been modified since the last time `Pipfile.lock` was generated. Run `pipenv lock` to update the lock file.

### Dependency Resolution Failures

If Pipenv can't resolve dependencies:

1. Try clearing the cache: `pipenv lock --clear`
2. Check for conflicting version requirements
3. Consider relaxing version constraints in your Pipfile
4. Use `pipenv install --verbose` to see detailed resolution information

### Manually Editing Files

- **Pipfile**: Safe to edit manually, but follow TOML syntax rules
- **Pipfile.lock**: Do not edit manually; always use Pipenv commands to modify

### Editable Install Fails with `BackendUnavailable` (build isolation disabled)

**Symptom**: When `PIP_NO_BUILD_ISOLATION=0` is set and you have multiple
editable packages, `pipenv sync` fails with an error like:

```
pipenv.patched.pip._vendor.pyproject_hooks._impl.BackendUnavailable:
  ImportError: The 'importlib_metadata' package is required; normally this is
  bundled with this package so if you get this warning, consult the packager
  of your distribution.
```

**Cause**: Pipenv installs packages in parallel.  With build isolation
disabled, all packages share the same virtual environment for building.  If
`setuptools` (or another build backend) is being upgraded in one thread while
another thread is trying to use it to build an editable package, the build
backend can fail mid-import.

**Solutions** (in order of preference):

1. **Restore build isolation** (`PIP_NO_BUILD_ISOLATION=1`, the default).
   Each package gets its own clean build environment so there is no race
   condition.  Accept the extra install time as a trade-off for reliability.

2. **Stage build dependencies with named categories** so they are always
   installed before packages that need them:

   ```toml
   [build-deps]
   setuptools = "*"
   wheel = "*"

   [packages]
   my-editable-pkg = { path = "./my-editable-pkg", editable = true }
   ```

   ```bash
   pipenv sync --categories="build-deps packages"
   ```

3. **Include build backends in `[packages]`** so they are installed (as
   non-editable, named packages) before the editable packages in the same
   category.  Pipenv installs all non-editable packages before editable ones
   within a single category:

   ```toml
   [packages]
   setuptools = "*"
   my-editable-pkg = { path = "./my-editable-pkg", editable = true }
   ```

See [Editable installs and build isolation](#editable-installs-and-build-isolation)
in the Advanced Usage section for a fuller explanation.
