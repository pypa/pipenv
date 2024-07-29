# Other topics

This document is current in the process of being broken apart into more granular sections so that we may provide better overall documentation.

## ☤ Supplying additional arguments to pip

There may be cases where you wish to supply additional arguments to pip to be used during the install phase. For example, you may want to enable the pip feature for using [system certificate stores](https://pip.pypa.io/en/latest/topics/https-certificates/#using-system-certificate-stores)

In this case you can supply these additional arguments to `pipenv sync` or `pipenv install` by passing additional
argument `--extra-pip-args="--use-feature=truststore"`. It is possible to supply multiple arguments in the `--extra-pip-args`. Example usage:

    pipenv sync --extra-pip-args="--use-feature=truststore --proxy=127.0.0.1"

## ☤ Using pipenv for Deployments

You may want to use `pipenv` as part of a deployment process.

You can enforce that your `Pipfile.lock` is in parity with your `Pipfile` by using the `--deploy` flag:

    $ pipenv install --deploy

This will fail a build if the `Pipfile.lock` `_meta` `hash` is out of date from the Pipfile contents.

Or you can install packages exactly as specified in `Pipfile.lock` using the `install` or `sync` command:

    $ pipenv install

    or

    $ pipenv install

Note:  Legacy versions of pipenv (prior to pipenv 2024) would relock dependencies when running `pipenv install`.  This behavior was changed in pipenv 2024.0.0 to only relock dependencies when supply package specifiers to the `install` command.

    ``pipenv sync`` is nearly equivalent to ``pipenv install`` at this point, except pipenv install provides more functionality for adding and upgrading packages.

You may only wish to verify your `Pipfile.lock` is up-to-date with dependencies specified in the `Pipfile`, without installing:

    $ pipenv verify

The command will perform a verification, and return an exit code `1` when dependency locking is needed. This may be useful for cases when the `Pipfile.lock` file is subject to version control, so this command can be used within your CI/CD pipelines.

### Deploying System Dependencies

You can tell Pipenv to install a Pipfile's contents into its parent system with the `--system` flag:

    $ pipenv install --system

This is useful for managing the system Python, and deployment infrastructure (e.g. Heroku does this).

## ☤ Pipenv and Other Python Distributions

To use Pipenv with a third-party Python distribution (e.g. Anaconda), you simply provide the path to the Python binary:

    $ pipenv install --python=/path/to/python

Anaconda uses Conda to manage packages. To reuse Conda–installed Python packages, use the `--site-packages` flag:

    $ pipenv --python=/path/to/python --site-packages

## ☤ Generating a `requirements.txt`

Sometimes, you would want to generate a requirements file based on your current
environment, for example to include tooling that only supports requirements.txt.
You can convert a `Pipfile.lock` into a `requirements.txt`
file very easily.

Let's take this `Pipfile`:

    [[source]]
    name = "pypi"
    url = "https://pypi.org/simple"
    verify_ssl = true

    [packages]
    requests = {version="==2.18.4"}

    [dev-packages]
    pytest = {version="==3.2.3"}

Which generates a `Pipfile.lock` upon completion of running ``pipenv lock``` similar to:

    {
            "_meta": {
                    "hash": {
                            "sha256": "4b81df812babd4e54ba5a4086714d7d303c1c3f00d725c76e38dd58cbd360f4e"
                    },
                    "pipfile-spec": 6,
                    "requires": {},
                    "sources": [
                            {
                                    "name": "pypi",
                                    "url": "https://pypi.org/simple",
                                    "verify_ssl": true
                            }
                    ]
            },
            "default": {
    		... snipped ...
                    "requests": {
                            "hashes": [
                                    "sha256:6a1b267aa90cac58ac3a765d067950e7dbbf75b1da07e895d1f594193a40a38b",
                                    "sha256:9c443e7324ba5b85070c4a818ade28bfabedf16ea10206da1132edaa6dda237e"
                            ],
                            "index": "pypi",
                            "version": "==2.18.4"
                    },
    		... snipped ...
            },
            "develop": {
                    ... snipped ...
                    "pytest": {
                            "hashes": [
                                    "sha256:27fa6617efc2869d3e969a3e75ec060375bfb28831ade8b5cdd68da3a741dc3c",
                                    "sha256:81a25f36a97da3313e1125fce9e7bbbba565bc7fec3c5beb14c262ddab238ac1"
                            ],
                            "index": "pypi",
                            "version": "==3.2.3"
                    }
                    ... snipped ...
    }

Given the `Pipfile.lock` exists, you may generate a set of requirements out of it with the default dependencies:

    $ pipenv requirements
    -i https://pypi.org/simple
    certifi==2022.9.24 ; python_version >= '3.6'
    chardet==3.0.4
    idna==2.6
    requests==2.18.4
    urllib3==1.22

As with other commands, passing `--dev` will include both the default and
development dependencies:

     $ pipenv requirements --dev
    -i https://pypi.org/simple
    colorama==0.4.5 ; sys_platform == 'win32'
    py==1.11.0 ; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'
    pytest==3.2.3
    setuptools==65.4.1 ; python_version >= '3.7'
    certifi==2022.9.24 ; python_version >= '3.6'
    chardet==3.0.4
    idna==2.6
    requests==2.18.4
    urllib3==1.22

If you wish to generate a requirements file with only the development requirements you can do that too, using the `--dev-only` flag:

    $ pipenv requirements --dev-only
    -i https://pypi.org/simple
    colorama==0.4.5 ; sys_platform == 'win32'
    py==1.11.0 ; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'
    pytest==3.2.3
    setuptools==65.4.1 ; python_version >= '3.7'

Adding the `--hash` flag adds package hashes to the output for extra security.
Adding the `--exclude-markers` flag excludes the markers from the output.

The locked requirements are written to stdout, with shell output redirection
used to write them to a file:

    $ pipenv requirements > requirements.txt
    $ pipenv requirements --dev-only > dev-requirements.txt
    $ cat requirements.txt
    -i https://pypi.org/simple
    certifi==2022.9.24 ; python_version >= '3.6'
    chardet==3.0.4
    idna==2.6
    requests==2.18.4
    urllib3==1.22
    $ cat dev-requirements.txt
    -i https://pypi.org/simple
    colorama==0.4.5 ; sys_platform == 'win32'
    py==1.11.0 ; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'
    pytest==3.2.3
    setuptools==65.4.1 ; python_version >= '3.7'

If you have multiple categories in your Pipfile and wish to generate
a requirements file for only some categories, you can do that too,
using the `--categories` option:

    $ pipenv requirements --categories="tests" > requirements-tests.txt
    $ pipenv requirements --categories="docs" > requirements-docs.txt
    $ cat requirements-tests.txt
    -i https://pypi.org/simple
    attrs==22.1.0 ; python_version >= '3.5'
    iniconfig==1.1.1
    packaging==21.3 ; python_version >= '3.6'
    pluggy==1.0.0 ; python_version >= '3.6'
    py==1.11.0 ; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'
    pyparsing==3.0.9 ; python_full_version >= '3.6.8'
    pytest==7.1.3
    tomli==2.0.1 ; python_version >= '3.7'

It can be used to specify multiple categories also.

    $ pipenv requirements --categories="tests,docs"

## ☤ Detection of Security Vulnerabilities

Pipenv includes the [safety](https://github.com/pyupio/safety) package, and will use it to scan your dependency graph for known security vulnerabilities!

By default `pipenv check` will scan the Pipfile.lock default packages group and use this as the input to the safety command.
To scan other package categories pass the specific `--categories` you want to check against.
To have `pipenv check` scan the virtualenv packages for what is installed and use this as the input to the safety command,
run`pipenv check --use-installed`.
Note: `--use-installed` was the default behavior in `pipenv<=2023.2.4`.

Example:

    $ pipenv install wheel==0.37.1
    $ cat Pipfile.lock
    ...
    "default": {
        "wheel": {
            "hashes": [
                "sha256:4bdcd7d840138086126cd09254dc6195fb4fc6f01c050a1d7236f2630db1d22a",
                "sha256:e9a504e793efbca1b8e0e9cb979a249cf4a0a7b5b8c9e8b65a5e39d49529c1c4"
            ],
            "index": "pypi",
            "version": "==0.37.1"
        }
    },
    ...

    $ pipenv check --use-lock
    ...
    -> Vulnerability found in wheel version 0.37.1
       Vulnerability ID: 51499
       Affected spec: <0.38.1
       ADVISORY: Wheel 0.38.1 includes a fix for CVE-2022-40898: An issue discovered in Python Packaging Authority (PyPA) Wheel 0.37.1 and earlier allows remote attackers to cause a denial of service
       via attacker controlled input to wheel cli.https://pyup.io/posts/pyup-discovers-redos-vulnerabilities-in-top-python-packages
       CVE-2022-40898
       For more information, please visit https://pyup.io/v/51499/742

     Scan was completed. 1 vulnerability was found.
     ...

Note

Each month, [PyUp.io](https://pyup.io) updates the `safety` database of insecure Python packages and [makes it available to the open source community for free](https://pyup.io/safety/). Each time you run `pipenv check` to show you vulnerable dependencies,
Pipenv makes an API call to retrieve and use those results.

For more up-to-date vulnerability data, you may also use your own safety API key by setting the environment variable `PIPENV_PYUP_API_KEY`.

## ☤ Community Integrations

There are a range of community-maintained plugins and extensions available for a range of editors and IDEs, as well as different products which integrate with Pipenv projects:

-   [Heroku](https://heroku.com/python) (Cloud Hosting)
-   [Platform.sh](https://platform.sh/hosting/python)(Cloud Hosting)
-   [PyUp](https://pyup.io) (Security Notification)
-   [Emacs](https://github.com/pwalsh/pipenv.el) (Editor Integration)
-   [Fish Shell](https://github.com/fisherman/pipenv) (Automatic `$ pipenv shell`!)
-   [VS Code](https://code.visualstudio.com/docs/python/environments) (Editor Integration)
-   [PyCharm](https://www.jetbrains.com/pycharm/download/) (Editor Integration)

## ☤ Open a Module in Your Editor

Pipenv allows you to open any Python module that is installed (including ones in your codebase), with the `$ pipenv open` command:

    $ pipenv install -e git+https://github.com/kennethreitz/background.git#egg=background
    Installing -e git+https://github.com/kennethreitz/background.git#egg=background...
    ...
    Updated Pipfile.lock!

    $ pipenv open background
    Opening '/Users/kennethreitz/.local/share/virtualenvs/hmm-mGOawwm_/src/background/background.py' in your EDITOR.

This allows you to easily read the code you're consuming, instead of looking it up on GitHub.

Note

The standard `EDITOR` environment variable is used for this. If you're using VS Code, for example, you'll want to `export EDITOR=code` (if you're on macOS you will want to [install the command](https://code.visualstudio.com/docs/setup/mac#_launching-from-the-command-line) on to your `PATH` first).

## ☤ Automatic Python Installation

This is a very fancy feature, and we're very proud of it:

    $ cat Pipfile
    [[source]]
    name = "pypi"
    url = "https://pypi.org/simple"
    verify_ssl = true

    [dev-packages]

    [packages]
    requests = "*"

    [requires]
    python_version = "3.11"

    $ pipenv install
    Warning: Python 3.11 was not found on your system...
    Would you like us to install latest CPython 3.11 with pyenv? [Y/n]: y
    Installing CPython 3.11.2 with pyenv (this may take a few minutes)...
    ...
    Making Python installation global...
    Creating a virtualenv for this project...
    Using /Users/kennethreitz/.pyenv/shims/python3 to create virtualenv...
    ...
    No package provided, installing all dependencies.
    ...
    Installing dependencies from Pipfile.lock...
    🐍   ❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒❒ 5/5 — 00:00:03
    To activate this project's virtualenv, run the following:
     $ pipenv shell

Pipenv automatically honors both the `python_full_version` and `python_version` [PEP 508](https://www.python.org/dev/peps/pep-0508/) specifiers.

💫✨🍰✨💫

## ☤ Testing Projects

Pipenv is being used in projects like [Requests](https://github.com/psf/requests) for declaring development dependencies and running the test suite.

### Tox Automation Project

Here's an example `tox.ini` for both local and external testing:

    [tox]
    envlist = py37, py38, py39, py310, py311, pypy3, ruff

    [testenv]
    deps = pipenv
    commands=
        pipenv install --dev
        pipenv run pytest tests

    [testenv:ruff]
    basepython = python3.11
    commands=
        pipenv install --dev
        pipenv run ruff --version
        pipenv run ruff .

Pipenv will automatically use the virtualenv provided by `tox`. If `pipenv install --dev` installs e.g. `pytest`, then installed command `pytest` will be present in given virtualenv and can be called directly by `pytest tests` instead of `pipenv run pytest tests`.
W
✨🍰✨

## ☤ Working with Platform-Provided Python Components

It's reasonably common for platform specific Python bindings for operating system interfaces to only be available through the system package manager, and hence unavailable for installation into virtual
environments with `pip`. In these cases, the virtual environment can be created with access to the system `site-packages` directory:

    $ pipenv --site-packages

To ensure that all `pip`-installable components actually are installed into the virtual environment and system packages are only used for interfaces that don't participate in Python-level dependency resolution
at all, use the `PIP_IGNORE_INSTALLED` setting:

    $ PIP_IGNORE_INSTALLED=1 pipenv install --dev
