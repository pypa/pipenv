# Version Specifiers

This guide explains how to specify versions of packages and Python interpreters in Pipenv, including syntax, best practices, and advanced usage patterns.

## Package Version Specifiers

Pipenv uses the same version specifier format as pip, following [PEP 440](https://www.python.org/dev/peps/pep-0440/) standards. These specifiers allow you to control exactly which versions of packages are installed.

### Basic Version Specifiers

| Specifier | Example | Meaning |
|-----------|---------|---------|
| `==` | `requests==2.28.1` | Exact version |
| `>=` | `requests>=2.20.0` | Minimum version |
| `<=` | `requests<=2.30.0` | Maximum version |
| `>` | `requests>2.0.0` | Greater than version |
| `<` | `requests<3.0.0` | Less than version |
| `!=` | `requests!=2.29.0` | Not equal to version |
| `~=` | `requests~=2.28.0` | Compatible release (equivalent to `>=2.28.0,<2.29.0`) |
| `*` | `requests==*` | Any version (not recommended for production) |

### Combining Version Specifiers

You can combine specifiers to create version ranges:

```bash
# Install any version between 2.20.0 and 3.0.0
$ pipenv install "requests>=2.20.0,<3.0.0"
```

```{note}
The use of double quotes around the package and version specification (i.e. `"requests>=2.20.0,<3.0.0"`) is highly recommended to avoid issues with shell interpretation, especially on Unix-based systems.
```

### Compatible Release Operator

The `~=` operator (compatible release) is particularly useful:

```bash
# Install version 2.28.* (>=2.28.0,<2.29.0)
$ pipenv install "requests~=2.28.0"

# Install version 2.* (>=2.0.0,<3.0.0)
$ pipenv install "requests~=2.0"
```

This ensures you get bug fixes (micro version updates) but not potentially breaking changes (major or minor version updates, depending on how you specify it).

### Wildcard Versions

While not recommended for production, you can use wildcards:

```bash
# Install the latest version
$ pipenv install "requests==*"
# or simply
$ pipenv install requests
```

### Pre-release Versions

By default, Pipenv doesn't install pre-release versions. To include them:

```bash
# Command line flag
$ pipenv install --pre "requests>=2.0.0"

# Or in Pipfile
# [pipenv]
# allow_prereleases = true
```

## Python Version Specifiers

### Specifying Python Version for a Project

You can specify which Python version to use when creating a virtual environment:

```bash
# Use Python 3
$ pipenv --python 3

# Use Python 3.10 specifically
$ pipenv --python 3.10

# Use a specific Python executable
$ pipenv --python /usr/local/bin/python3.10
```

This creates a `Pipfile` with a `[requires]` section:

```toml
[requires]
python_version = "3.10"
```

### Python Version vs. Full Version

You can specify either a Python version or a full version:

```toml
# In your Pipfile
[requires]
python_version = "3.10"  # Any 3.10.x version
```

Or for more specific control:

```toml
# In your Pipfile
[requires]
python_full_version = "3.10.4"  # Exactly Python 3.10.4
```

### Python Version Selection Logic

When you run `pipenv install` without specifying a Python version:

1. Pipenv checks the `[requires]` section in the `Pipfile`
2. If `python_full_version` is specified, it tries to use that exact version
3. If `python_version` is specified, it tries to find a compatible version
4. If neither is specified, it uses the default Python interpreter

## Advanced Version Specifiers

### VCS Dependencies

You can install packages directly from version control systems:

```bash
# From a Git repository
$ pipenv install -e git+https://github.com/requests/requests.git@v2.31.0#egg=requests
```

The format follows this pattern:

```
<vcs_type>+<scheme>://<location>/<user_or_organization>/<repository>@<branch_or_tag>#egg=<package_name>
```

Where:
- `<vcs_type>` can be `git`, `bzr`, `svn`, or `hg`
- `<scheme>` can be `http`, `https`, `ssh`, or `file`
- `@<branch_or_tag>` is optional and specifies a specific branch, tag, or commit

This will be reflected in your `Pipfile`:

```toml
[packages]
requests = {editable = true, git = "https://github.com/requests/requests.git", ref = "v2.31.0"}
```

### Local Path Dependencies

You can install packages from a local path:

```bash
# Install a local package in editable mode
$ pipenv install -e ./path/to/package
```

This will be reflected in your `Pipfile`:

```toml
[packages]
my-package = {editable = true, path = "./path/to/package"}
```

### Platform-Specific Dependencies

You can specify that a package should only be installed on certain platforms using [PEP 508](https://www.python.org/dev/peps/pep-0508/) markers:

```bash
# Install pywinusb only on Windows
$ pipenv install "pywinusb ; sys_platform == 'win32'"
```

This will be reflected in your `Pipfile`:

```toml
[packages]
pywinusb = {version = "*", markers = "sys_platform == 'win32'"}
```

### Python Version-Specific Dependencies

You can specify dependencies that are only needed for certain Python versions:

```toml
[packages]
typing = {version = ">=3.6.2", markers = "python_version < '3.5'"}
dataclasses = {version = ">=0.8", markers = "python_version < '3.7'"}
```

### Complex Markers

You can use complex logical expressions in markers:

```toml
[packages]
unittest2 = {version = ">=1.0,<3.0", markers = "python_version < '2.7.9' or (python_version >= '3.0' and python_version < '3.4')"}
```

Common markers include:
- `python_version`: Python version in 'X.Y' format
- `python_full_version`: Python version in 'X.Y.Z' format
- `sys_platform`: Platform name (e.g., 'win32', 'linux', 'darwin')
- `platform_machine`: Machine type (e.g., 'x86_64', 'i386')
- `platform_python_implementation`: Python implementation (e.g., 'CPython', 'PyPy')
- `os_name`: Name of the operating system (e.g., 'posix', 'nt')

### Package Extras

Many packages provide optional features as "extras":

```bash
# Install requests with the 'security' and 'socks' extras
$ pipenv install "requests[security,socks]"
```

This will be reflected in your `Pipfile`:

```toml
[packages]
requests = {version = "*", extras = ["security", "socks"]}
```

## Package Categories

Pipenv supports organizing dependencies into different categories beyond the standard `packages` and `dev-packages`.

### Defining Custom Categories

In your `Pipfile`:

```toml
[packages]
requests = "*"

[dev-packages]
pytest = "*"

[docs]
sphinx = "*"
sphinx-rtd-theme = "*"

[tests]
pytest-cov = "*"
```

### Installing Specific Categories

```bash
# Install a package in a specific category
$ pipenv install sphinx --categories="docs"

# Install all packages from specific categories
$ pipenv install --categories="docs,tests"
```

### Locking Specific Categories

```bash
# Lock only specific categories
$ pipenv lock --categories="docs,tests"
```

## Best Practices

### For Applications

For applications, use specific versions to ensure stability:

```toml
[packages]
# Exact version for critical dependencies
requests = "==2.28.1"
# Compatible release for less critical dependencies
flask = "~=2.0.1"
# Version range for flexible dependencies
urllib3 = ">=1.26.0,<2.0.0"
```

### For Libraries

For libraries, use more flexible version constraints:

```toml
[packages]
# Minimum version only
requests = ">=2.20.0"
# Upper bound to prevent incompatible versions
urllib3 = "<2.0.0"
```

### Security Considerations

- Regularly update dependencies to get security fixes
- Use `pipenv scan` to check for vulnerabilities
- Avoid using `*` or very loose constraints in production
- Consider using hash verification with `pipenv lock`

### Dependency Resolution

When specifying versions, consider:

1. **Compatibility**: Ensure your constraints don't conflict with other packages
2. **Flexibility**: Overly strict constraints can make dependency resolution difficult
3. **Security**: Too loose constraints might introduce vulnerabilities
4. **Stability**: Balance between getting updates and maintaining stability

## Troubleshooting

### Common Issues

#### Version Conflict Resolution

If you encounter version conflicts:

```bash
# Try with verbose output to see the conflict
$ pipenv install --verbose

# Try relaxing version constraints
# Instead of requests==2.28.1, try requests~=2.28.0
```

#### No Matching Distribution Found

If pip can't find a matching distribution:

1. Check that the version exists on PyPI
2. Verify your version specifier syntax
3. Consider if you need pre-release versions (`--pre`)

#### Dependency Resolution Failures

If Pipenv can't resolve dependencies:

```bash
# Clear the cache and try again
$ pipenv lock --clear
```

## Conclusion

Understanding version specifiers is crucial for effective dependency management with Pipenv. By using the right specifiers, you can balance stability, security, and flexibility in your Python projects.
