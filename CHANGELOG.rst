2018.05.18 (2018-06-17)
=======================


Features & Improvements
-----------------------

- Pipenv-created virtualenvs will now be associated with a ``.project`` folder
  (features can be implemented on top of this later or users may choose to use
  ``pipenv-pipes`` to take full advantage of this.)  `#1861
  <https://github.com/pypa/pipenv/issues/1861>`_

- Virtualenv names will now appear in prompts for most Windows users.  `#2167
  <https://github.com/pypa/pipenv/issues/2167>`_

- Added support for cmder shell paths with spaces.  `#2168
  <https://github.com/pypa/pipenv/issues/2168>`_

- Added nested JSON output to the ``pipenv graph`` command.  `#2199
  <https://github.com/pypa/pipenv/issues/2199>`_

- Dropped vendored pip 9 and vendor, patch, and migrate to pip 10. Updated
  patched piptools version.  `#2255
  <https://github.com/pypa/pipenv/issues/2255>`_

- PyPI mirror URLs can now be set to override instances of PyPI urls by passing
  the ``--pypi-mirror`` argument from the command line or setting the
  ``PIPENV_PYPI_MIRROR`` environment variable.  `#2281
  <https://github.com/pypa/pipenv/issues/2281>`_

- Virtualenv activation lines will now avoid being written to some shell
  history files.  `#2287 <https://github.com/pypa/pipenv/issues/2287>`_

- Pipenv will now only search for ``requirements.txt`` files when creating new
  projects, and during that time only if the user doesn't specify packages to
  pass in.  `#2309 <https://github.com/pypa/pipenv/issues/2309>`_

- Added support for mounted drives via UNC paths.  `#2331
  <https://github.com/pypa/pipenv/issues/2331>`_

- Added support for Windows Subsystem for Linux bash shell detection.  `#2363
  <https://github.com/pypa/pipenv/issues/2363>`_


Behavior Changes
----------------

- Pipenv will now parse & capitalize ``platform_python_implementation`` markers
  -- **note** this could cause an issue if you have an out of date ``Pipfile``
  which lowercases the comparison value (e.g. ``cpython`` instead of
  ``CPython``).  `#2123 <https://github.com/pypa/pipenv/issues/2123>`_


Bug Fixes
---------

- Massive internal improvements to requirements parsing codebase, resolver, and
  error messaging.  `#1962 <https://github.com/pypa/pipenv/issues/1962>`_,
  `#2186 <https://github.com/pypa/pipenv/issues/2186>`_,
  `#2263 <https://github.com/pypa/pipenv/issues/2263>`_,
  `#2312 <https://github.com/pypa/pipenv/issues/2312>`_

- Pipenv will now parse & capitalize ``platform_python_implementation`` markers
  -- **note** this could cause an issue if you have an out of date ``Pipfile``
  which lowercases the comparison value (e.g. ``cpython`` instead of
  ``CPython``).  `#2123 <https://github.com/pypa/pipenv/issues/2123>`_

- Fixed a bug with parsing and grouping old-style setup.py extras during
  resolution  `#2142 <https://github.com/pypa/pipenv/issues/2142>`_

- Fixed a bug causing pipenv graph to throw unhelpful exceptions when running
  against empty or non-existent environments.  `#2161
  <https://github.com/pypa/pipenv/issues/2161>`_

- Fixed a bug which caused ``--system`` to incorrectly abort when users were in
  a virtualenv.  `#2181 <https://github.com/pypa/pipenv/issues/2181>`_

- Removed vendored ``cacert.pem`` which could cause issues for some users with
  custom certificate settings.  `#2193
  <https://github.com/pypa/pipenv/issues/2193>`_

- Fixed a regression which led to direct invocations of ``virtualenv``, rather
  than calling it by module.  `#2198
  <https://github.com/pypa/pipenv/issues/2198>`_

- Locking will now pin the correct VCS ref during ``pipenv update`` runs.
  Running ``pipenv update`` with a new vcs ref specified in the ``Pipfile``
  will now properly obtain, resolve, and install the specified dependency at
  the specified ref.  `#2209 <https://github.com/pypa/pipenv/issues/2209>`_

- ``pipenv clean`` will now correctly ignore comments from ``pip freeze`` when
  cleaning the environment.  `#2262
  <https://github.com/pypa/pipenv/issues/2262>`_

- Resolution bugs causing packages for incompatible python versions to be
  locked have been fixed.  `#2267
  <https://github.com/pypa/pipenv/issues/2267>`_

- Fixed a bug causing pipenv graph to fail to display sometimes.  `#2268
  <https://github.com/pypa/pipenv/issues/2268>`_

- Updated requirementslib to fix a bug in pipfile parsing affecting relative
  path conversions.  `#2269 <https://github.com/pypa/pipenv/issues/2269>`_

- Windows executable discovery now leverages ``os.pathext``.  `#2298
  <https://github.com/pypa/pipenv/issues/2298>`_

- Fixed a bug which caused ``--deploy --system`` to inadvertently create a
  virtualenv before failing.  `#2301
  <https://github.com/pypa/pipenv/issues/2301>`_

- Fixed an issue which led to a failure to unquote special characters in file
  and wheel paths.  `#2302 <https://github.com/pypa/pipenv/issues/2302>`_

- VCS dependencies are now manually obtained only if they do not match the
  requested ref.  `#2304 <https://github.com/pypa/pipenv/issues/2304>`_


Vendored Libraries
------------------

- Removed vendored ``cacert.pem`` which could cause issues for some users with
  custom certificate settings.  `#2193
  <https://github.com/pypa/pipenv/issues/2193>`_

- Dropped vendored pip 9 and vendor, patch, and migrate to pip 10. Updated
  patched piptools version.  `#2255
  <https://github.com/pypa/pipenv/issues/2255>`_

- Updated requirementslib to fix a bug in pipfile parsing affecting relative
  path conversions.  `#2269 <https://github.com/pypa/pipenv/issues/2269>`_

- Added custom shell detection library ``shellingham``, a port of our changes
  to ``pew``.  `#2363 <https://github.com/pypa/pipenv/issues/2363>`_

Updated vendored libraries. The following vendored libraries were updated: 
  * distlib from version ``0.2.6`` to ``0.2.7``.
  * jinja2 from version ``2.9.5`` to ``2.10``.
  * pathlib2 from version ``2.1.0`` to ``2.3.2``.
  * parse from version ``2.8.0`` to ``2.8.4``.
  * pexpect from version ``2.5.2`` to ``2.6.0``.
  * requests from version ``2.18.4`` to ``2.19.1``.
  * idna from version ``2.6`` to ``2.7``.
  * certifi from version ``2018.1.16`` to ``2018.4.16``.
  * packaging from version ``16.8`` to ``17.1``.
  * six from version ``1.10.0`` to ``1.11.0``.
  * requirementslib from version ``0.2.0`` to ``1.0.1``. 

In addition, scandir was vendored and patched to avoid importing host system binaries when falling back to pathlib2.  `#2368  <https://github.com/pypa/pipenv/issues/2368>`_
