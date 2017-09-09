.. pipenv documentation master file, created by
   sphinx-quickstart on Mon Jan 30 13:28:36 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Pipenv: Sacred Marriage of Pipfile, Pip, & Virtualenv
=====================================================

.. image:: https://img.shields.io/pypi/v/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/l/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/wheel/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/pyversions/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://travis-ci.org/kennethreitz/pipenv.svg?branch=master
    :target: https://travis-ci.org/kennethreitz/pipenv

.. image:: https://img.shields.io/badge/Say%20Thanks!-🦉-1EAEDB.svg
    :target: https://saythanks.io/to/kennethreitz

---------------

**Pipenv** — the officially recommended Python packaging tool from `Python.org <https://packaging.python.org/new-tutorials/installing-and-using-packages/>`_, free (as in freedom).

Pipenv is a project that aims to bring the best of all packaging worlds to the Python world. It harnesses `Pipfile <https://github.com/pypa/pipfile>`_, `pip <https://github.com/pypa/pip>`_, and `virtualenv <https://github.com/pypa/virtualenv>`_ into one single toolchain. It features very pretty terminal colors. *Windows is a first–class citizen, in our world.*

It automatically creates and manages a virtualenv for your projects, as well as adds/removes packages from your ``Pipfile`` as you install/uninstall packages. The ``lock`` command generates a lockfile (``Pipfile.lock``).


.. raw:: html

    <iframe src="https://player.vimeo.com/video/233134524" width="700" height="460" frameborder="0" webkitallowfullscreen mozallowfullscreen allowfullscreen></iframe>

The problems that Pipenv seeks to solve are multi-faceted:

- When using Pipenv, you no longer need to use ``pip`` and ``virtualenv`` separately. They work together.
- Managing a ``requirements.txt`` file `can be problematic <https://www.kennethreitz.org/essays/a-better-pip-workflow>`_, so Pipenv uses the upcoming ``Pipfile`` and ``Pipfile.lock`` instead, which is superior for basic use cases.
- Hashes are used everywhere, always. Security.


Install Pipenv Today!
---------------------

::

    $ pip install pipenv
    ✨🍰✨

If you have excellent taste, there's also a  `fancy installation method <http://docs.pipenv.org/en/latest/advanced.html#fancy-installation-of-pipenv>`_.

.. toctree::
   :maxdepth: 2

   basics

User Testimonials
-----------------

**Jannis Leidel**, former pip maintainer—
    *Pipenv is the porcelain I always wanted built for pip. It fits my brain and mostly replaces virtualenvwrapper and manual pip calls for me. Use it.*

**Jhon Crypt**—
    *Pipenv is the best thing since pip, thank you!*

**Isaac Sanders**—
    *Pipenv is literally the best thing about my day today. Thanks, Kenneth!*

☤ Pipenv Features
-----------------

- Enables truly *deterministic builds*, while easily specifying *what you want*.
- Automatically generates and checks file hashes for locked dependencies.
- Automatically finds your project home, recursively, by looking for a ``Pipfile``.
- Automatically generates a ``Pipfile``, if one doesn't exist.
- Automatically generates a ``Pipfile.lock``, if one doesn't exist.
- Automatically creates a virtualenv in a standard location.
- Automatically adds packages to a Pipfile when they are installed.
- Automatically removes packages from a Pipfile when they are un-installed.
- Also automatically updates pip and itself, when asked.

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

- ``shell`` will spawn a shell with the virtualenv activated.
- ``run`` will run a given command from the virtualenv, with any arguments forwarded (e.g. ``$ pipenv run python``).
- ``check`` asserts that PEP 508 requirements are being met by the current environment.


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
