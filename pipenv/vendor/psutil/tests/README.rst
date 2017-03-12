Instructions for running tests
==============================

- The recommended way to run tests (also on Windows) is to cd into psutil root
  directory and run ``make test``.

- Depending on the Python version, dependencies for running tests include
  ``ipaddress``, ``mock`` and ``unittest2`` modules.
  On Windows also ``pywin32`` and ``wmi`` modules are recommended
  (although optional).
  Run ``make setup-dev-env`` to install all deps (also on Windows).

- To run tests on all supported Python versions install tox
  (``pip install tox``) then run ``tox`` from psutil root directory.

- Every time a commit is pushed tests are automatically run on Travis
  (Linux, OSX) and appveyor (Windows):
  - https://travis-ci.org/giampaolo/psutil/
  - https://ci.appveyor.com/project/giampaolo/psutil
