# Package Indexes

This guide explains how to work with Python package indexes in Pipenv, including using alternative indexes, private repositories, and security considerations.

## Understanding Package Indexes

A package index is a repository of Python packages that can be installed using pip or Pipenv. The default and most widely used index is the [Python Package Index (PyPI)](https://pypi.org), but you may need to use alternative or additional indexes in certain situations.

## Configuring Package Sources

### Default PyPI Source

By default, Pipenv uses PyPI as the source for packages. This is defined in your `Pipfile`:

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"
```

### Adding Additional Sources

You can add additional package sources to your `Pipfile`:

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://custom-index.example.com/simple"
verify_ssl = true
name = "custom"
```

Each source must have:
- A unique `name` identifier
- A valid `url` pointing to a package repository
- A `verify_ssl` setting (set to `false` only if absolutely necessary)

## Index-Restricted Packages

Starting with Pipenv version `2022.3.23`, all packages are mapped to a single package index for security reasons. This means that each package must be explicitly associated with a specific index.

### Specifying Package Index

To install a package from a specific index, you must match the name of the index:

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://download.pytorch.org/whl/cu113/"
verify_ssl = true
name = "pytorch"

[packages]
requests = "*"  # From default PyPI index
torch = {version = "*", index = "pytorch"}  # From PyTorch index
```

### Installing from a Specific Index

You can specify the index when installing a package:

```bash
$ pipenv install torch --index=pytorch
```

You can also specify the index by URL, and Pipenv will add it to the `Pipfile` with a generated name (or reuse an existing name if the URL already exists):

```bash
$ pipenv install torch --index=https://download.pytorch.org/whl/cu113/
```

```{note}
In prior versions of Pipenv, you could use `--extra-index-urls` to search multiple indexes without specifying which package came from which index. This functionality was deprecated in favor of index-restricted packages for security reasons.
```

## Security Considerations

### Dependency Confusion Attacks

The index restriction feature was implemented to protect against dependency confusion attacks. This type of attack occurs when:

1. A private package is hosted on a private index
2. An attacker publishes a malicious package with the same name on a public index
3. The package manager searches the public index before the private one
4. The malicious package is installed instead of the legitimate private package

By requiring explicit index specification for each package, Pipenv prevents this attack vector.

### Using Private Indexes Securely

When using private package repositories:

1. Always use HTTPS URLs with SSL verification enabled
2. Use environment variables for authentication credentials
3. Explicitly specify which packages come from which index
4. Consider using a private mirror of PyPI that includes both public and private packages

## Using PyPI Mirrors

If you need to use a mirror of PyPI (for example, due to network restrictions or performance reasons), you can use the `--pypi-mirror` option:

```bash
$ pipenv install --pypi-mirror https://mirrors.aliyun.com/pypi/simple/
```

This will replace the default PyPI URL with the specified mirror for that command.

You can also set a default mirror using an environment variable:

```bash
$ export PIPENV_PYPI_MIRROR=https://mirrors.aliyun.com/pypi/simple/
$ pipenv install requests
```

## Alternative Default Index

If you want to use an alternative index as your default (instead of PyPI), simply omit PyPI from your sources:

```toml
[[source]]
url = "https://custom-index.example.com/simple"
verify_ssl = true
name = "custom"
```

```{warning}
When omitting PyPI, your alternative index must contain all the packages you need, including all dependencies. If a package or dependency is not available on your custom index, installation will fail.
```

## Working with Private Repositories

### Basic Authentication

For private repositories that require authentication, you can include credentials in the URL:

```toml
[[source]]
url = "https://username:password@private-repo.example.com/simple"
verify_ssl = true
name = "private"
```

However, it's better to use environment variables for credentials:

```toml
[[source]]
url = "https://${USERNAME}:${PASSWORD}@private-repo.example.com/simple"
verify_ssl = true
name = "private"
```

Set the environment variables before running Pipenv:

```bash
$ export USERNAME=myuser
$ export PASSWORD=mypassword
$ pipenv install
```

### Token Authentication

For repositories that use token authentication:

```toml
[[source]]
url = "https://${API_TOKEN}@private-repo.example.com/simple"
verify_ssl = true
name = "private"
```

### Self-Signed Certificates

If your private repository uses a self-signed SSL certificate, you have two options:

1. Add the certificate to your system's trusted certificates (recommended)
2. Disable SSL verification (use with caution):

```toml
[[source]]
url = "https://private-repo.example.com/simple"
verify_ssl = false
name = "private"
```

```{warning}
Disabling SSL verification is a security risk and should only be done in controlled environments where you trust the network and the repository.
```

## Multi-Source Installation

### The `install_search_all_sources` Option

In some organizations, not everyone has access to all package sources. For these cases, Pipenv provides an option to search all configured sources when installing from a lock file:

```toml
[pipenv]
install_search_all_sources = true
```

With this option enabled, `pipenv install` and `pipenv sync` will search all configured sources for packages, but only during installation. The lock file will still require each package to be resolved from a single index.

```{note}
This feature should be used with caution, as it bypasses some of the security benefits of index-restricted packages. Only use it when necessary and in trusted environments.
```

## Advanced Index Configuration

### Specifying Index in Pipfile

You can specify which packages come from which index directly in your `Pipfile`:

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://private-repo.example.com/simple"
verify_ssl = true
name = "private"

[packages]
requests = "*"  # From PyPI
private-package = {version = "*", index = "private"}  # From private repo
```

### Using Multiple Private Repositories

You can use multiple private repositories in the same project:

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://repo1.example.com/simple"
verify_ssl = true
name = "repo1"

[[source]]
url = "https://repo2.example.com/simple"
verify_ssl = true
name = "repo2"

[packages]
requests = "*"  # From PyPI
package1 = {version = "*", index = "repo1"}  # From repo1
package2 = {version = "*", index = "repo2"}  # From repo2
```

## Troubleshooting

### Package Not Found

If a package can't be found:

1. Verify the package name is correct
2. Check that the package exists on the specified index
3. Ensure you have proper authentication for private repositories
4. Try installing with verbose output for more information:
   ```bash
   $ pipenv install package-name --verbose
   ```

### Authentication Issues

If you're having authentication problems:

1. Check that your credentials are correct
2. Ensure environment variables are properly set
3. Verify that your credentials have access to the repository
4. Check for special characters in your credentials that might need URL encoding

### SSL Certificate Issues

If you encounter SSL certificate errors:

1. Update your CA certificates
2. Verify the repository's SSL certificate is valid
3. If using a self-signed certificate, add it to your trusted certificates
4. Only as a last resort, consider disabling SSL verification

## Best Practices

1. **Use index restrictions** for all packages to prevent dependency confusion attacks

2. **Use environment variables for credentials** instead of hardcoding them in your `Pipfile`

3. **Always enable SSL verification** when possible

4. **Specify explicit versions** for packages from private repositories to ensure reproducibility

5. **Consider using a private PyPI mirror** that includes both public and private packages

6. **Regularly audit your dependencies** and their sources for security vulnerabilities

7. **Document your custom indexes** in your project's README or documentation

## Conclusion

Properly configuring package indexes in Pipenv is essential for security and reproducibility. By understanding how to work with multiple indexes and private repositories, you can safely manage dependencies while protecting your project from supply chain attacks.
