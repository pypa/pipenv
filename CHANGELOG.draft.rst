2018.7.1.dev0 (2018-07-01)
==========================


Features & Improvements
-----------------------

- All calls to ``pipenv shell`` are now implemented from the ground up using `shellingham  <https://github.com/sarugaku/shellingham>`_, a custom library which was purpose built to handle edge cases and shell detection.  `#2371 <https://github.com/pypa/pipenv/issues/2371>`_
  
- Added support for python 3.7 via a few small compatibility / bugfixes.  `#2427 <https://github.com/pypa/pipenv/issues/2427>`_,
  `#2434 <https://github.com/pypa/pipenv/issues/2434>`_,
  `#2436 <https://github.com/pypa/pipenv/issues/2436>`_
  
- Added new flag ``pipenv --support`` to replace the diagnostic command ``python -m pipenv.help``.  `#2477 <https://github.com/pypa/pipenv/issues/2477>`_,
  `#2478 <https://github.com/pypa/pipenv/issues/2478>`_
  

Bug Fixes
---------

- Fixed an ongoing bug which sometimes resolved incompatible versions into lockfiles.  `#1901 <https://github.com/pypa/pipenv/issues/1901>`_
  
- Fixed a bug which caused errors when creating virtualenvs which contained leading dash characters.  `#2415 <https://github.com/pypa/pipenv/issues/2415>`_
  
- Fixed a logic error which caused ``--deploy --system`` to overwrite editable vcs packages in the pipfile before installing, which caused any installation to fail by default.  `#2417 <https://github.com/pypa/pipenv/issues/2417>`_
  
- Updated requirementslib to fix an issue with properly quoting markers in VCS requirements.  `#2419 <https://github.com/pypa/pipenv/issues/2419>`_
  
- Installed new vendored jinja2 templates for ``click-completion`` which were causing template errors for users with completion enabled.  `#2422 <https://github.com/pypa/pipenv/issues/2422>`_
  
- Added support for python 3.7 via a few small compatibility / bugfixes.  `#2427 <https://github.com/pypa/pipenv/issues/2427>`_
  
- Fixed an issue reading package names from ``setup.py`` files in projects which imported utilities such as ``versioneer``.  `#2433 <https://github.com/pypa/pipenv/issues/2433>`_
  
- Pipenv will now ensure that its internal package names registry files are written with unicode strings.  `#2450 <https://github.com/pypa/pipenv/issues/2450>`_
  
- Fixed a bug causing requirements input as relative paths to be output as absolute paths or URIs.
  Fixed a bug affecting normalization of ``git+git@host`` uris.  `#2453 <https://github.com/pypa/pipenv/issues/2453>`_
  
- Pipenv will now always use ``pathlib2`` for ``Path`` based filesystem interactions by default on ``python<3.5``.  `#2454 <https://github.com/pypa/pipenv/issues/2454>`_
  
- Fixed a bug which prevented passing proxy PyPI indexes set with ``--pypi-mirror`` from being passed to pip during virtualenv creation, which could cause the creation to freeze in some cases.  `#2462 <https://github.com/pypa/pipenv/issues/2462>`_
  
- Using the ``python -m pipenv.help`` command will now use proper encoding for the host filesystem to avoid encoding issues.  `#2466 <https://github.com/pypa/pipenv/issues/2466>`_
  
- The new ``jinja2`` templates for ``click_completion`` will now be included in pipenv source distributions.  `#2479 <https://github.com/pypa/pipenv/issues/2479>`_
  
- Resolved a long-standing issue with re-using previously generated ``InstallRequirement`` objects for resolution which could cause ``PKG-INFO`` file information to be deleted, raising a ``TypeError``.  `#2480 <https://github.com/pypa/pipenv/issues/2480>`_
  
- Resolved an issue parsing usernames from private PyPI URIs in ``Pipfiles`` by updating ``requirementslib``.  `#2484 <https://github.com/pypa/pipenv/issues/2484>`_
  

Vendored Libraries
------------------

- All calls to ``pipenv shell`` are now implemented from the ground up using `shellingham  <https://github.com/sarugaku/shellingham>`_, a custom library which was purpose built to handle edge cases and shell detection.  `#2371 <https://github.com/pypa/pipenv/issues/2371>`_
  
- Updated requirementslib to fix an issue with properly quoting markers in VCS requirements.  `#2419 <https://github.com/pypa/pipenv/issues/2419>`_
  
- Installed new vendored jinja2 templates for ``click-completion`` which were causing template errors for users with completion enabled.  `#2422 <https://github.com/pypa/pipenv/issues/2422>`_
  
- Add patch to ``prettytoml`` to support Python 3.7.  `#2426 <https://github.com/pypa/pipenv/issues/2426>`_
  
- Patched ``prettytoml.AbstractTable._enumerate_items`` to handle ``StopIteration`` errors in preparation of release of python 3.7.  `#2427 <https://github.com/pypa/pipenv/issues/2427>`_
  
- Fixed an issue reading package names from ``setup.py`` files in projects which imported utilities such as ``versioneer``.  `#2433 <https://github.com/pypa/pipenv/issues/2433>`_
  
- Updated ``requirementslib`` to version ``1.0.8``  `#2453 <https://github.com/pypa/pipenv/issues/2453>`_
  
- Unraveled a lot of old, unnecessary patches to ``pip-tools`` which were causing non-deterministic resolution errors.  `#2480 <https://github.com/pypa/pipenv/issues/2480>`_
  
- Resolved an issue parsing usernames from private PyPI URIs in ``Pipfiles`` by updating ``requirementslib``.  `#2484 <https://github.com/pypa/pipenv/issues/2484>`_
  

Improved Documentation
----------------------

- Added instructions for installing using Fedora's official repositories.  `#2404 <https://github.com/pypa/pipenv/issues/2404>`_

