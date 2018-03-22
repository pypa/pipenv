.. _diagnose:

Frequently Encountered Pipenv Problems
======================================

Pipenv is constantly being improved by volunteers, but is still a very young
project with limited resources, and has some quirks that needs to be dealt
with. We need everyone’s help (including yours!).

Here are some common questions people have using Pipenv. Please take a look
below and see if they resolve your problem.

.. Note:: **Make sure you’re running the newest Pipenv version first!**

☤ Your dependencies could not be resolved
-----------------------------------------

Make sure your dependencies actually *do* resolve. If you’re confident they
are, you may need to clear your resolver cache. Run the following command::

    pipenv-resolver --clear

and try again.

If this does not work, try manually deleting the whole cache directory. It is
usually one of the following locations:

* ``~/Library/Cache/pipenv`` (macOS)
* ``%LOCALAPPDATA%\pipenv\pipenv\Cache`` (Windows)
* ``~/.cache/pipenv`` (other operating systems)

Pipenv does not install prereleases (i.e. a version with an alpha/beta/etc.
suffix, such as *1.0b1*) by default. You will need to pass the ``--pre`` flag
in your command, or set

::

    [pipenv]
    allow_prereleases = true

in your Pipfile.

☤ No module named <module name>
---------------------------------

This is usually a result of mixing Pipenv with system packages. We *strongly*
recommend installing Pipenv in an isolated environment. Uninstall all existing
Pipenv installations, and see :ref:`proper_installation` to choose one of the
recommended way to install Pipenv instead.

☤ My pyenv-installed Python is not found
----------------------------------------

Make sure you have ``PYENV_ROOT`` set correctly. Pipenv only supports CPython
distributions.

☤ ``shell`` does not show the virtualenv’s name in prompt
---------------------------------------------------------

This is intentional. You can do it yourself with either shell plugins, or
clever ``PS1`` configuration. If you really want it back, use

::

    pipenv shell -c

instead (not available on Windows).

☤ Pipenv does not respect dependencies in setup.py
--------------------------------------------------

No, it does not, intentionally. Pipfile and setup.py serve different purposes,
and should not consider each other by default. See :ref:`pipfile-vs-setuppy`
for more information.
