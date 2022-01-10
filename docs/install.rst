.. _virtualenvironments-ref:

=============================
Pipenv & Virtual Environments
=============================

.. image:: https://farm3.staticflickr.com/2943/33485660921_dfc0494739_k_d.jpg

This tutorial walks you through installing and using Python packages.

It will show you how to install and use the necessary tools and make strong
recommendations on best practices. Keep in mind that Python is used for a great
many different purposes, and precisely how you want to manage your dependencies
may change based on how you decide to publish your software. The guidance
presented here is most directly applicable to the development and deployment of
network services (including web applications), but is also very well suited to
managing development and testing environments for any kind of project.

.. Note:: This guide is written for Python 3, however, these instructions
    should work fine on Python 2.7—if you are still using it, for some reason.


☤ Make sure you've got Python & pip
===================================

Before you go any further, make sure you have Python and that it's available
from your command line. You can check this by simply running::

    $ python --version

You should get some output like ``3.6.2``. If you do not have Python, please
install the latest 3.x version from `python.org`_ or refer to the
`Installing Python`_ section of *The Hitchhiker's Guide to Python*.

.. Note:: If you're newcomer and you get an error like this:

    .. code-block:: pycon

        >>> python
        Traceback (most recent call last):
          File "<stdin>", line 1, in <module>
        NameError: name 'python' is not defined

    It's because this command is intended to be run in a *shell* (also called
    a *terminal* or *console*). See the Python for Beginners
    `getting started tutorial`_ for an introduction to using your operating
    system's shell and interacting with Python.

Additionally, you'll need to make sure you have pip available. You can
check this by running::

    $ pip --version
    pip 9.0.1

If you installed Python from source, with an installer from `python.org`_, via `Homebrew`_ or via `Linuxbrew`_ you should already have pip. If you're on Linux and installed
using your OS package manager, you may have to `install pip <https://pip.pypa.io/en/stable/installing/>`_ separately.

If you plan to install Pipenv using Homebrew or Linuxbrew you can skip this step. The
Homebrew/Linuxbrew installer takes care of pip for you.

.. _getting started tutorial: https://opentechschool.github.io/python-beginners/en/getting_started.html#what-is-python-exactly
.. _python.org: https://python.org
.. _Homebrew: https://brew.sh
.. _Linuxbrew: https://linuxbrew.sh/
.. _Installing Python: http://docs.python-guide.org/en/latest/starting/installation/


.. _installing-pipenv:

☤ Installing Pipenv
===================

Pipenv is a dependency manager for Python projects. If you're familiar
with Node\.js's `npm`_ or Ruby's `bundler`_, it is similar in spirit to those
tools. While pip can install Python packages, Pipenv is recommended as
it's a higher-level tool that simplifies dependency management for common use
cases.

.. _npm: https://www.npmjs.com/
.. _bundler: http://bundler.io/


☤ Isolated Installation of Pipenv with Pipx
-------------------------------------------

`Pipx`_ is a tool to help you install and run end-user applications written in Python. It installs applications
into an isolated and clean environment on their own. To install pipx, just run::

    $ pip install --user pipx

Once you have ``pipx`` ready on your system, continue to install Pipenv::

    $ pipx install pipenv

.. _Pipx: https://pypa.github.io/pipx/


☤ Pragmatic Installation of Pipenv
----------------------------------

If you have a working installation of pip, and maintain certain "tool-chain" type Python modules as global utilities in your user environment, pip `user installs <https://pip.pypa.io/en/stable/user_guide/#user-installs>`_ allow for installation into your home directory. Note that due to interaction between dependencies, you should limit tools installed in this way to basic building blocks for a Python workflow like virtualenv, pipenv, tox, and similar software.

To install::

    $ pip install --user pipenv

.. Note:: This does a `user installation`_ to prevent breaking any system-wide
    packages. If ``pipenv`` isn't available in your shell after installation,
    you'll need to add the `user base`_'s binary directory to your ``PATH``.

    On Linux and macOS you can find the user base binary directory by running
    ``python -m site --user-base`` and adding ``bin`` to the end. For example,
    this will typically print ``~/.local`` (with ``~`` expanded to the
    absolute path to your home directory) so you'll need to add
    ``~/.local/bin`` to your ``PATH``. You can set your ``PATH`` permanently by
    `modifying ~/.profile`_.

    On Windows you can find the user base binary directory by running
    ``python -m site --user-site`` and replacing ``site-packages`` with
    ``Scripts``. For example, this could return
    ``C:\Users\Username\AppData\Roaming\Python36\site-packages`` so you would
    need to set your ``PATH`` to include
    ``C:\Users\Username\AppData\Roaming\Python36\Scripts``. You can set your
    user ``PATH`` permanently in the `Control Panel`_. You may need to log
    out for the ``PATH`` changes to take effect.

    For more information, see the `user installs documentation <https://pip.pypa.io/en/stable/user_guide/#user-installs>`_.


.. _user base: https://docs.python.org/3/library/site.html#site.USER_BASE
.. _user installation: https://pip.pypa.io/en/stable/user_guide/#user-installs
.. _modifying ~/.profile: https://stackoverflow.com/a/14638025
.. _Control Panel: https://msdn.microsoft.com/en-us/library/windows/desktop/bb776899(v=vs.85).aspx


To upgrade pipenv at any time::

    $ pip install --user --upgrade pipenv


☤ Crude Installation of Pipenv
------------------------------

If you don't even have pip installed, you can use this crude installation method, which will bootstrap your whole system::

    $ curl https://raw.githubusercontent.com/pypa/pipenv/master/get-pipenv.py | python


☤ Homebrew Installation of Pipenv(Discouraged)
----------------------------------------------
`Homebrew`_ is a popular open-source package management system for macOS. For Linux users, `Linuxbrew`_  is a Linux port of that.

Installing pipenv via Homebrew or Linuxbrew will keep pipenv and all of its dependencies in
an isolated virtual environment so it doesn't interfere with the rest of your
Python installation.

Once you have installed Homebrew or Linuxbrew simply run::

    $ brew install pipenv

To upgrade pipenv at any time::

    $ brew upgrade pipenv

.. Note::
    Homebrew installation is discouraged because each time the Homebrew Python is upgraded, which Pipenv depends on,
    users have to re-install Pipenv, and perhaps all virtual environments managed by it.


☤ Installing packages for your project
======================================

Pipenv manages dependencies on a per-project basis. To install packages,
change into your project's directory (or just an empty directory for this
tutorial) and run::

    $ cd myproject
    $ pipenv install requests

.. Note::

   Pipenv is designed to be used by non-privileged OS users. It is not meant
   to install or handle packages for the whole OS. Running Pipenv as ``root``
   or with ``sudo`` (or ``Admin`` on Windows) is highly discouraged and might
   lead to unintend breakage of your OS.

Pipenv will install the excellent `Requests`_ library and create a ``Pipfile``
for you in your project's directory. The ``Pipfile`` is used to track which
dependencies your project needs in case you need to re-install them, such as
when you share your project with others. You should get output similar to this
(although the exact paths shown will vary)::

     pipenv install requests
     Creating a virtualenv for this project...
     Pipfile: /home/user/myproject/Pipfile
     sing /home/user/.local/share/virtualenvs/pipenv-Cv0J3wbi/bin/python3.9 (3.9.9) to create virtualenv...
      Creating virtual environment...created virtual environment CPython3.9.9.final.0-64 in 1142ms
      creator CPython3Posix(dest=/home/user/.local/share/virtualenvs/myproject-R3jRVewK, clear=False, no_vcs_ignore=False, global=False)
      seeder FromAppData(download=False, pip=bundle, setuptools=bundle, wheel=bundle, via=copy, app_data_dir=/home/user/.local/share/virtualenv)
        added seed packages: pip==21.3.1, setuptools==60.2.0, wheel==0.37.1
      activators BashActivator,CShellActivator,FishActivator,NushellActivator,PowerShellActivator,PythonActivator

     ✔ Successfully created virtual environment!
     Virtualenv location: /home/user/.local/share/virtualenvs/pms-R3jRVewK
     Creating a Pipfile for this project...
     Installing requests...
     Adding requests to Pipfile's [packages]...
     Installation Succeeded
     Pipfile.lock not found, creating...
     Locking [dev-packages] dependencies...
     Locking [packages] dependencies...
     Building requirements...
     Resolving dependencies...
     ✔ Success!
     Updated Pipfile.lock (fe5a22)!
     Installing dependencies from Pipfile.lock (fe5a22)...
     🐍   ▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉ 0/0 — 00:00:00

.. _Requests: https://python-requests.org


☤ Using installed packages
==========================

Now that Requests is installed you can create a simple ``main.py`` file to
use it:

.. code-block:: python

    import requests

    response = requests.get('https://httpbin.org/ip')

    print('Your IP is {0}'.format(response.json()['origin']))

Then you can run this script using ``pipenv run``::

    $ pipenv run python main.py

You should get output similar to this:

.. code-block:: text

    Your IP is 8.8.8.8

Using ``$ pipenv run`` ensures that your installed packages are available to
your script. It's also possible to spawn a new shell that ensures all commands
have access to your installed packages with ``$ pipenv shell``.


☤ Virtualenv mapping caveat
===========================

- Pipenv automatically maps projects to their specific virtualenvs.
- The virtualenv is stored globally with the name of the project’s root directory plus the hash of the full path to the project's root (e.g., ``my_project-a3de50``).
- If you change your project's path, you break such a default mapping and pipenv will no longer be able to find and to use the project's virtualenv.
- You might want to set ``export PIPENV_VENV_IN_PROJECT=1`` in your .bashrc/.zshrc (or any shell configuration file) for creating the virtualenv inside your project's directory, avoiding problems with subsequent path changes.


☤ Next steps
============

Congratulations, you now know how to install and use Python packages! ✨ 🍰 ✨
