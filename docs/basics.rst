.. _virtualenvironments-ref:

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


☤  Make sure you've got Python & pip
------------------------------------

Before you go any further, make sure you have Python and that it's avalable
from your command line. You can check this by simply running:

.. code-block:: bash

    $ python --version

You should get some output like ``3.6.2``. If you do not have Python, please
install the latest 3.x version from `python.org`_ or refer to the
`Installing Python`_ section of *The Hitchhiker's Guide to Python*.

.. Note:: If you're newcomer and you get an error like this:

    .. code-block:: python

        >>> python
        Traceback (most recent call last):
          File "<stdin>", line 1, in <module>
        NameError: name 'python' is not defined

    It's because this command is intended to be run in a *shell* (also called
    a *terminal* or *console*). See the Python for Beginners
    `getting started tutorial`_ for an introduction to using your operating
    system's shell and interacting with Python.

Additionally, you'll need to make sure you have :ref:`pip` available. You can
check this by running:

.. code-block:: bash

    $ pip --version

If you installed Python from source, with an installer from `python.org`_, or
via `Homebrew`_ you should already have pip. If you're on Linux and installed
using your OS package manager, you may have to `install pip <https://pip.pypa.io/en/stable/installing/>`_ separately.

.. _getting started tutorial: https://opentechschool.github.io/python-beginners/en/getting_started.html#what-is-python-exactly
.. _python.org: https://python.org
.. _Homebrew: https://brew.sh
.. _Installing Python: http://docs.python-guide.org/en/latest/starting/installation/


☤ Installing Pipenv
-------------------

:ref:`Pipenv` is a dependency manager for Python projects. If you're familiar
with Node.js' `npm`_ or Ruby's `bundler`_, it is similar in spirit to those
tools. While :ref:`pip` can install Python packages, Pipenv is recommended as
it's a higher-level tool that simplifies dependency management for common use
cases.

Use ``pip`` to install Pipenv:

.. code-block:: python

    $ pip install --user pipenv


.. Note:: This does a `user installation`_ to prevent breaking any system-wide
    packages. If ``pipenv`` isn't available in your shell after installation,
    you'll need to add the `user base`_'s ``bin`` directory to your ``PATH``.
    You can find the user base by running ``python -m site`` which will print
    site information including the user base. For example, on Linux this will
    return ``USER_BASE: '~/.local'`` so you'll need to add ``~/.local/bin`` to
    your ``PATH``. On Linux and macOS you can set your ``PATH`` permanently
    by `modifying ~/.profile`_. On Windows you can set the user
    ``PATH`` permanently in the `Control Panel`_.

.. _npm: https://www.npmjs.com/
.. _bundler: http://bundler.io/
.. _user base: https://docs.python.org/3/library/site.html#site.USER_BASE
.. _user installation: https://pip.pypa.io/en/stable/user_guide/#user-installs
.. _modifying ~/.profile: https://stackoverflow.com/a/14638025
.. _Control Panel: https://msdn.microsoft.com/en-us/library/windows/desktop/bb776899(v=vs.85).aspx

☤ Installing packages for your project
--------------------------------------

Pipenv manages dependencies on a per-project basis. To install packages,
change into your project's directory (or just an empty directory for this
tutorial) and run:

.. code-block:: bash

    $ cd myproject
    $ pipenv install requests

Pipenv will install the excellent `Requests`_ library and create a ``Pipfile``
for you in your project's directory. The :ref:`Pipfile` is used to track which
dependencies your project needs in case you need to re-install them, such as
when you share your project with others. You should get output similar to this
(although the exact paths shown will vary):

.. code-block:: text

    Creating a Pipfile for this project...
    Creating a virtualenv for this project...
    Using base prefix '/usr/local/Cellar/python3/3.6.2/Frameworks/Python.framework/Versions/3.6'
    New python executable in ~/.local/share/virtualenvs/tmp-agwWamBd/bin/python3.6
    Also creating executable in ~/.local/share/virtualenvs/tmp-agwWamBd/bin/python
    Installing setuptools, pip, wheel...done.

    Virtualenv location: ~/.local/share/virtualenvs/tmp-agwWamBd
    Installing requests...
    Collecting requests
      Using cached requests-2.18.4-py2.py3-none-any.whl
    Collecting idna<2.7,>=2.5 (from requests)
      Using cached idna-2.6-py2.py3-none-any.whl
    Collecting urllib3<1.23,>=1.21.1 (from requests)
      Using cached urllib3-1.22-py2.py3-none-any.whl
    Collecting chardet<3.1.0,>=3.0.2 (from requests)
      Using cached chardet-3.0.4-py2.py3-none-any.whl
    Collecting certifi>=2017.4.17 (from requests)
      Using cached certifi-2017.7.27.1-py2.py3-none-any.whl
    Installing collected packages: idna, urllib3, chardet, certifi, requests
    Successfully installed certifi-2017.7.27.1 chardet-3.0.4 idna-2.6 requests-2.18.4 urllib3-1.22

    Adding requests to Pipfile's [packages]...
    P.S. You have excellent taste! ✨ 🍰 ✨

.. _Requests: https://python-requests.org


☤ Using installed packages
--------------------------

Now that Requests is installed you can create a simple ``main.py`` file to
use it:

.. code-block:: python

    import requests

    response = requests.get('https://httpbin.org/ip')

    print('Your IP is {0}'.format(response.json()['origin']))

Then you can run this script using ``pipenv run``:

.. code-block:: bash

    $ pipenv run python main.py

You should get output similar to this:

.. code-block:: text

    Your IP is 8.8.8.8

Using ``$ pipenv run`` ensures that your installed packages are available to
your script. It's also possible to spawn a new shell that ensures all commands
have access to your installed packages with ``$ pipenv shell``.


☤ Next steps
------------

Congratulations, you now know how to install and use Python packages! ✨ 🍰 ✨
