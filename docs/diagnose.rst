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

    pipenv lock --clear

and try again.

If this does not work, try manually deleting the whole cache directory. It is
usually one of the following locations:

* ``~/Library/Caches/pipenv`` (macOS)
* ``%LOCALAPPDATA%\pipenv\pipenv\Cache`` (Windows)
* ``~/.cache/pipenv`` (other operating systems)

Pipenv does not install pre-releases (i.e. a version with an alpha/beta/etc.
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
Pipenv installations, and see :ref:`installing-pipenv` to choose one of the
recommended way to install Pipenv instead.

☤ My pyenv-installed Python is not found
----------------------------------------

Make sure you have ``PYENV_ROOT`` set correctly. Pipenv only supports CPython
distributions, with version name like ``3.6.4`` or similar.

☤ Pipenv does not respect pyenv’s global and local Python versions
------------------------------------------------------------------

Pipenv by default uses the Python it is installed against to create the
virtualenv. You can set the ``--python`` option to ``$(pyenv which python)``
to use your current pyenv interpreter. See :ref:`specifying_versions` for more
information.

.. _unknown-local-diagnose:

☤ ValueError: unknown locale: UTF-8
-----------------------------------

macOS has a bug in its locale detection that prevents us from detecting your
shell encoding correctly. This can also be an issue on other systems if the
locale variables do not specify an encoding.

The workaround is to set the following two environment variables to a standard
localization format:

* ``LC_ALL``
* ``LANG``

For Bash, for example, you can add the following to your ``~/.bash_profile``:

.. code-block:: bash

    export LC_ALL='en_US.UTF-8'
    export LANG='en_US.UTF-8'

For Zsh, the file to edit is ``~/.zshrc``.

.. Note:: You can change both the ``en_US`` and ``UTF-8`` part to the
          language/locale and encoding you use.

☤ /bin/pip: No such file or directory
-------------------------------------

This may be related to your locale setting. See :ref:`unknown-local-diagnose`
for a possible solution.


☤ Pipenv does not respect dependencies in setup.py
--------------------------------------------------

No, it does not, intentionally. Pipfile and setup.py serve different purposes,
and should not consider each other by default. See :ref:`pipfile-vs-setuppy`
for more information.

☤ Using ``pipenv run`` in Supervisor program
---------------------------------------------

When you configure a supervisor program's ``command`` with ``pipenv run ...``, you
need to set locale environment variables properly to make it work.

Add this line under ``[supervisord]`` section in ``/etc/supervisor/supervisord.conf``::

    [supervisord]
    environment=LC_ALL='en_US.UTF-8',LANG='en_US.UTF-8'

☤ An exception is raised during ``Locking dependencies...``
-----------------------------------------------------------

Run ``pipenv lock --clear`` and try again. The lock sequence caches results
to speed up subsequent runs. The cache may contain faulty results if a bug
causes the format to corrupt, even after the bug is fixed. ``--clear`` flushes
the cache, and therefore removes the bad results.
