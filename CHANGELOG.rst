2018.10.13 (2018-10-13)
=======================

Bug Fixes
---------

- Fixed a bug in ``pipenv clean`` which caused global packages to sometimes be inadvertently targeted for cleanup.  `#2849 <https://github.com/pypa/pipenv/issues/2849>`_
  
- Fix broken backport imports for vendored vistir.  `#2950 <https://github.com/pypa/pipenv/issues/2950>`_,
  `#2955 <https://github.com/pypa/pipenv/issues/2955>`_,
  `#2961 <https://github.com/pypa/pipenv/issues/2961>`_
  
- Fixed a bug with importing local vendored dependencies when running ``pipenv graph``.  `#2952 <https://github.com/pypa/pipenv/issues/2952>`_
  
- Fixed a bug which caused executable discovery to fail when running inside a virtualenv.  `#2957 <https://github.com/pypa/pipenv/issues/2957>`_
  
- Fix parsing of outline tables.  `#2971 <https://github.com/pypa/pipenv/issues/2971>`_
  
- Fixed a bug which caused ``verify_ssl`` to fail to drop through to ``pip install`` correctly as ``trusted-host``.  `#2979 <https://github.com/pypa/pipenv/issues/2979>`_
  
- Fixed a bug which caused canonicalized package names to fail to resolve against PyPI.  `#2989 <https://github.com/pypa/pipenv/issues/2989>`_
  
- Enhanced CI detection to detect Azure Devops builds.  `#2993 <https://github.com/pypa/pipenv/issues/2993>`_
  
- Fixed a bug which prevented installing pinned versions which used redirection symbols from the command line.  `#2998 <https://github.com/pypa/pipenv/issues/2998>`_
  
- Fixed a bug which prevented installing the local directory in non-editable mode.  `#3005 <https://github.com/pypa/pipenv/issues/3005>`_
  

Vendored Libraries
------------------

- Updated ``requirementslib`` to version ``1.1.9``.  `#2989 <https://github.com/pypa/pipenv/issues/2989>`_
  
- Upgraded ``pythonfinder => 1.1.1`` and ``vistir => 0.1.7``.  `#3007 <https://github.com/pypa/pipenv/issues/3007>`_


2018.10.9 (2018-10-09)
======================

Features & Improvements
-----------------------

- Added environment variables `PIPENV_VERBOSE` and `PIPENV_QUIET` to control
  output verbosity without needing to pass options.  `#2527 <https://github.com/pypa/pipenv/issues/2527>`_
  
- Updated test-pypi addon to better support json-api access (forward compatibility).
  Improved testing process for new contributors.  `#2568 <https://github.com/pypa/pipenv/issues/2568>`_
  
- Greatly enhanced python discovery functionality:

  - Added pep514 (windows launcher/finder) support for python discovery.
  - Introduced architecture discovery for python installations which support different architectures.  `#2582 <https://github.com/pypa/pipenv/issues/2582>`_
  
- Added support for ``pipenv shell`` on msys and cygwin/mingw/git bash for Windows.  `#2641 <https://github.com/pypa/pipenv/issues/2641>`_
  
- Enhanced resolution of editable and VCS dependencies.  `#2643 <https://github.com/pypa/pipenv/issues/2643>`_
  
- Deduplicate and refactor CLI to use stateful arguments and object passing.  See `this issue <https://github.com/pallets/click/issues/108>`_ for reference.  `#2814 <https://github.com/pypa/pipenv/issues/2814>`_
  

Behavior Changes
----------------

- Virtual environment activation for ``run`` is revised to improve interpolation
  with other Python discovery tools.  `#2503 <https://github.com/pypa/pipenv/issues/2503>`_
  
- Improve terminal coloring to display better in Powershell.  `#2511 <https://github.com/pypa/pipenv/issues/2511>`_
  
- Invoke ``virtualenv`` directly for virtual environment creation, instead of depending on ``pew``.  `#2518 <https://github.com/pypa/pipenv/issues/2518>`_
  
- ``pipenv --help`` will now include short help descriptions.  `#2542 <https://github.com/pypa/pipenv/issues/2542>`_
  
- Add ``COMSPEC`` to fallback option (along with ``SHELL`` and ``PYENV_SHELL``)
  if shell detection fails, improving robustness on Windows.  `#2651 <https://github.com/pypa/pipenv/issues/2651>`_
  
- Fallback to shell mode if `run` fails with Windows error 193 to handle non-executable commands. This should improve usability on Windows, where some users run non-executable files without specifying a command, relying on Windows file association to choose the current command.  `#2718 <https://github.com/pypa/pipenv/issues/2718>`_
  

Bug Fixes
---------

- Fixed a bug which prevented installation of editable requirements using ``ssh://`` style urls  `#1393 <https://github.com/pypa/pipenv/issues/1393>`_
  
- VCS Refs for locked local editable dependencies will now update appropriately to the latest hash when running ``pipenv update``.  `#1690 <https://github.com/pypa/pipenv/issues/1690>`_
  
- ``.tar.gz`` and ``.zip`` artifacts will now have dependencies installed even when they are missing from the lockfile.  `#2173 <https://github.com/pypa/pipenv/issues/2173>`_
  
- The command line parser will now handle multiple ``-e/--editable`` dependencies properly via click's option parser to help mitigate future parsing issues.  `#2279 <https://github.com/pypa/pipenv/issues/2279>`_
  
- Fixed the ability of pipenv to parse ``dependency_links`` from ``setup.py`` when ``PIP_PROCESS_DEPENDENCY_LINKS`` is enabled.  `#2434 <https://github.com/pypa/pipenv/issues/2434>`_
  
- Fixed a bug which could cause ``-i/--index`` arguments to sometimes be incorrectly picked up in packages.  This is now handled in the command line parser.  `#2494 <https://github.com/pypa/pipenv/issues/2494>`_
  
- Fixed non-deterministic resolution issues related to changes to the internal package finder in ``pip 10``.  `#2499 <https://github.com/pypa/pipenv/issues/2499>`_,
  `#2529 <https://github.com/pypa/pipenv/issues/2529>`_,
  `#2589 <https://github.com/pypa/pipenv/issues/2589>`_,
  `#2666 <https://github.com/pypa/pipenv/issues/2666>`_,
  `#2767 <https://github.com/pypa/pipenv/issues/2767>`_,
  `#2785 <https://github.com/pypa/pipenv/issues/2785>`_,
  `#2795 <https://github.com/pypa/pipenv/issues/2795>`_,
  `#2801 <https://github.com/pypa/pipenv/issues/2801>`_,
  `#2824 <https://github.com/pypa/pipenv/issues/2824>`_,
  `#2862 <https://github.com/pypa/pipenv/issues/2862>`_,
  `#2879 <https://github.com/pypa/pipenv/issues/2879>`_,
  `#2894 <https://github.com/pypa/pipenv/issues/2894>`_,
  `#2933 <https://github.com/pypa/pipenv/issues/2933>`_
  
- Fix subshell invocation on Windows for Python 2.  `#2515 <https://github.com/pypa/pipenv/issues/2515>`_
  
- Fixed a bug which sometimes caused pipenv to throw a ``TypeError`` or to run into encoding issues when writing lockfiles on python 2.  `#2561 <https://github.com/pypa/pipenv/issues/2561>`_
  
- Improve quoting logic for ``pipenv run`` so it works better with Windows
  built-in commands.  `#2563 <https://github.com/pypa/pipenv/issues/2563>`_
  
- Fixed a bug related to parsing vcs requirements with both extras and subdirectory fragments.
  Corrected an issue in the ``requirementslib`` parser which led to some markers being discarded rather than evaluated.  `#2564 <https://github.com/pypa/pipenv/issues/2564>`_
  
- Fixed multiple issues with finding the correct system python locations.  `#2582 <https://github.com/pypa/pipenv/issues/2582>`_
  
- Catch JSON decoding error to prevent exception when the lock file is of
  invalid format.  `#2607 <https://github.com/pypa/pipenv/issues/2607>`_
  
- Fixed a rare bug which could sometimes cause errors when installing packages with custom sources.  `#2610 <https://github.com/pypa/pipenv/issues/2610>`_
  
- Update requirementslib to fix a bug which could raise an ``UnboundLocalError`` when parsing malformed VCS URIs.  `#2617 <https://github.com/pypa/pipenv/issues/2617>`_
  
- Fixed an issue which prevented passing multiple ``--ignore`` parameters to ``pipenv check``.  `#2632 <https://github.com/pypa/pipenv/issues/2632>`_
  
- Fixed a bug which caused attempted hashing of ``ssh://`` style URIs which could cause failures during installation of private ssh repositories.
  - Corrected path conversion issues which caused certain editable VCS paths to be converted to ``ssh://`` URIs improperly.  `#2639 <https://github.com/pypa/pipenv/issues/2639>`_
  
- Fixed a bug which caused paths to be formatted incorrectly when using ``pipenv shell`` in bash for windows.  `#2641 <https://github.com/pypa/pipenv/issues/2641>`_
  
- Dependency links to private repositories defined via ``ssh://`` schemes will now install correctly and skip hashing as long as ``PIP_PROCESS_DEPENDENCY_LINKS=1``.  `#2643 <https://github.com/pypa/pipenv/issues/2643>`_
  
- Fixed a bug which sometimes caused pipenv to parse the ``trusted_host`` argument to pip incorrectly when parsing source URLs which specify ``verify_ssl = false``.  `#2656 <https://github.com/pypa/pipenv/issues/2656>`_
  
- Prevent crashing when a virtual environment in ``WORKON_HOME`` is faulty.  `#2676 <https://github.com/pypa/pipenv/issues/2676>`_
  
- Fixed virtualenv creation failure when a .venv file is present in the project root.  `#2680 <https://github.com/pypa/pipenv/issues/2680>`_
  
- Fixed a bug which could cause the ``-e/--editable`` argument on a dependency to be accidentally parsed as a dependency itself.  `#2714 <https://github.com/pypa/pipenv/issues/2714>`_
  
- Correctly pass `verbose` and `debug` flags to the resolver subprocess so it generates appropriate output. This also resolves a bug introduced by the fix to #2527.  `#2732 <https://github.com/pypa/pipenv/issues/2732>`_
  
- All markers are now included in ``pipenv lock --requirements`` output.  `#2748 <https://github.com/pypa/pipenv/issues/2748>`_
  
- Fixed a bug in marker resolution which could cause duplicate and non-deterministic markers.  `#2760 <https://github.com/pypa/pipenv/issues/2760>`_
  
- Fixed a bug in the dependency resolver which caused regular issues when handling ``setup.py`` based dependency resolution.  `#2766 <https://github.com/pypa/pipenv/issues/2766>`_
  
- Updated vendored dependencies:
    - ``pip-tools`` (updated and patched to latest w/ ``pip 18.0`` compatibilty)
    - ``pip 10.0.1 => 18.0``
    - ``click 6.7 => 7.0``
    - ``toml 0.9.4 => 0.10.0``
    - ``pyparsing 2.2.0 => 2.2.2``
    - ``delegator 0.1.0 => 0.1.1``
    - ``attrs 18.1.0 => 18.2.0``
    - ``distlib 0.2.7 => 0.2.8``
    - ``packaging 17.1.0 => 18.0``
    - ``passa 0.2.0 => 0.3.1``
    - ``pip_shims 0.1.2 => 0.3.1``
    - ``plette 0.1.1 => 0.2.2``
    - ``pythonfinder 1.0.2 => 1.1.0``
    - ``pytoml 0.1.18 => 0.1.19``
    - ``requirementslib 1.1.16 => 1.1.17``
    - ``shellingham 1.2.4 => 1.2.6``
    - ``tomlkit 0.4.2 => 0.4.4``
    - ``vistir 0.1.4 => 0.1.6``  `#2802 <https://github.com/pypa/pipenv/issues/2802>`_,
  `#2867 <https://github.com/pypa/pipenv/issues/2867>`_,
  `#2880 <https://github.com/pypa/pipenv/issues/2880>`_
  
- Fixed a bug where `pipenv` crashes when the `WORKON_HOME` directory does not exist.  `#2877 <https://github.com/pypa/pipenv/issues/2877>`_
  
- Fixed pip is not loaded from pipenv's patched one but the system one  `#2912 <https://github.com/pypa/pipenv/issues/2912>`_
  
- Fixed various bugs related to ``pip 18.1`` release which prevented locking, installation, and syncing, and dumping to a ``requirements.txt`` file.  `#2924 <https://github.com/pypa/pipenv/issues/2924>`_
  

Vendored Libraries
------------------

- Pew is no longer vendored. Entry point ``pewtwo``, packages ``pipenv.pew`` and
  ``pipenv.patched.pew`` are removed.  `#2521 <https://github.com/pypa/pipenv/issues/2521>`_
  
- Update ``pythonfinder`` to major release ``1.0.0`` for integration.  `#2582 <https://github.com/pypa/pipenv/issues/2582>`_
  
- Update requirementslib to fix a bug which could raise an ``UnboundLocalError`` when parsing malformed VCS URIs.  `#2617 <https://github.com/pypa/pipenv/issues/2617>`_
  
- - Vendored new libraries ``vistir`` and ``pip-shims``, ``tomlkit``, ``modutil``, and ``plette``.

  - Update vendored libraries:
    - ``scandir`` to ``1.9.0``
    - ``click-completion`` to ``0.4.1``
    - ``semver`` to ``2.8.1``
    - ``shellingham`` to ``1.2.4``
    - ``pytoml`` to ``0.1.18``
    - ``certifi`` to ``2018.8.24``
    - ``ptyprocess`` to ``0.6.0``
    - ``requirementslib`` to ``1.1.5``
    - ``pythonfinder`` to ``1.0.2``
    - ``pipdeptree`` to ``0.13.0``
    - ``python-dotenv`` to ``0.9.1``  `#2639 <https://github.com/pypa/pipenv/issues/2639>`_
  
- Updated vendored dependencies:
    - ``pip-tools`` (updated and patched to latest w/ ``pip 18.0`` compatibilty)
    - ``pip 10.0.1 => 18.0``
    - ``click 6.7 => 7.0``
    - ``toml 0.9.4 => 0.10.0``
    - ``pyparsing 2.2.0 => 2.2.2``
    - ``delegator 0.1.0 => 0.1.1``
    - ``attrs 18.1.0 => 18.2.0``
    - ``distlib 0.2.7 => 0.2.8``
    - ``packaging 17.1.0 => 18.0``
    - ``passa 0.2.0 => 0.3.1``
    - ``pip_shims 0.1.2 => 0.3.1``
    - ``plette 0.1.1 => 0.2.2``
    - ``pythonfinder 1.0.2 => 1.1.0``
    - ``pytoml 0.1.18 => 0.1.19``
    - ``requirementslib 1.1.16 => 1.1.17``
    - ``shellingham 1.2.4 => 1.2.6``
    - ``tomlkit 0.4.2 => 0.4.4``
    - ``vistir 0.1.4 => 0.1.6``  `#2902 <https://github.com/pypa/pipenv/issues/2902>`_,
  `#2935 <https://github.com/pypa/pipenv/issues/2935>`_
  

Improved Documentation
----------------------

- Simplified the test configuration process.  `#2568 <https://github.com/pypa/pipenv/issues/2568>`_
  
- Updated documentation to use working fortune cookie addon.  `#2644 <https://github.com/pypa/pipenv/issues/2644>`_
  
- Added additional information about troubleshooting ``pipenv shell`` by using the the ``$PIPENV_SHELL`` environment variable.  `#2671 <https://github.com/pypa/pipenv/issues/2671>`_
  
- Added a link to ``PEP-440`` version specifiers in the documentation for additional detail.  `#2674 <https://github.com/pypa/pipenv/issues/2674>`_
  
- Added simple example to README.md for installing from git.  `#2685 <https://github.com/pypa/pipenv/issues/2685>`_
  
- Stopped recommending `--system` for Docker contexts.  `#2762 <https://github.com/pypa/pipenv/issues/2762>`_
  
- Fixed the example url for doing "pipenv install -e
  some-repo-url#egg=something", it was missing the "egg=" in the fragment
  identifier.  `#2792 <https://github.com/pypa/pipenv/issues/2792>`_
  
- Fixed link to the "be cordial" essay in the contribution documentation.  `#2793 <https://github.com/pypa/pipenv/issues/2793>`_
  
- Clarify `pipenv install` documentation  `#2844 <https://github.com/pypa/pipenv/issues/2844>`_
  
- Replace reference to uservoice with PEEP-000  `#2909 <https://github.com/pypa/pipenv/issues/2909>`_


2018.7.1 (2018-07-01)
=====================

Features & Improvements
-----------------------

- All calls to ``pipenv shell`` are now implemented from the ground up using `shellingham  <https://github.com/sarugaku/shellingham>`_, a custom library which was purpose built to handle edge cases and shell detection.  `#2371 <https://github.com/pypa/pipenv/issues/2371>`_
  
- Added support for python 3.7 via a few small compatibility / bugfixes.  `#2427 <https://github.com/pypa/pipenv/issues/2427>`_,
  `#2434 <https://github.com/pypa/pipenv/issues/2434>`_,
  `#2436 <https://github.com/pypa/pipenv/issues/2436>`_
  
- Added new flag ``pipenv --support`` to replace the diagnostic command ``python -m pipenv.help``.  `#2477 <https://github.com/pypa/pipenv/issues/2477>`_,
  `#2478 <https://github.com/pypa/pipenv/issues/2478>`_
  
- Improved import times and CLI runtimes with minor tweaks.  `#2485 <https://github.com/pypa/pipenv/issues/2485>`_
  

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
  
- Updated ``requirementslib`` to version ``1.0.9``  `#2453 <https://github.com/pypa/pipenv/issues/2453>`_
  
- Unraveled a lot of old, unnecessary patches to ``pip-tools`` which were causing non-deterministic resolution errors.  `#2480 <https://github.com/pypa/pipenv/issues/2480>`_
  
- Resolved an issue parsing usernames from private PyPI URIs in ``Pipfiles`` by updating ``requirementslib``.  `#2484 <https://github.com/pypa/pipenv/issues/2484>`_
  

Improved Documentation
----------------------

- Added instructions for installing using Fedora's official repositories.  `#2404 <https://github.com/pypa/pipenv/issues/2404>`_


2018.6.25 (2018-06-25)
======================

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

- Dropped vendored pip 9 and vendored, patched, and migrated to pip 10. Updated
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

- Pipenv will now generate hashes much more quickly by resolving them in a
  single pass during locking.  `#2384
  <https://github.com/pypa/pipenv/issues/2384>`_

- ``pipenv run`` will now avoid spawning additional ``COMSPEC`` instances to
  run commands in when possible.  `#2385
  <https://github.com/pypa/pipenv/issues/2385>`_

- Massive internal improvements to requirements parsing codebase, resolver, and
  error messaging.  `#2388 <https://github.com/pypa/pipenv/issues/2388>`_

- ``pipenv check`` now may take multiple of the additional argument
  ``--ignore`` which takes a parameter ``cve_id`` for the purpose of ignoring
  specific CVEs.  `#2408 <https://github.com/pypa/pipenv/issues/2408>`_


Behavior Changes
----------------

- Pipenv will now parse & capitalize ``platform_python_implementation`` markers
  .. warning:: This could cause an issue if you have an out of date ``Pipfile``
  which lowercases the comparison value (e.g. ``cpython`` instead of
  ``CPython``).  `#2123 <https://github.com/pypa/pipenv/issues/2123>`_

- Pipenv will now only search for ``requirements.txt`` files when creating new
  projects, and during that time only if the user doesn't specify packages to
  pass in.  `#2309 <https://github.com/pypa/pipenv/issues/2309>`_


Bug Fixes
---------

- Massive internal improvements to requirements parsing codebase, resolver, and
  error messaging.  `#1962 <https://github.com/pypa/pipenv/issues/1962>`_,
  `#2186 <https://github.com/pypa/pipenv/issues/2186>`_,
  `#2263 <https://github.com/pypa/pipenv/issues/2263>`_,
  `#2312 <https://github.com/pypa/pipenv/issues/2312>`_

- Pipenv will now parse & capitalize ``platform_python_implementation``
  markers.  `#2123 <https://github.com/pypa/pipenv/issues/2123>`_

- Fixed a bug with parsing and grouping old-style ``setup.py`` extras during
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

- Updated ``requirementslib`` to fix a bug in pipfile parsing affecting
  relative path conversions.  `#2269
  <https://github.com/pypa/pipenv/issues/2269>`_

- Windows executable discovery now leverages ``os.pathext``.  `#2298
  <https://github.com/pypa/pipenv/issues/2298>`_

- Fixed a bug which caused ``--deploy --system`` to inadvertently create a
  virtualenv before failing.  `#2301
  <https://github.com/pypa/pipenv/issues/2301>`_

- Fixed an issue which led to a failure to unquote special characters in file
  and wheel paths.  `#2302 <https://github.com/pypa/pipenv/issues/2302>`_

- VCS dependencies are now manually obtained only if they do not match the
  requested ref.  `#2304 <https://github.com/pypa/pipenv/issues/2304>`_

- Added error handling functionality to properly cope with single-digit
  ``Requires-Python`` metatdata with no specifiers.  `#2377
  <https://github.com/pypa/pipenv/issues/2377>`_

- ``pipenv update`` will now always run the resolver and lock before ensuring
  your dependencies are in sync with your lockfile.  `#2379
  <https://github.com/pypa/pipenv/issues/2379>`_

- Resolved a bug in our patched resolvers which could cause nondeterministic
  resolution failures in certain conditions. Running ``pipenv install`` with no
  arguments in a project with only a ``Pipfile`` will now correctly lock first
  for dependency resolution before installing.  `#2384
  <https://github.com/pypa/pipenv/issues/2384>`_

- Patched ``python-dotenv`` to ensure that environment variables always get
  encoded to the filesystem encoding.  `#2386
  <https://github.com/pypa/pipenv/issues/2386>`_


Improved Documentation
----------------------

- Update documentation wording to clarify Pipenv's overall role in the packaging ecosystem.  `#2194 <https://github.com/pypa/pipenv/issues/2194>`_
  
- Added contribution documentation and guidelines.  `#2205 <https://github.com/pypa/pipenv/issues/2205>`_
  
- Added instructions for supervisord compatibility.  `#2215 <https://github.com/pypa/pipenv/issues/2215>`_
  
- Fixed broken links to development philosophy and contribution documentation.  `#2248 <https://github.com/pypa/pipenv/issues/2248>`_


Vendored Libraries
------------------

- Removed vendored ``cacert.pem`` which could cause issues for some users with
  custom certificate settings.  `#2193
  <https://github.com/pypa/pipenv/issues/2193>`_

- Dropped vendored pip 9 and vendored, patched, and migrated to pip 10. Updated
  patched piptools version.  `#2255
  <https://github.com/pypa/pipenv/issues/2255>`_

- Updated ``requirementslib`` to fix a bug in pipfile parsing affecting
  relative path conversions.  `#2269
  <https://github.com/pypa/pipenv/issues/2269>`_

- Added custom shell detection library ``shellingham``, a port of our changes
  to ``pew``.  `#2363 <https://github.com/pypa/pipenv/issues/2363>`_

- Patched ``python-dotenv`` to ensure that environment variables always get
  encoded to the filesystem encoding.  `#2386
  <https://github.com/pypa/pipenv/issues/2386>`_

- Updated vendored libraries. The following vendored libraries were updated:

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

  In addition, scandir was vendored and patched to avoid importing host system binaries when falling back to pathlib2.  `#2368 <https://github.com/pypa/pipenv/issues/2368>`_

