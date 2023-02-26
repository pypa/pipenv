# Pipenv: Python Dev Workflow for Humans
![pypi version](https://img.shields.io/pypi/v/pipenv.svg)(https://pypi.python.org/pypi/pipenv)

![MIT License](https://img.shields.io/pypi/l/pipenv.svg)(https://pypi.python.org/pypi/pipenv)

![Supported Versions](https://img.shields.io/pypi/pyversions/pipenv.svg)(https://pypi.python.org/pypi/pipenv)

**Pipenv** is a tool that aims to bring the best of all packaging worlds (bundler, composer, npm, cargo, yarn, etc.) to the Python world. *Windows is a first-class citizen, in our world.*

It automatically creates and manages a virtualenv for your projects, as well as adds/removes packages from your ``Pipfile`` as you install/uninstall packages. It also generates the ever-important ``Pipfile.lock``, which is used to produce deterministic builds.

Pipenv is primarily meant to provide users and developers of applications with an easy method to setup a working environment. For the distinction between libraries and applications and the usage of ``setup.py`` vs ``Pipfile`` to define dependencies, see :ref:`pipfile-vs-setuppy`.

.. image:: https://gist.githubusercontent.com/jlusk/855d611bbcfa2b159839db73d07f6ce9/raw/7f5743401809f7e630ee8ff458faa980e19924a0/pipenv.gif
   :height: 341px
   :width: 654px
   :scale: 100 %
   :alt: a short animation of pipenv at work

The problems that Pipenv seeks to solve are multi-faceted:

- You no longer need to use ``pip`` and ``virtualenv`` separately. They work together.
- Managing a ``requirements.txt`` file `can be problematic <https://kennethreitz.org/essays/2016/02/25/a-better-pip-workflow>`__, so Pipenv uses ``Pipfile`` and ``Pipfile.lock`` to separate abstract dependency declarations from the last tested combination.
- Hashes are used everywhere, always. Security. Automatically expose security vulnerabilities.
- Strongly encourage the use of the latest versions of dependencies to minimize security risks `arising from outdated components <https://www.owasp.org/index.php/Top_10-2017_A9-Using_Components_with_Known_Vulnerabilities>`_.
- Give you insight into your dependency graph (e.g. ``$ pipenv graph``).
- Streamline development workflow by loading ``.env`` files.

You can quickly play with Pipenv right in your browser:

.. image:: https://cdn.rawgit.com/rootnroll/library/assets/try.svg
    :target: https://rootnroll.com/d/pipenv/
    :alt: Try in browser


## Install Pipenv Today!

The recommended way to install pipenv on most platforms is to install from pypi using ``pip``:

    $ pip install --user pipenv

More detailed installation instructions can be found in the :ref:`installing-pipenv` chapter.

✨🍰✨

## Pipenv Features

- Enables truly *deterministic builds*, while easily specifying *only what you want*.
- Generates and checks file hashes for locked dependencies when installing from ``Pipfile.lock``.
- Automatically install required Python version when ``pyenv`` is available.
- Automatically finds your project home, recursively, by looking for a ``Pipfile``.
- Automatically generates a ``Pipfile``, if one doesn't exist.
- Automatically creates a virtualenv in a standard customizable location.
- Automatically adds/removes packages to a ``Pipfile`` when they are installed or uninstalled.
- Automatically loads ``.env`` files to support customization and overrides.


.. include:: quickstart.rst

Pipenv Documentation
----------------------------

```{toctree}
---
caption: Pipenv Documentation
maxdepth: 2
---
installation
quickstart
workflows
pipfile
commands
specifiers
shell
docker
advanced
cli
diagnose
changelog
```

Contribution Guides
-------------------

```{toctree}
---
caption: Contributing to Pipenv
maxdepth: 2
---
dev/contributing
```
