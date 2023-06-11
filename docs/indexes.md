# Specifying Package Indexes

The default python package index that is standard for use is [pypi.org](https://pypi.org).
Sometimes there is a need to work with alternative or additional package indexes.

## Index Restricted Packages

Starting in release `2022.3.23` all packages are mapped only to a single package index for security reasons.
All unspecified packages are resolved using the default index source; the default package index is PyPI.

For a specific package to be installed from an alternate package index, you must match the name of the index as in the following example:

    [[source]]
    url = "https://pypi.org/simple"
    verify_ssl = true
    name = "pypi"

    [[source]]
    url = "https://download.pytorch.org/whl/cu113/"
    verify_ssl = false
    name = "pytorch"

    [dev-packages]

    [packages]
    torch = {version="*", index="pytorch"}
    numpy = {version="*"}

You may install a package such as the example `torch` from the named index `pytorch` using the CLI by running
the following command:

`pipenv install torch --index=pytorch`

Alternatively the index may be specified by full url, and it will be added to the `Pipfile` with a generated name
unless it already exists in which case the existing name with be reused when pinning the package index.

```{note}
In prior versions of `pipenv` you could specify `--extra-index-urls` to the `pip` resolver and avoid specifically matching the expected index by name.
That functionality was deprecated in favor of index restricted packages, which is a simplifying assumption that is more security mindful.
The pip documentation has the following warning around the `--extra-index-urls` option:

> Using this option to search for packages which are not in the main repository (such as private packages) is unsafe,
> per a security vulnerability called dependency confusion: an attacker can claim the package on the public repository
> in a way that will ensure it gets chosen over the private package.
```

Should you wish to use an alternative default index other than PyPI: simply do not specify PyPI as one of the
sources in your `Pipfile`.  When PyPI is omitted, then any public packages required either directly or
as sub-dependencies must be mirrored onto your private index or they will not resolve properly.  This matches the
standard recommendation of `pip` maintainers: "To correctly make a private project installable is to point
--index-url to an index that contains both PyPI and their private projects—which is our recommended best practice."

The above documentation holds true for both `lock` resolution and `sync` of packages. It was suggested that
once the resolution and the lock file are updated, it is theoretically possible to safely scan multiple indexes
for these packages when running `pipenv sync` or `pipenv install --deploy` since it will verify the package
hashes match the allowed hashes that were already captured from a safe locking cycle.
To enable this non-default behavior, add `install_search_all_sources = true` option
to your `Pipfile` in the  `pipenv` section::

    [pipenv]
    install_search_all_sources = true

**Note:** The locking cycle will still require that each package be resolved from a single index.  This feature was
requested as a workaround in order to support organizations where not everyone has access to the package sources.

## Using a PyPI Mirror

Should you have access to a mirror of PyPI packages and wish to substitute the default pypi.org index URL with your PyPI mirror,
you may supply the `--pypi-mirror <mirror_url>` argument to select commands:

    $ pipenv install --pypi-mirror <mirror_url>

    $ pipenv update --pypi-mirror <mirror_url>

    $ pipenv sync --pypi-mirror <mirror_url>

    $ pipenv lock --pypi-mirror <mirror_url>

    $ pipenv uninstall --pypi-mirror <mirror_url>

Note that setting the `PIPENV_PYPI_MIRROR` environment variable is equivalent to passing `--pypi-mirror <mirror_url>`.
