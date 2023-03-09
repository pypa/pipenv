# Pipenv Installation

Note: This guide is written for Python 3.7+


## Make sure you have python

Before you go any further, make sure you have Python and that it's available
from your command line. You can check this by simply running:

    $ python --version

You should get some output like `3.10.8`. If you do not have Python, please
install the latest 3.x version from [python.org](https://python.org)

Additionally, you will want to make sure you have pip available.
Check this by running:

    $ pip --version
    pip 22.3.1

If you installed Python from source, with an installer from [python.org], via `Homebrew`_ you likely already have pip.
If you're on Linux and installed using your OS package manager, you may have to [install pip](https://pip.pypa.io/en/stable/installing/) manually.

* [python.org](https://python.org)
* [Installing Python](https://wiki.python.org/moin/BeginnersGuide/Download)
* [pip](https://pypi.org/project/pip/)



## Installing Pipenv

It is recommended that users on most platforms should install pipenv from pypi.org using `pip install pipenv --user`.


### Preferred Installation of Pipenv

If you have a working installation of pip, and maintain certain "tool-chain" type Python modules as global utilities in your user environment, pip `user installs <https://pip.pypa.io/en/stable/user_guide/#user-installs>`_ allow for installation into your home directory. Note that due to interaction between dependencies, you should limit tools installed in this way to basic building blocks for a Python workflow like virtualenv, pipenv, tox, and similar software.

To install:

    $ pip install pipenv --user

```{note}
    This does a `user installation`_ to prevent breaking any system-wide
    packages. If `pipenv` isn't available in your shell after installation,
    you'll need to add the user site-packages binary directory to your `PATH`.

    On Linux and macOS you can find the user base binary directory by running
    `python -m site --user-base` and adding `bin` to the end. For example,
    this will typically print `~/.local` (with `~` expanded to the
    absolute path to your home directory) so you'll need to add
    `~/.local/bin` to your `PATH`. You can set your `PATH` permanently by
    `modifying ~/.profile`_.

    On Windows you can find the user base binary directory by running
    `python -m site --user-site` and replacing `site-packages` with
    `Scripts`. For example, this could return
    `C:\Users\Username\AppData\Roaming\Python37\site-packages` so you would
    need to set your `PATH` to include
    `C:\Users\Username\AppData\Roaming\Python37\Scripts`. You can set your
    user `PATH` permanently in the `Control Panel`_. You may need to log
    out for the `PATH` changes to take effect.

    For more information, see the `user installs documentation <https://pip.pypa.io/en/stable/user_guide/#user-installs>`_.
```

.. _user base: https://docs.python.org/3/library/site.html#site.USER_BASE
.. _user installation: https://pip.pypa.io/en/stable/user_guide/#user-installs
.. _modifying ~/.profile: https://stackoverflow.com/a/14638025


To upgrade pipenv at any time:

    $ pip install --user --upgrade pipenv



### Homebrew Installation of Pipenv
* [Homebrew](https://brew.sh) is a popular open-source package management system for macOS. For Linux users, `Linuxbrew`_  is a Linux port of that.

Once you have installed Homebrew or Linuxbrew simply run:

    $ brew install pipenv

To upgrade pipenv at any time:

    $ brew upgrade pipenv

```{note}
Homebrew installation is discouraged because it works better to install pipenv using pip on macOS
```

### Installing packages for your project

Pipenv manages dependencies on a per-project basis. To install packages,
change into your project's directory (or just an empty directory for this
tutorial) and run:

    $ cd myproject
    $ pipenv install requests

```{note}
   Pipenv is designed to be used by non-privileged OS users. It is not meant
   to install or handle packages for the whole OS. Running Pipenv as `root`
   or with `sudo` (or `Admin` on Windows) is highly discouraged and might
   lead to unintend breakage of your OS.
```

Pipenv will install the `requests` library and create a `Pipfile`
for you in your project's directory. The `Pipfile` is used to track which
dependencies your project needs in case you need to re-install them, such as
when you share your project with others.

You should get output similar to this:

    Creating a virtualenv for this project...
    Pipfile: C:\Users\matte\Projects\pipenv-triage\example\Pipfile
    Using C:/Users/matte/AppData/Local/Programs/Python/Python311/python.exe (3.11.2) to create virtualenv...
    [    ] Creating virtual environment...created virtual environment CPython3.11.2.final.0-64 in 488ms
      creator CPython3Windows(dest=C:\Users\matte\.virtualenvs\example-7V6BFyzL, clear=False, no_vcs_ignore=False, global=False)
      seeder FromAppData(download=False, pip=bundle, setuptools=bundle, wheel=bundle, via=copy, app_data_dir=C:\Users\matte\AppData\Local\pypa\virtualenv)
        added seed packages: pip==23.0, setuptools==67.1.0, wheel==0.38.4
      activators BashActivator,BatchActivator,FishActivator,NushellActivator,PowerShellActivator,PythonActivator

    Successfully created virtual environment!
    Virtualenv location: C:\Users\matte\.virtualenvs\example-7V6BFyzL
    Installing requests...
    Resolving requests...
    Installing...
    Adding requests to Pipfile's [packages] ...
    Installation Succeeded
    Installing dependencies from Pipfile.lock (3b5a71)...
    To activate this project's virtualenv, run pipenv shell.
    Alternatively, run a command inside the virtualenv with pipenv run.

## Using installed packages

Now that `requests` is installed you can create a simple `main.py` file to use it:

```
import requests

response = requests.get('https://httpbin.org/ip')
print('Your IP is {0}'.format(response.json()['origin']))
```
Then you can run this script using `pipenv run`

    $ pipenv run python main.py

You should get output similar to this:

    Your IP is 8.8.8.8

Using `$ pipenv run` ensures that your installed packages are available to
your script by activating the virtualenv. It is also possible to spawn a new shell
that ensures all commands have access to your installed packages with `$ pipenv shell`.


## Virtualenv mapping caveat

- Pipenv automatically maps projects to their specific virtualenvs.
- By default, the virtualenv is stored globally with the name of the project’s root directory plus the hash of the full path to the project's root (e.g., `my_project-a3de50`).
- Should you change your project's path, you break such a default mapping and pipenv will no longer be able to find and to use the project's virtualenv.
- Customize this behavior with `PIPENV_CUSTOM_VENV_NAME` environment variable.
- You might also prefer to set `PIPENV_VENV_IN_PROJECT=1` in your .env or .bashrc/.zshrc (or other shell configuration file) for creating the virtualenv inside your project's directory.
