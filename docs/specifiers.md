# Specifiers


## Specifying Versions of a Package

You can specify versions of a package using the [Semantic Versioning scheme](https://semver.org/)
(i.e. `major.minor.micro`).

To install a major version of requests you can use:

    $ pipenv install requests~=1.1

Pipenv will install version `1.2` as it is a minor update, but not `2.0`.

To install a minor version of requests you can use:

    $ pipenv install requests~=1.0.1

Pipenv will install version `1.0.4` as it is a micro version update, but not `1.1.0`.

This will update your `Pipfile` to reflect this requirement, automatically.

In general, Pipenv uses the same specifier format as pip. However, note that according to [PEP 440](https://www.python.org/dev/peps/pep-0440/),
you can't use versions containing a hyphen or a plus sign.

To make inclusive or exclusive version comparisons you can use:

    $ pipenv install "requests>=1.4"   # will install a version equal or larger than 1.4.0
    $ pipenv install "requests<=2.13"  # will install a version equal or lower than 2.13.0
    $ pipenv install "requests>2.19"   # will install 2.19.1 but not 2.19.0

```{note}
The use of double quotes around the package and version specification (i.e. `"requests>2.19"`) is highly recommended
to avoid issues with [Input and output redirection](https://robots.thoughtbot.com/input-output-redirection-in-the-shell)
in Unix-based operating systems.
```

The use of `~=` is preferred over the `==` identifier as the latter prevents pipenv from updating the packages:

    $ pipenv install "requests~=2.2"  # locks the major version of the package (this is equivalent to using >=2.2, ==2.*)

To avoid installing a specific version you can use the `!=` identifier.

For an in depth explanation of the valid identifiers and more complex use cases check
the [relevant section of PEP-440]( https://www.python.org/dev/peps/pep-0440/#version-specifiers).

## Specifying Versions of Python

To create a new virtualenv, using a specific version of Python you have installed (and
on your `PATH`), use the `--python VERSION` flag, like so:

Use Python 3

    $ pipenv --python 3

Use Python3.11

    $ pipenv --python 3.11


When given a Python version, like this, Pipenv will automatically scan your system for a Python that matches that given version.

If a `Pipfile` hasn't been created yet, one will be created for you, that looks like this:

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true
    name = "pypi"

    [dev-packages]

    [packages]

    [requires]
    python_version = "3.11"

```{note}
The inclusion of `[requires] python_version = "3.11"` specifies that your application requires this version
of Python, and will be used automatically when running `pipenv install` against this `Pipfile` in the future
(e.g. on other machines). If this is not true, feel free to simply remove this section.
```

If you don't specify a Python version on the command–line, either the `[requires]` `python_full_version` or `python_version` will be selected
automatically, falling back to whatever your system's default `python` installation is, at time of execution.


## Editable Dependencies ( -e . )

You can tell Pipenv to install a path as editable — often this is useful for
the current working directory when working on packages:

    $ pipenv install --dev -e .

    $ cat Pipfile
    ...
    [dev-packages]
    "e1839a8" = {path = ".", editable = true}
    ...
```{note}
All sub-dependencies will get added to the `Pipfile.lock` as well. Sub-dependencies are **not** added to the
`Pipfile.lock` if you leave the `-e` option out.
```

## VCS Dependencies

VCS dependencies from git and other version control systems using URLs formatted using preferred pip line formats:

    <vcs_type>+<scheme>://<location>/<user_or_organization>/<repository>@<branch_or_tag>

Extras may be specified using the following format when issuing install command:

    <package_name><possible_extras>@ <vcs_type>+<scheme>://<location>/<user_or_organization>/<repository>@<branch_or_tag>

Note: that the #egg fragments should only be used for legacy pip lines which are still required in editable requirements.

    $ pipenv install -e git+https://github.com/requests/requests.git@v2.31.0#egg=requests


Below is an example usage which installs the git repository located at `https://github.com/requests/requests.git` from tag `v2.20.1` as package name `requests`:

    $ pipenv install -e git+https://github.com/requests/requests.git@v2.20.1#egg=requests
    Installing -e git+https://github.com/requests/requests.git@v2.20.1#egg=requests...
    Resolving -e git+https://github.com/requests/requests.git@v2.20.1#egg=requests...
    Added requests to Pipfile's [packages] ...
    Installation Succeeded
    Pipfile.lock not found, creating...
    Locking [packages] dependencies...
    Building requirements...
    Resolving dependencies...
    Success!
    Locking [dev-packages] dependencies...
    Updated Pipfile.lock (389441cc656bb774aaa28c7e53a35137aace7499ca01668765d528fa79f8acc8)!
    Installing dependencies from Pipfile.lock (f8acc8)...
    To activate this project's virtualenv, run pipenv shell.
    Alternatively, run a command inside the virtualenv with pipenv run.

    $ cat Pipfile
    [packages]
    requests = {editable = true, ref = "v2.20.1", git = "git+https://github.com/requests/requests.git"}

    $ cat Pipfile.lock
    ...
    "requests": {
        "editable": true,
        "git": "git+https://github.com/requests/requests.git",
        "markers": "python_version >= '3.7'",
        "ref": "6cfbe1aedd56f8c2f9ff8b968efe65b22669795b"
    },
    ...

Valid values for `<vcs_type>` include `git`, `bzr`, `svn`, and `hg`.  Valid values for `<scheme>` include `http`, `https`, `ssh`, and `file`.  In specific cases you also have access to other schemes: `svn` may be combined with `svn` as a scheme, and `bzr` can be combined with `sftp` and `lp`.

You can read more about pip's implementation of VCS support `here <https://pip.pypa.io/en/stable/reference/pip_install/#vcs-support>`__.


## Specifying Package Categories

Originally pipenv supported only two package groups:  `packages` and `dev-packages` in the `Pipfile` which mapped to `default` and `develop` in the `Pipfile.lock`.   Support for additional named categories has been added such that arbitrary named groups can utilized across the available pipenv commands.

```{note}
The name will be the same between `Pipfile` and lock file, however to support the legacy naming convention it is not possible to have an additional group named `default` or `develop` in the `Pipfile`.
```

By default `pipenv lock` will lock all known package categorises; to specify locking only specific groups use the `--categories` argument.
The command should process the package groups in the order specified.

Example usages:

	# single category
	pipenv install six --categories prereq

	# multiple categories
	pipenv sync --categories="prereq packages"

	# lock and uninstall examples
	pipenv lock --categories="prereq dev-packages"
	pipenv uninstall six --categories prereq


```{note}
The `packages`/`default` specifiers are used to constrain all other categories just as they have done
for `dev-packages`/`develop` category.  However this is the only way constraints are applied --
the presence of other named groups do not constraint each other,
which means it is possible to define conflicting package versions across groups.
This may be desired in some use cases where users only are installing groups specific to their system platform.
```

## Specifying Basically Anything

If you'd like to specify that a specific package only be installed on certain systems,
you can use [PEP 508 specifiers](https://www.python.org/dev/peps/pep-0508/) to accomplish this.

Here's an example `Pipfile`, which will only install `pywinusb` on Windows systems::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true
    name = "pypi"

    [packages]
    requests = "*"
    pywinusb = {version = "*", sys_platform = "== 'win32'"}

Here's a more complex example::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true

    [packages]
    unittest2 = {version = ">=1.0,<3.0", markers="python_version < '2.7.9' or (python_version >= '3.0' and python_version < '3.4')"}

Markers provide a ton of flexibility when specifying package requirements.
