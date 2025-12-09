# PEP 751 pylock.toml Support

Pipenv supports [PEP 751](https://peps.python.org/pep-0751/) pylock.toml files, which provide a standardized format for recording Python dependencies to enable installation reproducibility.

## What is pylock.toml?

The pylock.toml file is a standardized lock file format introduced in PEP 751. It is designed to be:

- Human-readable and machine-generated
- Secure by default (includes file hashes)
- Able to support both single-use and multi-use lock files
- Compatible across different Python packaging tools

## Using pylock.toml with Pipenv

Pipenv can automatically detect and use pylock.toml files in your project. When both a Pipfile.lock and a pylock.toml file exist, Pipenv will prioritize the pylock.toml file.

### Reading pylock.toml Files

When you run commands like `pipenv install` or `pipenv sync`, Pipenv will check for a pylock.toml file in your project directory. If found, it will use the dependencies specified in the pylock.toml file instead of Pipfile.lock.

Pipenv looks for pylock.toml files in the following order:
1. A file named `pylock.toml` in the project directory
2. A file matching the pattern `pylock.*.toml` in the project directory

### Example pylock.toml File

Here's a simplified example of a pylock.toml file:

```toml
lock-version = '1.0'
environments = ["sys_platform == 'win32'", "sys_platform == 'linux'", "sys_platform == 'darwin'"]
requires-python = '>=3.8'
extras = []
dependency-groups = ['dev']
default-groups = ['default']
created-by = 'pipenv'

[[packages]]
name = 'requests'
version = '2.28.1'
requires-python = '>=3.7'
index = 'https://pypi.org/simple/'

[[packages.wheels]]
name = 'requests-2.28.1-py3-none-any.whl'
upload-time = '2022-07-13T14:00:00Z'
url = 'https://files.pythonhosted.org/packages/ca/91/6d9b8ccacd0412c08820f72cebaa4f0c61441f4AE7b7338a82051330d70/requests-2.28.1-py3-none-any.whl'
size = 61805
hashes = {sha256 = 'b8aa58f8cf793ffd8782d3d8cb19e66ef36f7aba4353eec859e74678b01b07a7'}

[[packages]]
name = 'pytest'
version = '7.0.0'
marker = "'dev' in dependency_groups"
index = 'https://pypi.org/simple/'
```

## Benefits of Using pylock.toml

- **Standardization**: pylock.toml is a standardized format that can be used by multiple Python packaging tools.
- **Security**: pylock.toml includes file hashes by default, making it more secure against supply chain attacks.
- **Flexibility**: pylock.toml supports extras and dependency groups for multi-use lock files.
- **Interoperability**: pylock.toml can be used by different tools, reducing vendor lock-in.
- **Auditability**: Packages include their index URL for SBOM generation.

## Writing pylock.toml Files

Pipenv can generate pylock.toml files alongside Pipfile.lock files. To enable this feature, add the following to your Pipfile:

```toml
[pipenv]
use_pylock = true
```

With this setting, whenever Pipenv updates the Pipfile.lock file (e.g., when running `pipenv lock`), it will also generate a pylock.toml file in the same directory.

You can also specify a custom name for the pylock.toml file:

```toml
[pipenv]
use_pylock = true
pylock_name = "dev"  # This will generate pylock.dev.toml
```

## CLI Commands

Pipenv provides a `pylock` command for managing pylock.toml files:

### Generate pylock.toml from Pipfile.lock

```bash
pipenv pylock --generate
```

### Generate pylock.toml from pyproject.toml

Create a pylock.toml skeleton from your pyproject.toml dependencies (PEP 621/735):

```bash
pipenv pylock --from-pyproject
```

**Note:** This creates a skeleton file with declared dependencies. Package versions and hashes need to be resolved by running `pipenv lock`.

### Validate pylock.toml

```bash
pipenv pylock --validate
```

### Custom Output Path

```bash
pipenv pylock --generate --output /path/to/pylock.toml
```

### Custom Dependency Groups

Specify which dependency groups should be used for develop packages:

```bash
pipenv pylock --generate --dev-groups "dev,test,docs"
```

## pyproject.toml Support

Pipenv can read dependencies from `pyproject.toml` files following PEP 621 and PEP 735:

- `[project.dependencies]` - Main project dependencies
- `[project.optional-dependencies]` - Optional dependencies (extras)
- `[dependency-groups]` - Dependency groups (PEP 735)

This allows you to use `pyproject.toml` as your primary dependency specification while generating standardized pylock.toml files.

## Marker Evaluation

Pipenv supports PEP 751 marker syntax for extras and dependency groups:

- `'name' in extras` - Include package when extra is enabled
- `'name' in dependency_groups` - Include package when dependency group is enabled

Example:

```toml
[[packages]]
name = 'pytest'
version = '7.0.0'
marker = "'dev' in dependency_groups"
```

## Features

### Implemented

- ✅ Core pylock.toml format (read/write)
- ✅ Bidirectional conversion with Pipfile.lock
- ✅ Package index tracking (`packages.index`)
- ✅ Extras and dependency groups
- ✅ Marker evaluation for filtering packages
- ✅ CLI commands for generation and validation
- ✅ pyproject.toml dependency reading

### Future Enhancements

- VCS package support (`packages.vcs`)
- Local directory support (`packages.directory`)
- Direct archive support (`packages.archive`)
- Attestation identities support
