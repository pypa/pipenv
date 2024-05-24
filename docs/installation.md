# Pipenv Installation

```{note}
This guide is written for Python 3.7+
```


## Make sure you have python and pip

Before you go any further, make sure you have Python and that it's available
from your command line. You can check this by simply running

    $ python --version

You should get some output like `3.12.1`. If you do not have Python, please
install the latest 3.x version from [python.org](https://python.org)

Additionally, make sure you have [pip] available, assuming you install via pip, our preferred method of installation.
Check this by running

    $ pip --version
    pip 24.0

If you installed Python from source, with an installer from [python.org] or via [Homebrew], you likely already have pip.
If you're on Linux and installed using your OS package manager, you may have to [install pip](https://pip.pypa.io/en/stable/installing/) manually.

[python.org]: https://python.org
[pypi.org]: https://pypi.org
[pip]: https://pypi.org/project/pip/
[Homebrew]: https://brew.sh/


## Installing Pipenv


### Preferred Installation of Pipenv

It is recommended that users on most platforms install pipenv from [pypi.org] using

    $ pip install pipenv --user

```{note}
pip [user installations] allow for installation into your home directory to prevent breaking any system-wide packages.
Due to interaction between dependencies, you should limit tools installed in this way to basic building blocks for a Python workflow such as virtualenv, pipenv, tox, and similar software.
```


If `pipenv` isn't available in your shell after installation,
you'll need to add the user site-packages binary directory to your `PATH`.

On Linux and macOS you can find the [user base] binary directory by running
`python -m site --user-base` and appending `bin` to the end. For example,
this will typically print `~/.local` (with `~` expanded to the
absolute path to your home directory), so you'll need to add
`~/.local/bin` to your `PATH`. You can set your `PATH` permanently by
[modifying ~/.profile].

On Windows you can find the user base binary directory by running
`python -m site --user-site` and replacing `site-packages` with
`Scripts`. For example, this could return
`C:\Users\Username\AppData\Roaming\Python37\site-packages`, so you would
need to set your `PATH` to include
`C:\Users\Username\AppData\Roaming\Python37\Scripts`. You can set your
user `PATH` permanently in the [Control Panel](https://learn.microsoft.com/en-us/windows/win32/shell/user-environment-variables).

You may need to log out for the `PATH` changes to take effect.

[user base]: https://docs.python.org/3/library/site.html#site.USER_BASE
[user installations]: https://pip.pypa.io/en/stable/user_guide/#user-installs
[modifying ~/.profile]: https://stackoverflow.com/a/14638025
[Control Panel]: https://learn.microsoft.com/en-us/windows/win32/shell/user-environment-variables

To upgrade pipenv at any time:

    $ pip install --user --upgrade pipenv

### Homebrew Installation of Pipenv
* [Homebrew] is a popular open-source package management system for macOS (or Linux).

Once you have installed Homebrew simply run

    $ brew install pipenv

To upgrade pipenv at any time:

    $ brew upgrade pipenv

```{note}
Homebrew installation is discouraged because it works better to install pipenv using pip on macOS.
```

## Installing packages for your project

Pipenv manages dependencies on a per-project basis. To install a package,
change into your project's directory (or just an empty directory for this
tutorial) and run

    $ cd myproject
    $ pipenv install <package>

```{note}
Pipenv is designed to be used by non-privileged OS users. It is not meant
to install or handle packages for the whole OS. Running Pipenv as `root`
or with `sudo` (or `Admin` on Windows) is highly discouraged and might
lead to unintend breakage of your OS.
```

Pipenv will install the package and create a `Pipfile`
for you in your project's directory. The `Pipfile` is used to track which
dependencies your project needs in case you need to re-install them, such as
when you share your project with others.

For example when installing the `requests` library, you should get output similar to this:

    $ pipenv install requests
    Creating a virtualenv for this project...
    Pipfile: /home/matteius/pipenv-triage/test_install2/Pipfile
    Using default python from /mnt/extra/miniconda3/bin/python (3.12.1) to create virtualenv...
    ⠹ Creating virtual environment...created virtual environment CPython3.12.1.final.0-64 in 139ms
      creator CPython3Posix(dest=/home/matteius/Envs/test_install2-DMnDbAT9, clear=False, no_vcs_ignore=False, global=False)
      seeder FromAppData(download=False, pip=bundle, via=copy, app_data_dir=/home/matteius/.local/share/virtualenv)
        added seed packages: pip==24.0
      activators BashActivator,CShellActivator,FishActivator,NushellActivator,PowerShellActivator,PythonActivator

    ✔ Successfully created virtual environment!
    Virtualenv location: /home/matteius/Envs/test_install2-DMnDbAT9
    Creating a Pipfile for this project...
    Installing requests...
    Resolving requests...
    Added requests to Pipfile's [packages] ...
    ✔ Installation Succeeded
    Pipfile.lock not found, creating...
    Locking [packages] dependencies...
    Building requirements...
    Resolving dependencies...
    ✔ Success!
    Locking [dev-packages] dependencies...
    Updated Pipfile.lock (1977acb1ba9778abb66054090e2618a0a1f1759b1b3b32afd8a7d404ba18b4fb)!
    To activate this project's virtualenv, run pipenv shell.
    Alternatively, run a command inside the virtualenv with pipenv run.
    Installing dependencies from Pipfile.lock (18b4fb)...


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
- If you must move or rename a directory managed by pipenv, run 'pipenv --rm' before renaming or moving your project directory. Then, after renaming or moving the directory run 'pipenv install' to recreate the virtualenv.
- Customize this behavior with `PIPENV_CUSTOM_VENV_NAME` environment variable.
- You might also prefer to set `PIPENV_VENV_IN_PROJECT=1` in your .env or .bashrc/.zshrc (or other shell configuration file) for creating the virtualenv inside your project's directory.
