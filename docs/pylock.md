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
dependency-groups = []
default-groups = []
created-by = 'pipenv'

[[packages]]
name = 'requests'
version = '2.28.1'
requires-python = '>=3.7'

[[packages.wheels]]
name = 'requests-2.28.1-py3-none-any.whl'
upload-time = '2022-07-13T14:00:00Z'
url = 'https://files.pythonhosted.org/packages/ca/91/6d9b8ccacd0412c08820f72cebaa4f0c61441f4AE7b7338a82051330d70/requests-2.28.1-py3-none-any.whl'
size = 61805
hashes = {sha256 = 'b8aa58f8cf793ffd8782d3d8cb19e66ef36f7aba4353eec859e74678b01b07a7'}
```

## Benefits of Using pylock.toml

- **Standardization**: pylock.toml is a standardized format that can be used by multiple Python packaging tools.
- **Security**: pylock.toml includes file hashes by default, making it more secure against supply chain attacks.
- **Flexibility**: pylock.toml can support both single-use and multi-use lock files, allowing for more complex dependency scenarios.
- **Interoperability**: pylock.toml can be used by different tools, reducing vendor lock-in.

## Limitations

- Currently, Pipenv only supports reading pylock.toml files, not writing them.
- Some advanced features of pylock.toml, such as environment markers for extras and dependency groups, are not fully supported yet.

## Future Plans

In future releases, Pipenv plans to add support for:

- Writing pylock.toml files
- Full support for environment markers for extras and dependency groups
- Converting between Pipfile.lock and pylock.toml formats
