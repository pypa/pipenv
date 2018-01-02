.. pipenv documentation master file, created by
   sphinx-quickstart on Mon Jan 30 13:28:36 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Pipenv: Python Dev Workflow for Humans
======================================

.. image:: https://img.shields.io/pypi/v/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/l/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/pyversions/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/badge/Say%20Thanks!-🦉-1EAEDB.svg
    :target: https://saythanks.io/to/kennethreitz

---------------

**Pipenv** — the officially recommended Python packaging tool from `Python.org <https://packaging.python.org/tutorials/managing-dependencies/#managing-dependencies>`_, free (as in freedom).

Pipenv is a tool that aims to bring the best of all packaging worlds (bundler, composer, npm, cargo, yarn, etc.) to the Python world. *Windows is a first–class citizen, in our world.*

It automatically creates and manages a virtualenv for your projects, as well as adds/removes packages from your ``Pipfile`` as you install/uninstall packages. It also generates the ever–important ``Pipfile.lock``, which is used to produce deterministic builds.


.. raw:: html

    <iframe src="https://player.vimeo.com/video/233134524" width="700" height="460" frameborder="0" webkitallowfullscreen mozallowfullscreen allowfullscreen></iframe>

The problems that Pipenv seeks to solve are multi-faceted:

- You no longer need to use ``pip`` and ``virtualenv`` separately. They work together.
- Managing a ``requirements.txt`` file `can be problematic <https://www.kennethreitz.org/essays/a-better-pip-workflow>`_, so Pipenv uses the upcoming ``Pipfile`` and ``Pipfile.lock`` instead, which is superior for basic use cases.
- Hashes are used everywhere, always. Security. Automatically expose security vulnerabilities.
- Give you insight into your dependency graph (e.g. ``$ pipenv graph``).
- Streamline development workflow by loading ``.env`` files.


Install Pipenv Today!
---------------------


.. note:: The use of **Python 3** is *highly* preferred over Python 2, when installing Pipenv. Compatibility with three virtualenvs is greatly improved when using Python 3 as the installation target.

  —*Kenneth Reitz*

Pipenv is a python package and so can be installed using ``pip`` as you would expect.
::

    $ pip install pipenv
    ✨🍰✨

If you have excellent taste, there are various other installation methods which
prevent pipenv and its dependencies from interfering with the rest of your
Python installation. These include
`Pipsi <https://docs.pipenv.org/install/#fancy-installation-of-pipenv>`_,
`Nix <https://docs.pipenv.org/install/#referentially-transparent-installation-of-pipenv>`_
and `Homebrew <https://docs.pipenv.org/install/#homebrew-installation-of-pipenv>`_.

.. toctree::
   :maxdepth: 2

   install

User Testimonials
-----------------

**Jannis Leidel**, former pip maintainer—
    *Pipenv is the porcelain I always wanted to build for pip. It fits my brain and mostly replaces virtualenvwrapper and manual pip calls for me. Use it.*

**Justin Myles Holmes**—
    *Pipenv is finally an abstraction meant to engage the mind instead of merely the filesystem.*

**Isaac Sanders**—
    *Pipenv is literally the best thing about my day today. Thanks, Kenneth!*

☤ Pipenv Features
-----------------

- Enables truly *deterministic builds*, while easily specifying *only what you want*.
- Generates and checks file hashes for locked dependencies.
- Automatically install required Pythons, if ``pyenv`` is available.
- Automatically finds your project home, recursively, by looking for a ``Pipfile``.
- Automatically generates a ``Pipfile``, if one doesn't exist.
- Automatically creates a virtualenv in a standard location.
- Automatically adds/removes packages to a ``Pipfile`` when they are un/installed.
- Automatically loads ``.env`` files, if they exist.

The main commands are ``install``, ``uninstall``, and ``lock``, which generates a ``Pipfile.lock``. These are intended to replace ``$ pip install`` usage, as well as manual virtualenv management (to activate a virtualenv, run ``$ pipenv shell``).

Basic Concepts
//////////////

- A virtualenv will automatically be created, when one doesn't exist.
- When no parameters are passed to ``install``, all packages ``[packages]`` specified will be installed.
- To initialize a Python 3 virtual environment, run ``$ pipenv --three``.
- To initialize a Python 2 virtual environment, run ``$ pipenv --two``.
- Otherwise, whatever virtualenv defaults to will be the default.



Other Commands
//////////////

- ``graph`` will show you a dependency graph, of your installed dependencies.
- ``shell`` will spawn a shell with the virtualenv activated.
- ``run`` will run a given command from the virtualenv, with any arguments forwarded (e.g. ``$ pipenv run python``).
- ``check`` checks for security vulnerabilities and asserts that PEP 508 requirements are being met by the current environment.


Further Documentation Guides
----------------------------

.. toctree::
   :maxdepth: 2

   basics
   advanced

☤ Pipenv Usage
--------------

.. click:: pipenv:cli
   :prog: pipenv
   :show-nested:

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
