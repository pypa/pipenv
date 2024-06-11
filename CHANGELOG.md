2024.0.1 (2024-06-11)
=====================
Pipenv 2024.0.1 (2024-06-11)
============================


No significant changes.


2024.0.0 (2024-06-06)
=====================
Pipenv 2024.0.0 (2024-06-06)
============================

Features & Improvements
-----------------------

- Supply any ``--extra-pip-args`` also in the resolver steps.  `#6006 <https://github.com/pypa/pipenv/issues/6006>`_
- The ``uninstall`` command now does the inverse of ``upgrade`` which means it no longer invokes a full ``lock`` cycle which was problematic for projects with many dependencies.  `#6029 <https://github.com/pypa/pipenv/issues/6029>`_
- The ``pipenv requirements`` subcommand now supports the ``--from-pipfile`` flag. When this flag is used, the requirements file will only include the packages explicitly listed in the Pipfile, excluding any sub-packages.  `#6156 <https://github.com/pypa/pipenv/issues/6156>`_

Behavior Changes
----------------

- ``pipenv==3000.0.0`` denotes the first major release of our semver strategy.
  As much requested, the ``install`` no longer does a complete lock operation.  Instead ``install`` follows the same code path as pipenv update (which is upgrade + sync).
  This is what most new users expect the behavior to be; it is a behavioral change, a necessary one to make the tool more usable.
  Remember that complete lock resolution can be invoked with ``pipenv lock`` just as before.  `#6098 <https://github.com/pypa/pipenv/issues/6098>`_

Bug Fixes
---------

- Fix a bug that passes pipenv check command if Pipfile.lock not exist  `#6126 <https://github.com/pypa/pipenv/issues/6126>`_
- Fix a bug that vcs subdependencies were locked without their subdirectory fragment if they had one  `#6136 <https://github.com/pypa/pipenv/issues/6136>`_
- ``pipenv`` converts off ``pkg_resources`` API usages.  This necessitated also vendoring in:
  * latest ``pipdeptree==2.18.1`` which also converted off ``pkg_resources``
  * ``importlib-metadata==7.1.0`` to continue supporting python 3.8 and 3.9
  * ``packaging==24.0`` since the packaging we were utilizing in pip's _vendor was insufficient for this conversion.  `#6139 <https://github.com/pypa/pipenv/issues/6139>`_
- Pipenv only supports absolute python version. If the user specifies a Python version with inequality signs like >=3.12, <3.12 in the [requires] field, the code has been modified to explicitly express in an error log that absolute versioning must be used.  `#6164 <https://github.com/pypa/pipenv/issues/6164>`_

Vendored Libraries
------------------

- Vendor in ``pip==24.0``  `#6117 <https://github.com/pypa/pipenv/issues/6117>`_
- Spring 2024 Vendoring includes:
  * ``click-didyoumean==0.3.1``
  * ``expect==4.9.0``
  * ``pipdeptree==2.16.2``
  * ``python-dotenv==1.0.1``
  * ``ruamel.yaml==0.18.6``
  * ``shellingham==1.5.4``
  * ``tomlkit==0.12.4``  `#6118 <https://github.com/pypa/pipenv/issues/6118>`_


2023.12.1 (2024-02-04)
======================
Pipenv 2023.12.1 (2024-02-04)
=============================


Bug Fixes
---------

- Remove debug print statements that should not have made it into the last release.  `#6079 <https://github.com/pypa/pipenv/issues/6079>`_
2023.12.0 (2024-02-01)
======================
Pipenv 2023.12.0 (2024-02-01)
=============================


Bug Fixes
---------

- Removal of pydantic from pythonfinder and pipenv; reduced complexity of pythonfinder pathlib usage (avoid posix conversions).  `#6065 <https://github.com/pypa/pipenv/issues/6065>`_
- Adjusted logic which assumed any file, path or VCS install should be considered editable.  Instead relies on the user specified editable flag to mark requirement as editable install.  `#6069 <https://github.com/pypa/pipenv/issues/6069>`_
- Remove logic that treats ``CI`` variable to use ``do_run_nt`` shell logic, as the original reasons for that patch were no longer valid.  `#6072 <https://github.com/pypa/pipenv/issues/6072>`_
2023.11.17 (2024-01-21)
=======================
Pipenv 2023.11.17 (2024-01-21)
==============================


Bug Fixes
---------

- Add markers to Pipfile when parsing requirements.txt  `#6008 <https://github.com/pypa/pipenv/issues/6008>`_
- Fix KeyError when using a source without a name in Pipfile  `#6021 <https://github.com/pypa/pipenv/issues/6021>`_
- Fix a bug with locking projects that contains packages with non canonical names from private indexes  `#6056 <https://github.com/pypa/pipenv/issues/6056>`_

Vendored Libraries
------------------

- Update vendored tomlkit to ``0.12.3``  `#6024 <https://github.com/pypa/pipenv/issues/6024>`_
- Bump version of pipdeptree to 0.13.2  `#6055 <https://github.com/pypa/pipenv/issues/6055>`_
2023.11.15 (2023-11-15)
=======================
Pipenv 2023.11.15 (2023-11-15)
==============================


Bug Fixes
---------

- Fix regression with path installs on most recent release ``2023.11.14``  `#6017 <https://github.com/pypa/pipenv/issues/6017>`_


2023.11.14 (2023-11-14)
=======================
Pipenv 2023.11.14 (2023-11-14)
==============================


Behavior Changes
----------------

- pipenv now ignores existing venv dir when ``PIPENV_VENV_IN_PROJECT`` is false.  `#6009 <https://github.com/pypa/pipenv/issues/6009>`_

Bug Fixes
---------

- Assume the vcs and direct URL installs need to be reinstalled.  `#5936 <https://github.com/pypa/pipenv/issues/5936>`_
- Pass through pipfile index urls when creating https session so that keyring fully works  `#5994 <https://github.com/pypa/pipenv/issues/5994>`_
- Fix Using dependencies from a URL fails on Windows.  `#6011 <https://github.com/pypa/pipenv/issues/6011>`_


2023.10.24 (2023-10-24)
=======================
Pipenv 2023.10.24 (2023-10-24)
==============================


Features & Improvements
-----------------------

- Officially support python 3.12  `#5987 <https://github.com/pypa/pipenv/issues/5987>`_

Bug Fixes
---------

- Additional safety check in _fold_markers logic that affected some lock resolutions in prior release.  `#5988 <https://github.com/pypa/pipenv/issues/5988>`_

Vendored Libraries
------------------

- Update vendored versions of:
    * click==8.1.7
    * markupsafe==2.1.3
    * pydantic==1.10.13
    * pythonfinder==2.0.6
    * ruamel.yaml==0.17.39
    * shellingham==1.5.3
    * tomlkit==0.12.1  `#5986 <https://github.com/pypa/pipenv/issues/5986>`_
- Update vendored pip to ``23.3.1``  `#5991 <https://github.com/pypa/pipenv/issues/5991>`_


2023.10.20 (2023-10-20)
=======================

Features & Improvements
-----------------------

- Add quiet option to pipenv shell, hiding "Launching subshell in virtual environment..."  `#5966 <https://github.com/pypa/pipenv/issues/5966>`_
- Vendor in pip==23.3 which includes updates to certifi, urllib3, and  adds truststore among other improvements.  `#5979 <https://github.com/pypa/pipenv/issues/5979>`_

Behavior Changes
----------------

- Change ``--py`` to use ``print`` preventing insertion of newline characters  `#5969 <https://github.com/pypa/pipenv/issues/5969>`_

Vendored Libraries
------------------

- Drop pep517 - as it is no longer used.  `#5970 <https://github.com/pypa/pipenv/issues/5970>`_

Removals and Deprecations
-------------------------

- Drop support for Python 3.7  `#5879 <https://github.com/pypa/pipenv/issues/5879>`_


2023.10.3 (2023-10-03)
======================

Bug Fixes
---------

- Eveb better handling of vcs branch references that contain special characters.  `#5934 <https://github.com/pypa/pipenv/issues/5934>`_
- Bump certifi from 2023.5.7 to 2023.7.22 in /examples to address a security vulnerability  `#5941 <https://github.com/pypa/pipenv/issues/5941>`_


2023.9.8 (2023-09-08)
=====================

Bug Fixes
---------

- ignore_compatibility was supposed to default to False (except for hash collection)  `#5926 <https://github.com/pypa/pipenv/issues/5926>`_


2023.9.7 (2023-09-07)
=====================

Features & Improvements
-----------------------

- Updates build to use exclusively ``pyproject.toml``
  ---------------------------------------------------

  Modernizes the build process by consolidating all of ``setuptools`` metadata within ``pyproject.toml`` and removing deprecated ``setup.cfg`` and ``setup.py``.  `#5837 <https://github.com/pypa/pipenv/issues/5837>`_

Bug Fixes
---------

- Restore the ignore compatibility finder pip patch to resolve issues collecting hashes from google artifact registry (and possibly others).  `#5887 <https://github.com/pypa/pipenv/issues/5887>`_
- Handle case better where setup.py name is referencing a variable that is a string while encouraging folks to migrate their projects to pyproject.toml  `#5905 <https://github.com/pypa/pipenv/issues/5905>`_
- Better handling of local file install edge cases; handle local file extras.  `#5919 <https://github.com/pypa/pipenv/issues/5919>`_
- Include the Pipfile markers in the install phase when using ``--skip-lock``.  `#5920 <https://github.com/pypa/pipenv/issues/5920>`_
- Fallback to default vcs ref when no ref is supplied.
  More proactively determine package name from the pip line where possible, fallback to the existing file scanning logics when unable to determine name.  `#5921 <https://github.com/pypa/pipenv/issues/5921>`_


# 2023.9.1 (2023-09-01)

# Pipenv 2023.9.1 (2023-09-01)

## Features & Improvements

- Top level Pipfile sys_platform markers should be transitive; adds top level platform_machine entries that are also transitive.   Marker entries continue to operate the same as before.  [#5892](https://github.com/pypa/pipenv/issues/5892)

## Bug Fixes

- Apply patch for install_search_all_sources = True functionality.  [#5895](https://github.com/pypa/pipenv/issues/5895)
- Relative paths improvements for editable installs.  [#5896](https://github.com/pypa/pipenv/issues/5896)
- Set log level in resolver to WARN when verbose is not passed.  [#5897](https://github.com/pypa/pipenv/issues/5897)
- Handle more variations in private index html to improve hash collection.  [#5898](https://github.com/pypa/pipenv/issues/5898)

# 2023.8.28 (2023-08-28)

## Bug Fixes

- Revert change that caused the credentials in source url issue.  [#5878](https://github.com/pypa/pipenv/issues/5878)
- Do not treat named requirements as file installs just becacuse a match path exists; better handling of editable keyword for local file installs.
  Handle additional edge cases in the setup.py ast parser logic for trying to determine local install package name.  [#5885](https://github.com/pypa/pipenv/issues/5885)

# 2023.8.26 (2023-08-26)

## Bug Fixes

- Additional property caching to avoid duplication of sources in the resolver.  [#5863](https://github.com/pypa/pipenv/issues/5863)
- Fix recent regressions with local/editable file installs.  [#5870](https://github.com/pypa/pipenv/issues/5870)
- Fixes the vcs subdirectory fragments regression; fixes sys_platform markers regression.  [#5871](https://github.com/pypa/pipenv/issues/5871)
- Fix regression that caused printing non-printable ascii characters  when help was called.  [#5872](https://github.com/pypa/pipenv/issues/5872)

# 2023.8.25 (2023-08-25)

## Bug Fixes

- Fix regression of hash collection when downloading package from private indexes when the hash is not found in the index href url fragment.  [#5866](https://github.com/pypa/pipenv/issues/5866)

# 2023.8.23 (2023-08-22)

## Bug Fixes

- More gracefully handle @ symbols in vcs URLs to address recent regression with vcs URLs.  [#5849](https://github.com/pypa/pipenv/issues/5849)

# 2023.8.22 (2023-08-22)

## Bug Fixes

- Fix regression with `ssh://` vcs URLs introduced in `2023.8.21` whereby ssh vcs URLs are expected to have at least one `@` symbol.  [#5846](https://github.com/pypa/pipenv/issues/5846)

# 2023.8.21 (2023-08-21)

## Bug Fixes

- Add back some relevant caching to increase performance after the major refactor released with `2023.8.19`  [#5841](https://github.com/pypa/pipenv/issues/5841)
- Fix some edge cases around vcs dependencies without a ref, and older Pipfile/lockfile formats.  [#5843](https://github.com/pypa/pipenv/issues/5843)

## Vendored Libraries

- Remove unused command line interface for vendored packages.  [#5840](https://github.com/pypa/pipenv/issues/5840)

# 2023.8.20 (2023-08-20)

## Bug Fixes

- Fix the expected output of the `version` command.  [#5838](https://github.com/pypa/pipenv/issues/5838)

# 2023.8.19 (2023-08-19)

## Features & Improvements

- The `--categories` option now works with requirements.txt file.  [#5722](https://github.com/pypa/pipenv/issues/5722)

## Bug Fixes

- Drop requirementslib for managing pip lines and InstallRequirements, bring remaining requirementslib functionality into pipenv.
  Fixes numerous reports about extras installs with vcs and file installs; format pip lines correctly to not generate deprecation warnings.  [#5793](https://github.com/pypa/pipenv/issues/5793)

## Vendored Libraries

- Update pip 23.2 -> 23.2.1  [#5822](https://github.com/pypa/pipenv/issues/5822)

## Improved Documentation

- Added documentation on how to move or rename a project directory  [#5129](https://github.com/pypa/pipenv/issues/5129)

## Removals and Deprecations

- The `--skip-lock` flag which was deprecated, has now been removed to unblock modernizing the pipenv resolver code.  [#5805](https://github.com/pypa/pipenv/issues/5805)

# 2023.7.23 (2023-07-23)

## Features & Improvements

- Upgrades `pip==23.2` which includes everything from the pip changelog.  Drops the "install_compatatability_finder" pip internals patch.  [#5808](https://github.com/pypa/pipenv/issues/5808)

## Bug Fixes

- Fix issue parsing some Pipfiles with separate packages.\<pkg> sections (tomlkit OutOfOrderTableProxy)  [#5794](https://github.com/pypa/pipenv/issues/5794)
- Fix all ruff linter warnings  [#5807](https://github.com/pypa/pipenv/issues/5807)
- Restore running Resolver in sub-process using the project python by default; maintains ability to run directly by setting `PIPENV_RESOLVER_PARENT_PYTHON` environment variable to 1 (useful for internal debugging).  [#5809](https://github.com/pypa/pipenv/issues/5809)
- Fix error when a Windows path begins with a '' with `pythonfinder==2.0.5`.  [#5812](https://github.com/pypa/pipenv/issues/5812)

## Vendored Libraries

- Remove usage of click.secho in some modules.  [#5804](https://github.com/pypa/pipenv/issues/5804)

2023.7.11 (2023-07-11)

## Bug Fixes

- Invoke the resolver in the same process as pipenv rather than utilizing subprocess.  [#5787](https://github.com/pypa/pipenv/issues/5787)
- Fix regression markers being included as None/null in requirements command.  [#5788](https://github.com/pypa/pipenv/issues/5788)

# 2023.7.9 (2023-07-09)

## Bug Fixes

- Drop the --keep-outdated flag and --selective-upgrade flags that have been deprecated in favor of update/upgrade commands.  [#5730](https://github.com/pypa/pipenv/issues/5730)
- Fix regressions in the `requirements` command related to standard index extras and handling of local file requirements.  [#5784](https://github.com/pypa/pipenv/issues/5784)

# 2023.7.4 (2023-07-04)

## Bug Fixes

- Fixes regression on Pipfile requirements syntax. Ensure default operator is provided to requirement lib to avoid crash.  [#5765](https://github.com/pypa/pipenv/issues/5765)
- Ensure hashes included in a generated requirements file are after any markers.  [#5777](https://github.com/pypa/pipenv/issues/5777)

# 2023.7.3 (2023-07-02)

## Bug Fixes

- Fix regression with `--system` flag usage.  [#5773](https://github.com/pypa/pipenv/issues/5773)

# 2023.7.1 (2023-07-01)

## Bug Fixes

- Patch `_get_requests_session` method to consider `PIP_CLIENT_CERT` value when present.  [#5746](https://github.com/pypa/pipenv/issues/5746)
- Fix regression in `requirements` command that was causing package installs after upgrade to `requirementslib==3.0.0`.  [#5755](https://github.com/pypa/pipenv/issues/5755)
- Fix `error: invalid command 'egg_info'` edge case with requirementslib 3.0.0.  It exposed pipenv resolver sometimes was using a different python than expected.  [#5760](https://github.com/pypa/pipenv/issues/5760)
- Fix issue in requirementslib 3.0.0 where dependencies defined in pyproject.toml were not being included in the lock file.  [#5766](https://github.com/pypa/pipenv/issues/5766)

## Removals and Deprecations

- Bump dparse to 0.6.3  [#5750](https://github.com/pypa/pipenv/issues/5750)

# 2023.6.26 (2023-06-26)

## Improved Documentation

- Add missing environment variable descriptions back to documentation  [#missing_env_var_desc](https://github.com/pypa/pipenv/issues/missing_env_var_desc)

# 2023.6.18 (2023-06-18)

## Bug Fixes

- Fixes resolver to only consider the default index for packages when a secondary index is not specified.  This brings the code into alignment with stated assumptions about index restricted packages behavior of `pipenv`.  [#5737](https://github.com/pypa/pipenv/issues/5737)

## Removals and Deprecations

- Deprecation of `--skip-lock` flag as it bypasses the security benefits of pipenv.  Plus it lacks proper deterministic support of installation from multiple package indexes.  [#5737](https://github.com/pypa/pipenv/issues/5737)

# 2023.6.12 (2023-06-11)

## Bug Fixes

- Remove the `sys.path` modifications and as a result fixes keyring support.  [#5719](https://github.com/pypa/pipenv/issues/5719)

# 2023.6.11 (2023-06-11)

## Vendored Libraries

- Upgrades to `pipdeptree==2.8.0` which fixes edge cases of the `pipenv graph` command.  [#5720](https://github.com/pypa/pipenv/issues/5720)

# 2023.6.2 (2023-06-02)

## Features & Improvements

- Resolver performance: package sources following PEP 503 will leverage package hashes from the URL fragment, without downloading the package.  [#5701](https://github.com/pypa/pipenv/issues/5701)

## Bug Fixes

- Improve regex for python versions to handle hidden paths; handle relative paths to python better as well.  [#4588](https://github.com/pypa/pipenv/issues/4588)
- Update `pythonfinder==2.0.4` with fix for "RecursionError: maximum recursion depth exceeded".  [#5709](https://github.com/pypa/pipenv/issues/5709)

## Vendored Libraries

- Drop old vendored toml library. Use stdlib tomllib or tomli instead.  [#5678](https://github.com/pypa/pipenv/issues/5678)
- Drop vendored library cerberus. This isn't actually used by pipenv.  [#5699](https://github.com/pypa/pipenv/issues/5699)

# 2023.5.19 (2023-05-19)

## Bug Fixes

- Consider `--index` argument in `update` and `upgrade` commands.  [#5692](https://github.com/pypa/pipenv/issues/5692)

## Vendored Libraries

- Upgrade `pythonfinder==2.0.0` which also brings in `pydantic==1.10.7`.  [#5677](https://github.com/pypa/pipenv/issues/5677)

# 2023.4.29 (2023-04-29)

## Vendored Libraries

- Vendor in `pip==23.1.2` latest.  [#5671](https://github.com/pypa/pipenv/issues/5671)
- Vendor in `requirementslib==2.3.0` which drops usage of `vistir`.  [#5672](https://github.com/pypa/pipenv/issues/5672)

# 2023.4.20 (2023-04-20)

## Features & Improvements

- Checks environment variable `PIP_TRUSTED_HOSTS` when evaluating an
  index specified at the command line when adding to `Pipfile`.

  For example, this command line

  ```
  PIP_TRUSTED_HOSTS=internal.mycompany.com pipenv install pypkg --index=https://internal.mycompany.com/pypi/simple
  ```

  will add the following to the `Pipfile`:

  ```
  [[source]]
  url = 'https://internal.mycompany.com/pypi/simple'
  verify_ssl = false
  name = 'Internalmycompany'

  [packages]
  pypkg = {version="*", index="Internalmycompany"}
  ```

  This allows users with private indexes to add them to `Pipfile`
  initially from command line with correct permissions using environment
  variable `PIP_TRUSTED_HOSTS`.  [#5572](https://github.com/pypa/pipenv/issues/5572)

- Vendor in the updates, upgrades and fixes provided by `pip==23.1`.  [#5655](https://github.com/pypa/pipenv/issues/5655)

- Replace flake8 and isort with [ruff](https://beta.ruff.rs).  [#ruff](https://github.com/pypa/pipenv/issues/ruff)

## Bug Fixes

- Fix regression with `--skip-lock` option with `install` command.  [#5653](https://github.com/pypa/pipenv/issues/5653)

## Vendored Libraries

- Vendor in latest `python-dotenv==1.0.0`  [#5656](https://github.com/pypa/pipenv/issues/5656)
- Vendor in latest available dependencies:  `attrs==23.1.0` `click-didyoumean==0.3.0` `click==8.1.3` `markupsafe==2.1.2` `pipdeptree==2.7.0` `shellingham==1.5.0.post1` `tomlkit==0.11.7`  [#5657](https://github.com/pypa/pipenv/issues/5657)
- Vendor in latest `requirementslib==2.2.5` which includes updates for pip 23.1  [#5659](https://github.com/pypa/pipenv/issues/5659)

## Improved Documentation

- Made documentation clear about tilde-equals operator for package versions.  [#5594](https://github.com/pypa/pipenv/issues/5594)

# 2023.3.20 (2023-03-19)

No significant changes.

# 2023.3.18 (2023-03-19)

## Bug Fixes

- Fix import error in virtualenv utility for creating new environments caused by `2023.3.18` release.  [#5636](https://github.com/pypa/pipenv/issues/5636)

# 2023.3.18 (2023-03-18)

## Features & Improvements

- Provide a more powerful solution than `--keep-outdated` and `--selective-upgrade` which are deprecated for removal.
  Introducing the `pipenv upgrade` command which takes the same package specifiers as `pipenv install` and
  updates the `Pipfile` and `Pipfile.lock` with a valid lock resolution that only effects the specified packages and their dependencies.
  Additionally, the `pipenv update` command has been updated to use the `pipenv upgrade` routine when packages are provided, which will install sync the new lock file as well.  [#5617](https://github.com/pypa/pipenv/issues/5617)

## Vendored Libraries

- Bump vistir to 0.8.0, requirementslib to 2.2.4.  [#5635](https://github.com/pypa/pipenv/issues/5635)

# 2023.2.18 (2023-02-18)

## Features & Improvements

- `pipenv` now reads the system `pip.conf` or `pip.ini` file in order to determine pre-defined indexes to use for package resolution and installation.  [#5297](https://github.com/pypa/pipenv/issues/5297)
- Behavior change for `pipenv check` now checks the default packages group of the lockfile.
  Specifying `--categories` to override which categories to check against.
  Pass `--use-installed` to get the prior behavior of checking the packages actually installed into the environment.  [#5600](https://github.com/pypa/pipenv/issues/5600)

## Bug Fixes

- Fix regression with detection of `CI` env variable being set to something other than a truthy value.  [#5554](https://github.com/pypa/pipenv/issues/5554)
- Fix `--categories` argument inconsistency between requirements command and install/sync by allowing comma separated values or spaces.  [#5570](https://github.com/pypa/pipenv/issues/5570)
- Use Nushell overlays when running `pipenv shell`.  [#5603](https://github.com/pypa/pipenv/issues/5603)

## Vendored Libraries

- Vendor in the `pip==23.0` release.  [#5586](https://github.com/pypa/pipenv/issues/5586)
- Vendor in `pip==23.0.1` minor pt release.  Updates `pythonfinder==1.3.2`.  [#5614](https://github.com/pypa/pipenv/issues/5614)

## Improved Documentation

- Make some improvements to the contributing guide.  [#5611](https://github.com/pypa/pipenv/issues/5611)

# 2023.2.4 (2023-02-04)

## Bug Fixes

- Fix overwriting of output in verbose mode  [#5530](https://github.com/pypa/pipenv/issues/5530)
- Fix for resolution error when direct url includes an extras.  [#5536](https://github.com/pypa/pipenv/issues/5536)

## Removals and Deprecations

- Remove pytest-pypi package since it's not used anymore  [#5556](https://github.com/pypa/pipenv/issues/5556)
- Remove deprecated --three flag from the CLI.  [#5576](https://github.com/pypa/pipenv/issues/5576)

# 2022.12.19 (2022-12-19)

## Bug Fixes

- Fix for `requirementslib` hanging during install of remote wheels files.  [#5546](https://github.com/pypa/pipenv/issues/5546)

# 2022.12.17 (2022-12-17)

## Bug Fixes

- virtualenv creation no longer uses `--creator=venv` by default; introduced two environment variables:
  `PIPENV_VIRTUALENV_CREATOR` -- May be specified to instruct virtualenv which `--creator=` to use.
  `PIPENV_VIRTUALENV_COPIES` -- When specified as truthy, instructs virtualenv to not use symlinks.  [#5477](https://github.com/pypa/pipenv/issues/5477)
- Fix regression where `path` is not propagated to the `Pipfile.lock`.  [#5479](https://github.com/pypa/pipenv/issues/5479)
- Solve issue where null markers were getting added to lock file when extras were provided.  [#5486](https://github.com/pypa/pipenv/issues/5486)
- Fix: `update --outdated` raises NonExistentKey with outdated dev packages  [#5540](https://github.com/pypa/pipenv/issues/5540)

## Vendored Libraries

- Vendor in `pip==22.3.1` which is currently the latest version of `pip`.  [#5520](https://github.com/pypa/pipenv/issues/5520)
- - Bump version of requirementslib to 2.2.1
  - Bump version of vistir to 0.7.5
  - Bump version of colorama to 0.4.6  [#5522](https://github.com/pypa/pipenv/issues/5522)
- Bump plette version to 0.4.4  [#5539](https://github.com/pypa/pipenv/issues/5539)

# 2022.11.30 (2022-11-30)

## Bug Fixes

- Fix regression: pipenv does not sync indexes to lockfile.  [#5508](https://github.com/pypa/pipenv/issues/5508)

# 2022.11.25 (2022-11-24)

## Bug Fixes

- Solving issue where `pipenv check` command has been broken in the published wheel distribution.  [#5493](https://github.com/pypa/pipenv/issues/5493)

# 2022.11.24 (2022-11-24)

## Bug Fixes

- Stop building universal wheels since Python 2 is no longer supported.  [#5496](https://github.com/pypa/pipenv/issues/5496)

# 2022.11.23 (2022-11-23)

## Features & Improvements

- Find nushell activate scripts.  [#5470](https://github.com/pypa/pipenv/issues/5470)

## Vendored Libraries

- - Drop unused code from cerberus
  - Drop unused module wheel  [#5467](https://github.com/pypa/pipenv/issues/5467)
- - Replace yaspin spinner with rich spinner.
  - Bump vistir version to 0.7.4  [#5468](https://github.com/pypa/pipenv/issues/5468)
- Bump version of requirementslib to 2.2.0
  Drop yaspin which is no longer used.
  Bump vistir to version 0.7.4
  Remove parse.
  Remove termcolor.
  Remove idna.  [#5481](https://github.com/pypa/pipenv/issues/5481)

# 2022.11.11 (2022-11-11)

## Bug Fixes

- Fix regression of lock generation that caused the keep-outdated behavior to be default.  [#5456](https://github.com/pypa/pipenv/issues/5456)

# 2022.11.5 (2022-11-05)

## Bug Fixes

- Rollback the change in version of `colorama` due to regressions in core functionality.  [#5459](https://github.com/pypa/pipenv/issues/5459)

# 2022.11.4 (2022-11-04)

## Features & Improvements

- Allow pipenv settings to be explicitly disabled more easily by assigning to the environment variable a falsy value.  [#5451](https://github.com/pypa/pipenv/issues/5451)

## Bug Fixes

- Provide an install iteration per index when `install_search_all_sources` is `false` (default behavior).
  This fixes regression where install phase was using unexpected index after updating `pip==22.3`  [#5444](https://github.com/pypa/pipenv/issues/5444)

## Vendored Libraries

- Drop tomli, which is not used anymore.
  Bump attrs version see #5449.
  Drop distlib, colorama and platformdirs - use the ones from pip.\_vendor.  [#5450](https://github.com/pypa/pipenv/issues/5450)

# 2022.10.25 (2022-10-25)

## Features & Improvements

- Add support to export requirements file for a specified set of categories.  [#5431](https://github.com/pypa/pipenv/issues/5431)

## Vendored Libraries

- Remove appdirs.py in favor of platformdirs.  [#5420](https://github.com/pypa/pipenv/issues/5420)

## Removals and Deprecations

- Remove usage of vistir.cmdparse in favor of pipenv.cmdparse  [#5419](https://github.com/pypa/pipenv/issues/5419)

# 2022.10.12 (2022-10-12)

## Improved Documentation

- Update pipenv docs for with example for callabale package functions in Pipfile scripts  [#5396](https://github.com/pypa/pipenv/issues/5396)

# 2022.10.11 (2022-10-11)

## Bug Fixes

- Revert decision to change the default isolation level because it caused problems with existing workflows; solution is to recommend users that have issues requiring pre-requisites to pass --extra-pip-args="--no-build-isolation" in their install or sync commands.  [#5399](https://github.com/pypa/pipenv/issues/5399)

# 2022.10.10 (2022-10-10)

## Features & Improvements

- Add ability for callable scripts in Pipfile under \[scripts\]. Callables can now be added like: `<pathed.module>:<func>` and can also take arguments. For example: `func = {call = "package.module:func('arg1', 'arg2')"}` then this can be activated in the shell with `pipenv run func`  [#5294](https://github.com/pypa/pipenv/issues/5294)

## Bug Fixes

- Fixes regression from `2022.10.9` where `Pipfile` with `pipenv` section began generating new hash,
  and also fix regression where lock phase did not update the hash value.  [#5394](https://github.com/pypa/pipenv/issues/5394)

# 2022.10.9 (2022-10-09)

## Behavior Changes

- New pipfiles show python_full_version under \[requires\] if specified. Previously creating a new pipenv project would only specify in the Pipfile the major and minor version, i.e. "python_version = 3.7". Now if you create a new project with a fully named python version it will record both in the Pipfile. So: "python_version = 3.7" and "python_full_version = 3.7.2"  [#5345](https://github.com/pypa/pipenv/issues/5345)

## Relates to dev process changes

- Silence majority of pytest.mark warnings by registering custom marks. Can view a list of custom marks by running `pipenv run pytest --markers`

# 2022.10.4 (2022-10-04)

## Bug Fixes

- Use `--creator=venv` when creating virtual environments to avoid issue with sysconfig `posix_prefix` on some systems.  [#5075](https://github.com/pypa/pipenv/issues/5075)
- Prefer to use the lockfile sources if available during the install phase.  [#5380](https://github.com/pypa/pipenv/issues/5380)

## Vendored Libraries

- Drop vendored six - we no longer depend on this library, as we migrated from pipfile to plette.  [#5187](https://github.com/pypa/pipenv/issues/5187)

# 2022.9.24 (2022-09-24)

## Bug Fixes

- Update `requirementslib==2.0.3` to always evaluate the requirement markers fresh (without lru_cache) to fix marker determinism issue.  [#4660](https://github.com/pypa/pipenv/issues/4660)

# 2022.9.21 (2022-09-21)

## Bug Fixes

- Fix regression to `install --skip-lock` with update to `plette`.  [#5368](https://github.com/pypa/pipenv/issues/5368)

# 2022.9.20 (2022-09-20)

## Behavior Changes

- Remove usage of pipfile module in favour of Plette.
  pipfile is not actively maintained anymore. Plette is actively maintained,
  and has stricter checking of the Pipefile and Pipefile.lock. As a result,
  Pipefile with unnamed package indices will fail to lock. If a Pipefile
  was hand crafeted, and the source is anonymous an error will be thrown.
  The solution is simple, add a name to your index, e.g, replace:

  ```
  [[source]]
  url = "https://pypi.acme.com/simple"
  verify_ssl = true
  ```

  With:

  ```
  [[source]]
  url = "https://pypi.acme.com/simple"
  verify_ssl = true
  name = acmes_private_index  `#5339 <https://github.com/pypa/pipenv/issues/5339>`_
  ```

## Bug Fixes

- Modernize `pipenv` path patch with `importlib.util` to eliminate import of `pkg_resources`  [#5349](https://github.com/pypa/pipenv/issues/5349)

## Vendored Libraries

- Remove iso8601 from vendored packages since it was not used.  [#5346](https://github.com/pypa/pipenv/issues/5346)

# 2022.9.8 (2022-09-08)

## Features & Improvements

- It is now possible to supply additional arguments to `pip` install by supplying `--extra-pip-args="<arg1> <arg2>"`
  See the updated documentation `Supplying additional arguments to pip` for more details.  [#5283](https://github.com/pypa/pipenv/issues/5283)

## Bug Fixes

- Make editable detection better because not everyone specifies editable entry in the Pipfile for local editable installs.  [#4784](https://github.com/pypa/pipenv/issues/4784)
- Add error handling for when the installed package setup.py does not contain valid markers.  [#5329](https://github.com/pypa/pipenv/issues/5329)
- Load the dot env earlier so that `PIPENV_CUSTOM_VENV_NAME` is more useful across projects.  [#5334](https://github.com/pypa/pipenv/issues/5334)

## Vendored Libraries

- Bump version of shellingham to support nushell.  [#5336](https://github.com/pypa/pipenv/issues/5336)
- Bump plette to version v0.3.0  [#5337](https://github.com/pypa/pipenv/issues/5337)
- Bump version of pipdeptree  [#5343](https://github.com/pypa/pipenv/issues/5343)

## Removals and Deprecations

- Add deprecation warning to the --three flag. Pipenv now uses python3 by default.  [#5328](https://github.com/pypa/pipenv/issues/5328)

## Relates to dev process changes

- Convert the test runner to use `pypiserver` as a standalone process for all tests that referencce internal `pypi` artifacts.
  General refactoring of some test cases to create more variety in packages selected--preferring lighter weight packages--in existing test cases.

# 2022.9.4 (2022-09-04)

## Bug Fixes

- Fix the issue from `2022.9.2` where tarball URL packages were being skipped on batch_install.  [#5306](https://github.com/pypa/pipenv/issues/5306)

# 2022.9.2 (2022-09-02)

## Bug Fixes

- Fix issue where unnamed constraints were provided but which are not allowed by `pip` resolver.  [#5273](https://github.com/pypa/pipenv/issues/5273)

# 2022.8.31 (2022-08-31)

## Features & Improvements

- Performance optimization to `batch_install` results in a faster and less CPU intensive `pipenv sync` or `pipenv install`  experience.  [#5301](https://github.com/pypa/pipenv/issues/5301)

## Bug Fixes

- `pipenv` now uses a  `NamedTemporaryFile` for rsolver constraints and drops internal env var `PIPENV_PACKAGES`.  [#4925](https://github.com/pypa/pipenv/issues/4925)

## Removals and Deprecations

- Remove no longer used method `which_pip`.  [#5314](https://github.com/pypa/pipenv/issues/5314)
- Drop progress bar file due to recent performance optimization to combine `batch_install` requirements in at most two invocations of `pip install`.
  To see progress of install pass `--verbose` flag and `pip` progress will be output in realtime.  [#5315](https://github.com/pypa/pipenv/issues/5315)

# 2022.8.30 (2022-08-30)

## Bug Fixes

- Fix an issue when using `pipenv install --system` on systems that having the `python` executable pointing to Python 2 and a Python 3 executable being `python3`.  [#5296](https://github.com/pypa/pipenv/issues/5296)
- Sorting `constraints` before resolving, which fixes `pipenv lock` generates nondeterminism environment markers.  [#5299](https://github.com/pypa/pipenv/issues/5299)
- Fix #5273, use our own method for checking if a package is a valid constraint.  [#5309](https://github.com/pypa/pipenv/issues/5309)

## Vendored Libraries

- Vendor in `requirementslib==2.0.1` which fixes issue with local install not marked editable, and vendor in `vistir==0.6.1` which drops python2 support.
  Drops `orderedmultidict` from vendoring.  [#5308](https://github.com/pypa/pipenv/issues/5308)

# 2022.8.24 (2022-08-24)

## Bug Fixes

- Remove eager and unnecessary importing of `setuptools` and `pkg_resources` to avoid conflict upgrading `setuptools`.
  Roll back `sysconfig` patch of `pip` because it was problematic for some `--system` commands.  [#5228](https://github.com/pypa/pipenv/issues/5228)

## Vendored Libraries

- Vendor in `requirementslib==2.0.0` and drop `pip-shims` entirely.  [#5228](https://github.com/pypa/pipenv/issues/5228)
- Vendor in `pythonfinder==1.3.1`  [#5292](https://github.com/pypa/pipenv/issues/5292)

# 2022.8.19 (2022-08-19)

## Bug Fixes

- Fix issue where resolver is provided with `install_requires` constraints from `setup.py` that depend on editable dependencies and could not resolve them.  [#5271](https://github.com/pypa/pipenv/issues/5271)
- Fix for `pipenv lock` fails for packages with extras as of `2022.8.13`.  [#5274](https://github.com/pypa/pipenv/issues/5274)
- Revert the exclusion of `BAD_PACKAGES` from `batch_install` in order for `pipenv` to install specific versions of `setuptools`.
  To prevent issue upgrading `setuptools` this patches `_USE_SYSCONFIG_DEFAULT` to use `sysconfig` for `3.7` and above whereas `pip` default behavior was `3.10` and above.  [#5275](https://github.com/pypa/pipenv/issues/5275)

# 2022.8.17 (2022-08-17)

## Bug Fixes

- Fix "The Python interpreter can't be found" error when running `pipenv install --system` with a python3 but no python.  [#5261](https://github.com/pypa/pipenv/issues/5261)
- Revise pip import patch to include only `pipenv` from site-packages and removed `--ignore-installed` argument from pip install in order to fix regressions with `--use-site-packages`.  [#5265](https://github.com/pypa/pipenv/issues/5265)

# 2022.8.15 (2022-08-15)

## Bug Fixes

- `pip_install` method was using a different way of finding the python executable than other `pipenv` commands, which caused an issue with skipping package installation if it was already installed in site-packages.  [#5254](https://github.com/pypa/pipenv/issues/5254)

# 2022.8.14 (2022-08-14)

## Bug Fixes

- Removed `packaging` library from `BAD_PACKAGES` constant to allow it to be installed, which fixes regression from `pipenv==2022.8.13`.  [#5247](https://github.com/pypa/pipenv/issues/5247)

# 2022.8.13 (2022-08-13)

## Bug Fixes

- If environment variable `CI` or `TF_BUILD` is set but does not evaluate to `False` it is now treated as `True`.  [#5128](https://github.com/pypa/pipenv/issues/5128)
- Fix auto-complete crashing on 'install' and 'uninstall' keywords  [#5214](https://github.com/pypa/pipenv/issues/5214)
- Address remaining `pipenv` commands that were still referencing the user or system installed `pip` to use the vendored `pip` internal to `pipenv`.  [#5229](https://github.com/pypa/pipenv/issues/5229)
- Use `packages` as constraints when locking `dev-packages` in Pipfile.
  Use `packages` as constraints when installing new `dev-packages`.  [#5234](https://github.com/pypa/pipenv/issues/5234)

## Vendored Libraries

- Vendor in minor `pip` update `22.2.2`  [#5230](https://github.com/pypa/pipenv/issues/5230)

## Improved Documentation

- Add documentation for environment variables the configure pipenv.  [#5235](https://github.com/pypa/pipenv/issues/5235)

## Removals and Deprecations

- The deprecated way of generating requirements `install -r` or `lock -r` has been removed in favor of the `pipenv requirements` command.  [#5200](https://github.com/pypa/pipenv/issues/5200)

# 2022.8.5 (2022-08-05)

## Features & Improvements

- support PIPENV_CUSTOM_VENV_NAME to be the venv name if specified, update relevant docs.  [#4974](https://github.com/pypa/pipenv/issues/4974)

## Bug Fixes

- Remove usages of `pip_shims` from the non vendored `pipenv` code, but retain initialization for `requirementslib` still has usages.  [#5204](https://github.com/pypa/pipenv/issues/5204)
- Fix case sensitivity of color name `red` in exception when getting hashes from pypi in `_get_hashes_from_pypi`.  [#5206](https://github.com/pypa/pipenv/issues/5206)
- Write output from `subprocess_run` directly to `stdout` instead of creating temporary file.
  Remove deprecated `distutils.sysconfig`, use `sysconfig`.  [#5210](https://github.com/pypa/pipenv/issues/5210)

## Vendored Libraries

- - Rename patched `notpip` to `pip` in order to be clear that its a patched version of pip.
  - Remove the part of \_post_pip_import.patch that overrode the standalone pip to be the user installed pip, now we fully rely on our vendored and patched `pip`, even for all types of installs.
  - Vendor in the next newest version of `pip==22.2`
  - Modify patch for `pipdeptree` to not use `pip-shims`  [#5188](https://github.com/pypa/pipenv/issues/5188)
  - Remove vendored `urllib3` in favor of using it from vendored version in `pip._vendor`  [#5215](https://github.com/pypa/pipenv/issues/5215)

## Removals and Deprecations

- Remove tests that have been for a while been marked skipped and are no longer relevant.  [#5165](https://github.com/pypa/pipenv/issues/5165)

# 2022.7.24 (2022-07-24)

## Bug Fixes

- Re-enabled three installs tests again on the Windows CI as recent refactor work has fixed them.  [#5064](https://github.com/pypa/pipenv/issues/5064)
- Support ANSI `NO_COLOR` environment variable and deprecate `PIPENV_COLORBLIND` variable, which will be removed after this release.  [#5158](https://github.com/pypa/pipenv/issues/5158)
- Fixed edge case where a non-editable file, url or vcs would overwrite the value `no_deps` for all other requirements in the loop causing a retry condition.  [#5164](https://github.com/pypa/pipenv/issues/5164)
- Vendor in latest `requirementslib` for fix to lock when using editable VCS module with specific `@` git reference.  [#5179](https://github.com/pypa/pipenv/issues/5179)

## Vendored Libraries

- Remove crayons and replace with click.secho and click.styles per <https://github.com/pypa/pipenv/issues/3741>  [#3741](https://github.com/pypa/pipenv/issues/3741)
- Vendor in latest version of `pip==22.1.2` which upgrades `pipenv` from `pip==22.0.4`.
  Vendor in latest version of `requirementslib==1.6.7` which includes a fix for tracebacks on encountering Annotated variables.
  Vendor in latest version of `pip-shims==0.7.3` such that imports could be rewritten to utilize `packaging` from vendor'd `pip`.
  Drop the `packaging` requirement from the `vendor` directory in `pipenv`.  [#5147](https://github.com/pypa/pipenv/issues/5147)
- Remove unused vendored dependency `normailze-charset`.  [#5161](https://github.com/pypa/pipenv/issues/5161)
- Remove obsolete package `funcsigs`.  [#5168](https://github.com/pypa/pipenv/issues/5168)
- Bump vendored dependency `pyparsing==3.0.9`.  [#5170](https://github.com/pypa/pipenv/issues/5170)

# 2022.7.4 (2022-07-04)

## Behavior Changes

- Adjust `pipenv requirements` to add markers and add an `--exclude-markers` option to allow the exclusion of markers.  [#5092](https://github.com/pypa/pipenv/issues/5092)

## Bug Fixes

- Stopped expanding environment variables when using `pipenv requirements`  [#5134](https://github.com/pypa/pipenv/issues/5134)

## Vendored Libraries

- Depend on `requests` and `certifi` from vendored `pip` and remove them as explicit vendor dependencies.  [#5000](https://github.com/pypa/pipenv/issues/5000)
- Vendor in the latest version of `requirementslib==1.6.5` which includes bug fixes for beta python versions, projects with an at sign (@) in the path, and a `setuptools` deprecation warning.  [#5132](https://github.com/pypa/pipenv/issues/5132)

## Relates to dev process changes

- Switch from using type comments to type annotations.

# 2022.5.3.dev0 (2022-06-07)

## Bug Fixes

- Adjust pipenv to work with the newly added `venv` install scheme in Python.
  First check if `venv` is among the available install schemes, and use it if it is. Otherwise fall back to the `nt` or `posix_prefix` install schemes as before. This should produce no change for environments where the install schemes were not redefined.  [#5096](https://github.com/pypa/pipenv/issues/5096)

# 2022.5.2 (2022-05-02)

## Bug Fixes

- Fixes issue of `pipenv lock -r` command printing to stdout instead of stderr.  [#5091](https://github.com/pypa/pipenv/issues/5091)

# 2022.4.30 (2022-04-30)

## Bug Fixes

- Fixes issue of `requirements` command problem by modifying to print `-e` and path of the editable package.  [#5070](https://github.com/pypa/pipenv/issues/5070)
- Revert specifier of `setuptools` requirement in `setup.py` back to what it was in order to fix `FileNotFoundError: [Errno 2]` issue report.  [#5075](https://github.com/pypa/pipenv/issues/5075)
- Fixes issue of requirements command where git requirements cause the command to fail, solved by using existing convert_deps_to_pip function.  [#5076](https://github.com/pypa/pipenv/issues/5076)

## Vendored Libraries

- Vendor in `requirementslib==1.6.4` to Fix `SetuptoolsDeprecationWarning` `setuptools.config.read_configuration` became deprecated.  [#5081](https://github.com/pypa/pipenv/issues/5081)

## Removals and Deprecations

- Remove more usage of misc functions of vistir. Many of this function are available in the STL or in another dependency of pipenv.  [#5078](https://github.com/pypa/pipenv/issues/5078)

# 2022.4.21 (2022-04-21)

## Removals and Deprecations

- Updated setup.py to remove support for python 3.6 from built `pipenv` packages' Metadata.  [#5065](https://github.com/pypa/pipenv/issues/5065)

# 2022.4.20 (2022-04-20)

## Features & Improvements

- Added new Pipenv option `install_search_all_sources` that allows installation of packages from an
  existing `Pipfile.lock` to search all defined indexes for the constrained package version and hash signatures.  [#5041](https://github.com/pypa/pipenv/issues/5041)

## Bug Fixes

- allow the user to disable the `no_input` flag, so the use of e.g Google Artifact Registry is possible.  [#4706](https://github.com/pypa/pipenv/issues/4706)
- Fixes case where packages could fail to install and the exit code was successful.  [#5031](https://github.com/pypa/pipenv/issues/5031)

## Vendored Libraries

- Updated vendor version of `pip` from `21.2.2` to `22.0.4` which fixes a number of bugs including
  several reports of pipenv locking for an infinite amount of time when using certain package constraints.
  This also drops support for python 3.6 as it is EOL and support was removed in pip 22.x  [#4995](https://github.com/pypa/pipenv/issues/4995)

## Removals and Deprecations

- Removed the vendor dependency `more-itertools` as it was originally added for `zipp`, which since stopped using it.  [#5044](https://github.com/pypa/pipenv/issues/5044)
- Removed all usages of `pipenv.vendor.vistir.compat.fs_str`, since this function was used for PY2-PY3 compatibility and is no longer needed.  [#5062](https://github.com/pypa/pipenv/issues/5062)

## Relates to dev process changes

- Added pytest-cov and basic configuration to the project for generating html testing coverage reports.
- Make all CI jobs run only after the lint stage. Also added a makefile target for vendoring the packages.

# 2022.4.8 (2022-04-08)

## Features & Improvements

- Implements a `pipenv requirements` command which generates a requirements.txt compatible output without locking.  [#4959](https://github.com/pypa/pipenv/issues/4959)
- Internal to pipenv, the utils.py was split into a utils module with unused code removed.  [#4992](https://github.com/pypa/pipenv/issues/4992)

## Bug Fixes

- Pipenv will now ignore `.venv` in the project when `PIPENV_VENV_IN_PROJECT` variable is False.
  Unset variable maintains the existing behavior of preferring to use the project's `.venv` should it exist.  [#2763](https://github.com/pypa/pipenv/issues/2763)
- Fix an edge case of hash collection in index restricted packages whereby the hashes for some packages would
  be missing from the `Pipfile.lock` following package index restrictions added in `pipenv==2022.3.23`.  [#5023](https://github.com/pypa/pipenv/issues/5023)

## Improved Documentation

- Pipenv CLI documentation generation has been fixed.  It had broke when `click` was vendored into the project in
  `2021.11.9` because by default `sphinx-click` could no longer determine the CLI inherited from click.  [#4778](https://github.com/pypa/pipenv/issues/4778)
- Improve documentation around extra indexes and index restricted packages.  [#5022](https://github.com/pypa/pipenv/issues/5022)

## Removals and Deprecations

- Removes the optional `install` argument `--extra-index-url` as it was not compatible with index restricted packages.
  Using the `--index` argument is the correct way to specify a package should be pulled from the non-default index.  [#5022](https://github.com/pypa/pipenv/issues/5022)

## Relates to dev process changes

- Added code linting using pre-commit-hooks, black, flake8, isort, pygrep-hooks, news-fragments and check-manifest.
  Very similar to pip's configuration; adds a towncrier new's type `process` for change to Development processes.

# 2022.3.28 (2022-03-27)

## Bug Fixes

- Environment variables were not being loaded when the `--quiet` flag was set  [#5010](https://github.com/pypa/pipenv/issues/5010)
- It would appear that `requirementslib` was not fully specifying the subdirectory to `build_pep517` and
  and when a new version of `setuptools` was released, the test `test_lock_nested_vcs_direct_url`
  broke indicating the Pipfile.lock no longer contained the extra dependencies that should have been resolved.
  This regression affected `pipenv>=2021.11.9` but has been fixed by a patch to `requirementslib`.  [#5019](https://github.com/pypa/pipenv/issues/5019)

## Vendored Libraries

- Vendor in pip==21.2.4 (from 21.2.2) in order to bring in requested bug fix for python3.6.  Note: support for 3.6 will be dropped in a subsequent release.  [#5008](https://github.com/pypa/pipenv/issues/5008)

# 2022.3.24 (2022-03-23)

## Features & Improvements

- It is now possible to silence the `Loading .env environment variables` message on `pipenv run`
  with the `--quiet` flag or the `PIPENV_QUIET` environment variable.  [#4027](https://github.com/pypa/pipenv/issues/4027)

## Bug Fixes

- Fixes issue with new index safety restriction, whereby an unnamed extra sources index
  caused and error to be thrown during install.  [#5002](https://github.com/pypa/pipenv/issues/5002)
- The text `Loading .env environment variables...` has been switched back to stderr as to not
  break requirements.txt generation.  Also it only prints now when a `.env` file is actually present.  [#5003](https://github.com/pypa/pipenv/issues/5003)

# 2022.3.23 (2022-03-22)

## Features & Improvements

- Use environment variable `PIPENV_SKIP_LOCK` to control the behaviour of lock skipping.  [#4797](https://github.com/pypa/pipenv/issues/4797)
- New CLI command `verify`, checks the Pipfile.lock is up-to-date  [#4893](https://github.com/pypa/pipenv/issues/4893)

## Behavior Changes

- Pattern expansion for arguments was disabled on Windows.  [#4935](https://github.com/pypa/pipenv/issues/4935)

## Bug Fixes

- Python versions on Windows can now be installed automatically through pyenv-win  [#4525](https://github.com/pypa/pipenv/issues/4525)
- Patched our vendored Pip to fix: Pipenv Lock (Or Install) Does Not Respect Index Specified For A Package.  [#4637](https://github.com/pypa/pipenv/issues/4637)
- If `PIP_TARGET` is set to environment variables,  Refer specified directory for calculate delta, instead default directory  [#4775](https://github.com/pypa/pipenv/issues/4775)
- Remove remaining mention of python2 and --two flag from codebase.  [#4938](https://github.com/pypa/pipenv/issues/4938)
- Use `CI` environment value, over mere existence of name  [#4944](https://github.com/pypa/pipenv/issues/4944)
- Environment variables from dot env files are now properly expanded when included in scripts.  [#4975](https://github.com/pypa/pipenv/issues/4975)

## Vendored Libraries

- Updated vendor version of `pythonfinder` from `1.2.9` to `1.2.10` which fixes a bug with WSL
  (Windows Subsystem for Linux) when a path can not be read and Permission Denied error is encountered.  [#4976](https://github.com/pypa/pipenv/issues/4976)

## Removals and Deprecations

- Removes long broken argument `--code` from `install` and `--unused` from `check`.
  Check command no longer takes in arguments to ignore.
  Removed the vendored dependencies:  `pipreqs` and `yarg`  [#4998](https://github.com/pypa/pipenv/issues/4998)

# 2022.1.8 (2022-01-08)

## Bug Fixes

- Remove the extra parentheses around the venv prompt.  [#4877](https://github.com/pypa/pipenv/issues/4877)
- Fix a bug of installation fails when extra index url is given.  [#4881](https://github.com/pypa/pipenv/issues/4881)
- Fix regression where lockfiles would only include the hashes for releases for the platform generating the lockfile  [#4885](https://github.com/pypa/pipenv/issues/4885)
- Fix the index parsing to reject illegal requirements.txt.  [#4899](https://github.com/pypa/pipenv/issues/4899)

# 2021.11.23 (2021-11-23)

## Bug Fixes

- Update `charset-normalizer` from `2.0.3` to `2.0.7`, this fixes an import error on Python 3.6.  [#4865](https://github.com/pypa/pipenv/issues/4865)
- Fix a bug of deleting a virtualenv that is not managed by Pipenv.  [#4867](https://github.com/pypa/pipenv/issues/4867)
- Fix a bug that source is not added to `Pipfile` when index url is given with `pipenv install`.  [#4873](https://github.com/pypa/pipenv/issues/4873)

# 2021.11.15 (2021-11-15)

## Bug Fixes

- Return an empty dict when `PIPENV_DONT_LOAD_ENV` is set.  [#4851](https://github.com/pypa/pipenv/issues/4851)
- Don't use `sys.executable` when inside an activated venv.  [#4852](https://github.com/pypa/pipenv/issues/4852)

## Vendored Libraries

- Drop the vendored `jinja2` dependency as it is not needed any more.  [#4858](https://github.com/pypa/pipenv/issues/4858)
- Update `click` from `8.0.1` to `8.0.3`, to fix a problem with bash completion.  [#4860](https://github.com/pypa/pipenv/issues/4860)
- Drop unused vendor `chardet`.  [#4862](https://github.com/pypa/pipenv/issues/4862)

## Improved Documentation

- Fix the documentation to reflect the fact that special characters must be percent-encoded in the URL.  [#4856](https://github.com/pypa/pipenv/issues/4856)

# 2021.11.9 (2021-11-09)

## Features & Improvements

- Replace `click-completion` with `click`'s own completion implementation.  [#4786](https://github.com/pypa/pipenv/issues/4786)

## Bug Fixes

- Fix a bug that `pipenv run` doesn't set environment variables correctly.  [#4831](https://github.com/pypa/pipenv/issues/4831)
- Fix a bug that certifi can't be loaded within `notpip`'s vendor library. This makes several objects of `pip` fail to be imported.  [#4833](https://github.com/pypa/pipenv/issues/4833)
- Fix a bug that `3.10.0` can be found be python finder.  [#4837](https://github.com/pypa/pipenv/issues/4837)

## Vendored Libraries

- Update `pythonfinder` from `1.2.8` to `1.2.9`.  [#4837](https://github.com/pypa/pipenv/issues/4837)

# 2021.11.5.post0 (2021-11-05)

## Bug Fixes

- Fix a regression that `pipenv shell` fails to start a subshell.  [#4828](https://github.com/pypa/pipenv/issues/4828)
- Fix a regression that `pip_shims` object isn't imported correctly.  [#4829](https://github.com/pypa/pipenv/issues/4829)

# 2021.11.5 (2021-11-05)

## Features & Improvements

- Avoid sharing states but create project objects on demand. So that most integration test cases are able to switch to a in-process execution method.  [#4757](https://github.com/pypa/pipenv/issues/4757)
- Shell-quote `pip` commands when logging.  [#4760](https://github.com/pypa/pipenv/issues/4760)

## Bug Fixes

- Ignore empty .venv in rood dir and create project name base virtual environment  [#4790](https://github.com/pypa/pipenv/issues/4790)

## Vendored Libraries

- Update vendored dependencies
  \- `attrs` from `20.3.0` to `21.2.0`
  \- `cerberus` from `1.3.2` to `1.3.4`
  \- `certifi` from `2020.11.8` to `2021.5.30`
  \- `chardet` from `3.0.4` to `4.0.0`
  \- `click` from `7.1.2` to `8.0.1`
  \- `distlib` from `0.3.1` to `0.3.2`
  \- `idna` from `2.10` to `3.2`
  \- `importlib-metadata` from `2.0.0` to `4.6.1`
  \- `importlib-resources` from `3.3.0` to `5.2.0`
  \- `jinja2` from `2.11.2` to `3.0.1`
  \- `markupsafe` from `1.1.1` to `2.0.1`
  \- `more-itertools` from `5.0.0` to `8.8.0`
  \- `packaging` from `20.8` to `21.0`
  \- `pep517` from `0.9.1` to `0.11.0`
  \- `pipdeptree` from `1.0.0` to `2.0.0`
  \- `ptyprocess` from `0.6.0` to `0.7.0`
  \- `python-dateutil` from `2.8.1` to `2.8.2`
  \- `python-dotenv` from `0.15.0` to `0.19.0`
  \- `pythonfinder` from `1.2.5` to `1.2.8`
  \- `requests` from `2.25.0` to `2.26.0`
  \- `shellingham` from `1.3.2` to `1.4.0`
  \- `six` from `1.15.0` to `1.16.0`
  \- `tomlkit` from `0.7.0` to `0.7.2`
  \- `urllib3` from `1.26.1` to `1.26.6`
  \- `zipp` from `1.2.0` to `3.5.0`

  Add new vendored dependencies
  \- `charset-normalizer 2.0.3`
  \- `termcolor 1.1.0`
  \- `tomli 1.1.0`
  \- `wheel 0.36.2`  [#4747](https://github.com/pypa/pipenv/issues/4747)

- Drop the dependencies for Python 2.7 compatibility purpose.  [#4751](https://github.com/pypa/pipenv/issues/4751)

- Switch the dependency resolver from `pip-tools` to `pip`.

  Update vendor libraries:
  \- Update `requirementslib` from `1.5.16` to `1.6.1`
  \- Update `pip-shims` from `0.5.6` to `0.6.0`
  \- New vendor `platformdirs 2.4.0`  [#4759](https://github.com/pypa/pipenv/issues/4759)

## Improved Documentation

- remove prefixes on install commands for easy copy/pasting  [#4792](https://github.com/pypa/pipenv/issues/4792)
- Officially drop support for Python 2.7 and Python 3.5.  [#4261](https://github.com/pypa/pipenv/issues/4261)

# 2021.5.29 (2021-05-29)

## Bug Fixes

- Fix a bug where passing --skip-lock when PIPFILE has no \[SOURCE\] section throws the error: "tomlkit.exceptions.NonExistentKey: 'Key "source" does not exist.'"  [#4141](https://github.com/pypa/pipenv/issues/4141)
- Fix bug where environment wouldn't activate in paths containing & and \$ symbols  [#4538](https://github.com/pypa/pipenv/issues/4538)
- Fix a bug that `importlib-metadata` from the project's dependencies conflicts with that from `pipenv`'s.  [#4549](https://github.com/pypa/pipenv/issues/4549)
- Fix a bug where `pep508checker.py` did not expect double-digit Python minor versions (e.g. "3.10").  [#4602](https://github.com/pypa/pipenv/issues/4602)
- Fix bug where environment wouldn't activate in paths containing () and \[\] symbols  [#4615](https://github.com/pypa/pipenv/issues/4615)
- Fix bug preventing use of pipenv lock --pre  [#4642](https://github.com/pypa/pipenv/issues/4642)

## Vendored Libraries

- Update `packaging` from `20.4` to `20.8`.  [#4591](https://github.com/pypa/pipenv/issues/4591)

# 2020.11.15 (2020-11-15)

## Features & Improvements

- Support expanding environment variables in requirement URLs.  [#3516](https://github.com/pypa/pipenv/issues/3516)
- Show warning message when a dependency is skipped in locking due to the mismatch of its markers.  [#4346](https://github.com/pypa/pipenv/issues/4346)

## Bug Fixes

- Fix a bug that executable scripts with leading backslash can't be executed via `pipenv run`.  [#4368](https://github.com/pypa/pipenv/issues/4368)
- Fix a bug that VCS dependencies always satisfy even if the ref has changed.  [#4387](https://github.com/pypa/pipenv/issues/4387)
- Restrict the acceptable hash type to SHA256 only.  [#4517](https://github.com/pypa/pipenv/issues/4517)
- Fix the output of `pipenv scripts` under Windows platform.  [#4523](https://github.com/pypa/pipenv/issues/4523)
- Fix a bug that the resolver takes wrong section to validate constraints.  [#4527](https://github.com/pypa/pipenv/issues/4527)

## Vendored Libraries

- Update vendored dependencies:
  : - `colorama` from `0.4.3` to `0.4.4`
    - `python-dotenv` from `0.10.3` to `0.15.0`
    - `first` from `2.0.1` to `2.0.2`
    - `iso8601` from `0.1.12` to `0.1.13`
    - `parse` from `1.15.0` to `1.18.0`
    - `pipdeptree` from `0.13.2` to `1.0.0`
    - `requests` from `2.23.0` to `2.25.0`
    - `idna` from `2.9` to `2.10`
    - `urllib3` from `1.25.9` to `1.26.1`
    - `certifi` from `2020.4.5.1` to `2020.11.8`
    - `requirementslib` from `1.5.15` to `1.5.16`
    - `attrs` from `19.3.0` to `20.3.0`
    - `distlib` from `0.3.0` to `0.3.1`
    - `packaging` from `20.3` to `20.4`
    - `six` from `1.14.0` to `1.15.0`
    - `semver` from `2.9.0` to `2.13.0`
    - `toml` from `0.10.1` to `0.10.2`
    - `cached-property` from `1.5.1` to `1.5.2`
    - `yaspin` from `0.14.3` to `1.2.0`
    - `resolvelib` from `0.3.0` to `0.5.2`
    - `pep517` from `0.8.2` to `0.9.1`
    - `zipp` from `0.6.0` to `1.2.0`
    - `importlib-metadata` from `1.6.0` to `2.0.0`
    - `importlib-resources` from `1.5.0` to `3.3.0`  [#4533](https://github.com/pypa/pipenv/issues/4533)

## Improved Documentation

- Fix suggested pyenv setup to avoid using shimmed interpreter  [#4534](https://github.com/pypa/pipenv/issues/4534)

# 2020.11.4 (2020-11-04)

## Features & Improvements

- Add a new command `pipenv scripts` to display shortcuts from Pipfile.  [#3686](https://github.com/pypa/pipenv/issues/3686)
- Retrieve package file hash from URL to accelerate the locking process.  [#3827](https://github.com/pypa/pipenv/issues/3827)
- Add the missing `--system` option to `pipenv sync`.  [#4441](https://github.com/pypa/pipenv/issues/4441)
- Add a new option pair `--header/--no-header` to `pipenv lock` command,
  which adds a header to the generated requirements.txt  [#4443](https://github.com/pypa/pipenv/issues/4443)

## Bug Fixes

- Fix a bug that percent encoded characters will be unquoted incorrectly in the file URL.  [#4089](https://github.com/pypa/pipenv/issues/4089)
- Fix a bug where setting PIPENV_PYTHON to file path breaks environment name  [#4225](https://github.com/pypa/pipenv/issues/4225)
- Fix a bug that paths are not normalized before comparison.  [#4330](https://github.com/pypa/pipenv/issues/4330)
- Handle Python major and minor versions correctly in Pipfile creation.  [#4379](https://github.com/pypa/pipenv/issues/4379)
- Fix a bug that non-wheel file requirements can be resolved successfully.  [#4386](https://github.com/pypa/pipenv/issues/4386)
- Fix a bug that `pexept.exceptions.TIMEOUT` is not caught correctly because of the wrong import path.  [#4424](https://github.com/pypa/pipenv/issues/4424)
- Fix a bug that compound TOML table is not parsed correctly.  [#4433](https://github.com/pypa/pipenv/issues/4433)
- Fix a bug that invalid Python paths from Windows registry break `pipenv install`.  [#4436](https://github.com/pypa/pipenv/issues/4436)
- Fix a bug that function calls in `setup.py` can't be parsed rightly.  [#4446](https://github.com/pypa/pipenv/issues/4446)
- Fix a bug that dist-info inside `venv` directory will be mistaken as the editable package's metadata.  [#4480](https://github.com/pypa/pipenv/issues/4480)
- Make the order of hashes in resolution result stable.  [#4513](https://github.com/pypa/pipenv/issues/4513)

## Vendored Libraries

- Update `tomlkit` from `0.5.11` to `0.7.0`.  [#4433](https://github.com/pypa/pipenv/issues/4433)
- Update `requirementslib` from `1.5.13` to `1.5.14`.  [#4480](https://github.com/pypa/pipenv/issues/4480)

## Improved Documentation

- Discourage homebrew installation in installation guides.  [#4013](https://github.com/pypa/pipenv/issues/4013)

# 2020.8.13 (2020-08-13)

## Bug Fixes

- Fixed behaviour of `pipenv uninstall --all-dev`.
  From now on it does not uninstall regular packages.  [#3722](https://github.com/pypa/pipenv/issues/3722)
- Fix a bug that incorrect Python path will be used when `--system` flag is on.  [#4315](https://github.com/pypa/pipenv/issues/4315)
- Fix falsely flagging a Homebrew installed Python as a virtual environment  [#4316](https://github.com/pypa/pipenv/issues/4316)
- Fix a bug that `pipenv uninstall` throws an exception that does not exist.  [#4321](https://github.com/pypa/pipenv/issues/4321)
- Fix a bug that Pipenv can't locate the correct file of special directives in `setup.cfg` of an editable package.  [#4335](https://github.com/pypa/pipenv/issues/4335)
- Fix a bug that `setup.py` can't be parsed correctly when the assignment is type-annotated.  [#4342](https://github.com/pypa/pipenv/issues/4342)
- Fix a bug that `pipenv graph` throws an exception that PipenvCmdError(cmd_string, c.out, c.err, return_code).  [#4388](https://github.com/pypa/pipenv/issues/4388)
- Do not copy the whole directory tree of local file package.  [#4403](https://github.com/pypa/pipenv/issues/4403)
- Correctly detect whether Pipenv in run under an activated virtualenv.  [#4412](https://github.com/pypa/pipenv/issues/4412)

## Vendored Libraries

- Update `requirementslib` to `1.5.12`.  [#4385](https://github.com/pypa/pipenv/issues/4385)
- - Update `requirements` to `1.5.13`.
  - Update `pip-shims` to `0.5.3`.  [#4421](https://github.com/pypa/pipenv/issues/4421)

# 2020.6.2 (2020-06-02)

## Features & Improvements

- Pipenv will now detect existing `venv` and `virtualenv` based virtual environments more robustly.  [#4276](https://github.com/pypa/pipenv/issues/4276)

## Bug Fixes

- `+` signs in URL authentication fragments will no longer be incorrectly replaced with space ( \`\` \`\` ) characters.  [#4271](https://github.com/pypa/pipenv/issues/4271)
- Fixed a regression which caused Pipenv to fail when running under `/`.  [#4273](https://github.com/pypa/pipenv/issues/4273)
- `setup.py` files with `version` variables read from `os.environ` are now able to be parsed successfully.  [#4274](https://github.com/pypa/pipenv/issues/4274)
- Fixed a bug which caused Pipenv to fail to install packages in a virtual environment if those packages were already present in the system global environment.  [#4276](https://github.com/pypa/pipenv/issues/4276)
- Fix a bug that caused non-specific versions to be pinned in `Pipfile.lock`.  [#4278](https://github.com/pypa/pipenv/issues/4278)
- Corrected a missing exception import and invalid function call invocations in `pipenv.cli.command`.  [#4286](https://github.com/pypa/pipenv/issues/4286)
- Fixed an issue with resolving packages with names defined by function calls in `setup.py`.  [#4292](https://github.com/pypa/pipenv/issues/4292)
- Fixed a regression with installing the current directory, or `.`, inside a `venv` based virtual environment.  [#4295](https://github.com/pypa/pipenv/issues/4295)
- Fixed a bug with the discovery of python paths on Windows which could prevent installation of environments during `pipenv install`.  [#4296](https://github.com/pypa/pipenv/issues/4296)
- Fixed an issue in the `requirementslib` AST parser which prevented parsing of `setup.py` files for dependency metadata.  [#4298](https://github.com/pypa/pipenv/issues/4298)
- Fix a bug where Pipenv doesn't realize the session is interactive  [#4305](https://github.com/pypa/pipenv/issues/4305)

## Vendored Libraries

- Updated requirementslib to version `1.5.11`.  [#4292](https://github.com/pypa/pipenv/issues/4292)
- Updated vendored dependencies:
  : - **pythonfinder**: `1.2.2` => `1.2.4`
    - **requirementslib**: `1.5.9` => `1.5.10`  [#4302](https://github.com/pypa/pipenv/issues/4302)

# 2020.5.28 (2020-05-28)

## Features & Improvements

- `pipenv install` and `pipenv sync` will no longer attempt to install satisfied dependencies during installation.  [#3057](https://github.com/pypa/pipenv/issues/3057),
  [#3506](https://github.com/pypa/pipenv/issues/3506)

- Added support for resolution of direct-url dependencies in `setup.py` files to respect `PEP-508` style URL dependencies.  [#3148](https://github.com/pypa/pipenv/issues/3148)

- Added full support for resolution of all dependency types including direct URLs, zip archives, tarballs, etc.

  - Improved error handling and formatting.
  - Introduced improved cross platform stream wrappers for better `stdout` and `stderr` consistency.  [#3298](https://github.com/pypa/pipenv/issues/3298)

- For consistency with other commands and the `--dev` option
  description, `pipenv lock --requirements --dev` now emits
  both default and development dependencies.
  The new `--dev-only` option requests the previous
  behaviour (e.g. to generate a `dev-requirements.txt` file).  [#3316](https://github.com/pypa/pipenv/issues/3316)

- Pipenv will now successfully recursively lock VCS sub-dependencies.  [#3328](https://github.com/pypa/pipenv/issues/3328)

- Added support for `--verbose` output to `pipenv run`.  [#3348](https://github.com/pypa/pipenv/issues/3348)

- Pipenv will now discover and resolve the intrinsic dependencies of **all** VCS dependencies, whether they are editable or not, to prevent resolution conflicts.  [#3368](https://github.com/pypa/pipenv/issues/3368)

- Added a new environment variable, `PIPENV_RESOLVE_VCS`, to toggle dependency resolution off for non-editable VCS, file, and URL based dependencies.  [#3577](https://github.com/pypa/pipenv/issues/3577)

- Added the ability for Windows users to enable emojis by setting `PIPENV_HIDE_EMOJIS=0`.  [#3595](https://github.com/pypa/pipenv/issues/3595)

- Allow overriding PIPENV_INSTALL_TIMEOUT environment variable (in seconds).  [#3652](https://github.com/pypa/pipenv/issues/3652)

- Allow overriding PIP_EXISTS_ACTION environment variable (value is passed to pip install).
  Possible values here: <https://pip.pypa.io/en/stable/reference/pip/#exists-action-option>
  Useful when you need to `PIP_EXISTS_ACTION=i` (ignore existing packages) - great for CI environments, where you need really fast setup.  [#3738](https://github.com/pypa/pipenv/issues/3738)

- Pipenv will no longer forcibly override `PIP_NO_DEPS` on all vcs and file dependencies as resolution happens on these in a pre-lock step.  [#3763](https://github.com/pypa/pipenv/issues/3763)

- Improved verbose logging output during `pipenv lock` will now stream output to the console while maintaining a spinner.  [#3810](https://github.com/pypa/pipenv/issues/3810)

- Added support for automatic python installs via `asdf` and associated `PIPENV_DONT_USE_ASDF` environment variable.  [#4018](https://github.com/pypa/pipenv/issues/4018)

- Pyenv/asdf can now be used whether or not they are available on PATH. Setting PYENV_ROOT/ASDF_DIR in a Pipenv's .env allows Pipenv to install an interpreter without any shell customizations, so long as pyenv/asdf is installed.  [#4245](https://github.com/pypa/pipenv/issues/4245)

- Added `--key` command line parameter for including personal PyUp.io API tokens when running `pipenv check`.  [#4257](https://github.com/pypa/pipenv/issues/4257)

## Behavior Changes

- Make conservative checks of known exceptions when subprocess returns output, so user won't see the whole traceback - just the error.  [#2553](https://github.com/pypa/pipenv/issues/2553)
- Do not touch Pipfile early and rely on it so that one can do `pipenv sync` without a Pipfile.  [#3386](https://github.com/pypa/pipenv/issues/3386)
- Re-enable `--help` option for `pipenv run` command.  [#3844](https://github.com/pypa/pipenv/issues/3844)
- Make sure `pipenv lock -r --pypi-mirror {MIRROR_URL}` will respect the pypi-mirror in requirements output.  [#4199](https://github.com/pypa/pipenv/issues/4199)

## Bug Fixes

- Raise `PipenvUsageError` when \[\[source\]\] does not contain url field.  [#2373](https://github.com/pypa/pipenv/issues/2373)

- Fixed a bug which caused editable package resolution to sometimes fail with an unhelpful setuptools-related error message.  [#2722](https://github.com/pypa/pipenv/issues/2722)

- Fixed an issue which caused errors due to reliance on the system utilities `which` and `where` which may not always exist on some systems.
  \- Fixed a bug which caused periodic failures in python discovery when executables named `python` were not present on the target `$PATH`.  [#2783](https://github.com/pypa/pipenv/issues/2783)

- Dependency resolution now writes hashes for local and remote files to the lockfile.  [#3053](https://github.com/pypa/pipenv/issues/3053)

- Fixed a bug which prevented `pipenv graph` from correctly showing all dependencies when running from within `pipenv shell`.  [#3071](https://github.com/pypa/pipenv/issues/3071)

- Fixed resolution of direct-url dependencies in `setup.py` files to respect `PEP-508` style URL dependencies.  [#3148](https://github.com/pypa/pipenv/issues/3148)

- Fixed a bug which caused failures in warning reporting when running pipenv inside a virtualenv under some circumstances.

  - Fixed a bug with package discovery when running `pipenv clean`.  [#3298](https://github.com/pypa/pipenv/issues/3298)

- Quote command arguments with carets (`^`) on Windows to work around unintended shell escapes.  [#3307](https://github.com/pypa/pipenv/issues/3307)

- Handle alternate names for UTF-8 encoding.  [#3313](https://github.com/pypa/pipenv/issues/3313)

- Abort pipenv before adding the non-exist package to Pipfile.  [#3318](https://github.com/pypa/pipenv/issues/3318)

- Don't normalize the package name user passes in.  [#3324](https://github.com/pypa/pipenv/issues/3324)

- Fix a bug where custom virtualenv can not be activated with pipenv shell  [#3339](https://github.com/pypa/pipenv/issues/3339)

- Fix a bug that `--site-packages` flag is not recognized.  [#3351](https://github.com/pypa/pipenv/issues/3351)

- Fix a bug where pipenv --clear is not working  [#3353](https://github.com/pypa/pipenv/issues/3353)

- Fix unhashable type error during `$ pipenv install --selective-upgrade`  [#3384](https://github.com/pypa/pipenv/issues/3384)

- Dependencies with direct `PEP508` compliant VCS URLs specified in their `install_requires` will now be successfully locked during the resolution process.  [#3396](https://github.com/pypa/pipenv/issues/3396)

- Fixed a keyerror which could occur when locking VCS dependencies in some cases.  [#3404](https://github.com/pypa/pipenv/issues/3404)

- Fixed a bug that `ValidationError` is thrown when some fields are missing in source section.  [#3427](https://github.com/pypa/pipenv/issues/3427)

- Updated the index names in lock file when source name in Pipfile is changed.  [#3449](https://github.com/pypa/pipenv/issues/3449)

- Fixed an issue which caused `pipenv install --help` to show duplicate entries for `--pre`.  [#3479](https://github.com/pypa/pipenv/issues/3479)

- Fix bug causing `[SSL: CERTIFICATE_VERIFY_FAILED]` when Pipfile `[[source]]` has verify_ssl=false and url with custom port.  [#3502](https://github.com/pypa/pipenv/issues/3502)

- Fix `sync --sequential` ignoring `pip install` errors and logs.  [#3537](https://github.com/pypa/pipenv/issues/3537)

- Fix the issue that lock file can't be created when `PIPENV_PIPFILE` is not under working directory.  [#3584](https://github.com/pypa/pipenv/issues/3584)

- Pipenv will no longer inadvertently set `editable=True` on all vcs dependencies.  [#3647](https://github.com/pypa/pipenv/issues/3647)

- The `--keep-outdated` argument to `pipenv install` and `pipenv lock` will now drop specifier constraints when encountering editable dependencies.
  \- In addition, `--keep-outdated` will retain specifiers that would otherwise be dropped from any entries that have not been updated.  [#3656](https://github.com/pypa/pipenv/issues/3656)

- Fixed a bug which sometimes caused pipenv to fail to respect the `--site-packages` flag when passed with `pipenv install`.  [#3718](https://github.com/pypa/pipenv/issues/3718)

- Normalize the package names to lowercase when comparing used and in-Pipfile packages.  [#3745](https://github.com/pypa/pipenv/issues/3745)

- `pipenv update --outdated` will now correctly handle comparisons between pre/post-releases and normal releases.  [#3766](https://github.com/pypa/pipenv/issues/3766)

- Fixed a `KeyError` which could occur when pinning outdated VCS dependencies via `pipenv lock --keep-outdated`.  [#3768](https://github.com/pypa/pipenv/issues/3768)

- Resolved an issue which caused resolution to fail when encountering poorly formatted `python_version` markers in `setup.py` and `setup.cfg` files.  [#3786](https://github.com/pypa/pipenv/issues/3786)

- Fix a bug that installation errors are displayed as a list.  [#3794](https://github.com/pypa/pipenv/issues/3794)

- Update `pythonfinder` to fix a problem that `python.exe` will be mistakenly chosen for
  virtualenv creation under WSL.  [#3807](https://github.com/pypa/pipenv/issues/3807)

- Fixed several bugs which could prevent editable VCS dependencies from being installed into target environments, even when reporting successful installation.  [#3809](https://github.com/pypa/pipenv/issues/3809)

- `pipenv check --system` should find the correct Python interpreter when `python` does not exist on the system.  [#3819](https://github.com/pypa/pipenv/issues/3819)

- Resolve the symlinks when the path is absolute.  [#3842](https://github.com/pypa/pipenv/issues/3842)

- Pass `--pre` and `--clear` options to `pipenv update --outdated`.  [#3879](https://github.com/pypa/pipenv/issues/3879)

- Fixed a bug which prevented resolution of direct URL dependencies which have PEP508 style direct url VCS sub-dependencies with subdirectories.  [#3976](https://github.com/pypa/pipenv/issues/3976)

- Honor PIPENV_SPINNER environment variable  [#4045](https://github.com/pypa/pipenv/issues/4045)

- Fixed an issue with `pipenv check` failing due to an invalid API key from `pyup.io`.  [#4188](https://github.com/pypa/pipenv/issues/4188)

- Fixed a bug which caused versions from VCS dependencies to be included in `Pipfile.lock` inadvertently.  [#4217](https://github.com/pypa/pipenv/issues/4217)

- Fixed a bug which caused pipenv to search non-existent virtual environments for `pip` when installing using `--system`.  [#4220](https://github.com/pypa/pipenv/issues/4220)

- `Requires-Python` values specifying constraint versions of python starting from `1.x` will now be parsed successfully.  [#4226](https://github.com/pypa/pipenv/issues/4226)

- Fix a bug of `pipenv update --outdated` that can't print output correctly.  [#4229](https://github.com/pypa/pipenv/issues/4229)

- Fixed a bug which caused pipenv to prefer source distributions over wheels from `PyPI` during the dependency resolution phase.
  Fixed an issue which prevented proper build isolation using `pep517` based builders during dependency resolution.  [#4231](https://github.com/pypa/pipenv/issues/4231)

- Don't fallback to system Python when no matching Python version is found.  [#4232](https://github.com/pypa/pipenv/issues/4232)

## Vendored Libraries

- Updated vendored dependencies:

  > - **attrs**: `18.2.0` => `19.1.0`
  > - **certifi**: `2018.10.15` => `2019.3.9`
  > - **cached_property**: `1.4.3` => `1.5.1`
  > - **cerberus**: `1.2.0` => `1.3.1`
  > - **click-completion**: `0.5.0` => `0.5.1`
  > - **colorama**: `0.3.9` => `0.4.1`
  > - **distlib**: `0.2.8` => `0.2.9`
  > - **idna**: `2.7` => `2.8`
  > - **jinja2**: `2.10.0` => `2.10.1`
  > - **markupsafe**: `1.0` => `1.1.1`
  > - **orderedmultidict**: `(new)` => `1.0`
  > - **packaging**: `18.0` => `19.0`
  > - **parse**: `1.9.0` => `1.12.0`
  > - **pathlib2**: `2.3.2` => `2.3.3`
  > - **pep517**: `(new)` => `0.5.0`
  > - **pexpect**: `4.6.0` => `4.7.0`
  > - **pipdeptree**: `0.13.0` => `0.13.2`
  > - **pyparsing**: `2.2.2` => `2.3.1`
  > - **python-dotenv**: `0.9.1` => `0.10.2`
  > - **pythonfinder**: `1.1.10` => `1.2.1`
  > - **pytoml**: `(new)` => `0.1.20`
  > - **requests**: `2.20.1` => `2.21.0`
  > - **requirementslib**: `1.3.3` => `1.5.0`
  > - **scandir**: `1.9.0` => `1.10.0`
  > - **shellingham**: `1.2.7` => `1.3.1`
  > - **six**: `1.11.0` => `1.12.0`
  > - **tomlkit**: `0.5.2` => `0.5.3`
  > - **urllib3**: `1.24` => `1.25.2`
  > - **vistir**: `0.3.0` => `0.4.1`
  > - **yaspin**: `0.14.0` => `0.14.3`

  - Removed vendored dependency **cursor**.  [#3298](https://github.com/pypa/pipenv/issues/3298)

- Updated `pip_shims` to support `--outdated` with new pip versions.  [#3766](https://github.com/pypa/pipenv/issues/3766)

- Update vendored dependencies and invocations

  - Update vendored and patched dependencies
  - Update patches on `piptools`, `pip`, `pip-shims`, `tomlkit`
  - Fix invocations of dependencies
  - Fix custom `InstallCommand` instantiation
  - Update `PackageFinder` usage
  - Fix `Bool` stringify attempts from `tomlkit`

  Updated vendored dependencies:
  : - **attrs**: `` `18.2.0 `` => `` `19.1.0 ``
    - **certifi**: `` `2018.10.15 `` => `` `2019.3.9 ``
    - **cached_property**: `` `1.4.3 `` => `` `1.5.1 ``
    - **cerberus**: `` `1.2.0 `` => `` `1.3.1 ``
    - **click**: `` `7.0.0 `` => `` `7.1.1 ``
    - **click-completion**: `` `0.5.0 `` => `` `0.5.1 ``
    - **colorama**: `` `0.3.9 `` => `` `0.4.3 ``
    - **contextlib2**: `` `(new) `` => `` `0.6.0.post1 ``
    - **distlib**: `` `0.2.8 `` => `` `0.2.9 ``
    - **funcsigs**: `` `(new) `` => `` `1.0.2 ``
    - **importlib_metadata** `` `1.3.0 `` => `` `1.5.1 ``
    - **importlib-resources**:  `` `(new) `` => `` `1.4.0 ``
    - **idna**: `` `2.7 `` => `` `2.9 ``
    - **jinja2**: `` `2.10.0 `` => `` `2.11.1 ``
    - **markupsafe**: `` `1.0 `` => `` `1.1.1 ``
    - **more-itertools**: `` `(new) `` => `` `5.0.0 ``
    - **orderedmultidict**: `` `(new) `` => `` `1.0 ``
    - **packaging**: `` `18.0 `` => `` `19.0 ``
    - **parse**: `` `1.9.0 `` => `` `1.15.0 ``
    - **pathlib2**: `` `2.3.2 `` => `` `2.3.3 ``
    - **pep517**: `` `(new) `` => `` `0.5.0 ``
    - **pexpect**: `` `4.6.0 `` => `` `4.8.0 ``
    - **pip-shims**: `` `0.2.0 `` => `` `0.5.1 ``
    - **pipdeptree**: `` `0.13.0 `` => `` `0.13.2 ``
    - **pyparsing**: `` `2.2.2 `` => `` `2.4.6 ``
    - **python-dotenv**: `` `0.9.1 `` => `` `0.10.2 ``
    - **pythonfinder**: `` `1.1.10 `` => `` `1.2.2 ``
    - **pytoml**: `` `(new) `` => `` `0.1.20 ``
    - **requests**: `` `2.20.1 `` => `` `2.23.0 ``
    - **requirementslib**: `` `1.3.3 `` => `` `1.5.4 ``
    - **scandir**: `` `1.9.0 `` => `` `1.10.0 ``
    - **shellingham**: `` `1.2.7 `` => `` `1.3.2 ``
    - **six**: `` `1.11.0 `` => `` `1.14.0 ``
    - **tomlkit**: `` `0.5.2 `` => `` `0.5.11 ``
    - **urllib3**: `` `1.24 `` => `` `1.25.8 ``
    - **vistir**: `` `0.3.0 `` => `` `0.5.0 ``
    - **yaspin**: `` `0.14.0 `` => `` `0.14.3 ``
    - **zipp**: `` `0.6.0 ``

  - Removed vendored dependency **cursor**.  [#4169](https://github.com/pypa/pipenv/issues/4169)

- Add and update vendored dependencies to accommodate `safety` vendoring:
  \- **safety** `(none)` => `1.8.7`
  \- **dparse** `(none)` => `0.5.0`
  \- **pyyaml** `(none)` => `5.3.1`
  \- **urllib3** `1.25.8` => `1.25.9`
  \- **certifi** `2019.11.28` => `2020.4.5.1`
  \- **pyparsing** `2.4.6` => `2.4.7`
  \- **resolvelib** `0.2.2` => `0.3.0`
  \- **importlib-metadata** `1.5.1` => `1.6.0`
  \- **pip-shims** `0.5.1` => `0.5.2`
  \- **requirementslib** `1.5.5` => `1.5.6`  [#4188](https://github.com/pypa/pipenv/issues/4188)

- Updated vendored `pip` => `20.0.2` and `pip-tools` => `5.0.0`.  [#4215](https://github.com/pypa/pipenv/issues/4215)

- Updated vendored dependencies to latest versions for security and bug fixes:

  - **requirementslib** `1.5.8` => `1.5.9`
  - **vistir** `0.5.0` => `0.5.1`
  - **jinja2** `2.11.1` => `2.11.2`
  - **click** `7.1.1` => `7.1.2`
  - **dateutil** `(none)` => `2.8.1`
  - **backports.functools_lru_cache** `1.5.0` => `1.6.1`
  - **enum34** `1.1.6` => `1.1.10`
  - **toml** `0.10.0` => `0.10.1`
  - **importlib_resources** `1.4.0` => `1.5.0`  [#4226](https://github.com/pypa/pipenv/issues/4226)

- Changed attrs import path in vendored dependencies to always import from `pipenv.vendor`.  [#4267](https://github.com/pypa/pipenv/issues/4267)

## Improved Documentation

- Added documentation about variable expansion in `Pipfile` entries.  [#2317](https://github.com/pypa/pipenv/issues/2317)
- Consolidate all contributing docs in the rst file  [#3120](https://github.com/pypa/pipenv/issues/3120)
- Update the out-dated manual page.  [#3246](https://github.com/pypa/pipenv/issues/3246)
- Move CLI docs to its own page.  [#3346](https://github.com/pypa/pipenv/issues/3346)
- Replace (non-existent) video on docs index.rst with equivalent gif.  [#3499](https://github.com/pypa/pipenv/issues/3499)
- Clarify wording in Basic Usage example on using double quotes to escape shell redirection  [#3522](https://github.com/pypa/pipenv/issues/3522)
- Ensure docs show navigation on small-screen devices  [#3527](https://github.com/pypa/pipenv/issues/3527)
- Added a link to the TOML Spec under General Recommendations & Version Control to clarify how Pipfiles should be written.  [#3629](https://github.com/pypa/pipenv/issues/3629)
- Updated the documentation with the new `pytest` entrypoint.  [#3759](https://github.com/pypa/pipenv/issues/3759)
- Fix link to GIF in README.md demonstrating Pipenv's usage, and add descriptive alt text.  [#3911](https://github.com/pypa/pipenv/issues/3911)
- Added a line describing potential issues in fancy extension.  [#3912](https://github.com/pypa/pipenv/issues/3912)
- Documental description of how Pipfile works and association with Pipenv.  [#3913](https://github.com/pypa/pipenv/issues/3913)
- Clarify the proper value of `python_version` and `python_full_version`.  [#3914](https://github.com/pypa/pipenv/issues/3914)
- Write description for --deploy extension and few extensions differences.  [#3915](https://github.com/pypa/pipenv/issues/3915)
- More documentation for `.env` files  [#4100](https://github.com/pypa/pipenv/issues/4100)
- Updated documentation to point to working links.  [#4137](https://github.com/pypa/pipenv/issues/4137)
- Replace docs.pipenv.org with pipenv.pypa.io  [#4167](https://github.com/pypa/pipenv/issues/4167)
- Added functionality to check spelling in documentation and cleaned up existing typographical issues.  [#4209](https://github.com/pypa/pipenv/issues/4209)

# 2018.11.26 (2018-11-26)

## Bug Fixes

- Environment variables are expanded correctly before running scripts on POSIX.  [#3178](https://github.com/pypa/pipenv/issues/3178)
- Pipenv will no longer disable user-mode installation when the `--system` flag is passed in.  [#3222](https://github.com/pypa/pipenv/issues/3222)
- Fixed an issue with attempting to render unicode output in non-unicode locales.  [#3223](https://github.com/pypa/pipenv/issues/3223)
- Fixed a bug which could cause failures to occur when parsing python entries from global pyenv version files.  [#3224](https://github.com/pypa/pipenv/issues/3224)
- Fixed an issue which prevented the parsing of named extras sections from certain `setup.py` files.  [#3230](https://github.com/pypa/pipenv/issues/3230)
- Correctly detect the virtualenv location inside an activated virtualenv.  [#3231](https://github.com/pypa/pipenv/issues/3231)
- Fixed a bug which caused spinner frames to be written to standard output during locking operations which could cause redirection pipes to fail.  [#3239](https://github.com/pypa/pipenv/issues/3239)
- Fixed a bug that editable packages can't be uninstalled correctly.  [#3240](https://github.com/pypa/pipenv/issues/3240)
- Corrected an issue with installation timeouts which caused dependency resolution to fail for longer duration resolution steps.  [#3244](https://github.com/pypa/pipenv/issues/3244)
- Adding normal pep 508 compatible markers is now fully functional when using VCS dependencies.  [#3249](https://github.com/pypa/pipenv/issues/3249)
- Updated `requirementslib` and `pythonfinder` for multiple bug fixes.  [#3254](https://github.com/pypa/pipenv/issues/3254)
- Pipenv will now ignore hashes when installing with `--skip-lock`.  [#3255](https://github.com/pypa/pipenv/issues/3255)
- Fixed an issue where pipenv could crash when multiple pipenv processes attempted to create the same directory.  [#3257](https://github.com/pypa/pipenv/issues/3257)
- Fixed an issue which sometimes prevented successful creation of a project Pipfile.  [#3260](https://github.com/pypa/pipenv/issues/3260)
- `pipenv install` will now unset the `PYTHONHOME` environment variable when not combined with `--system`.  [#3261](https://github.com/pypa/pipenv/issues/3261)
- Pipenv will ensure that warnings do not interfere with the resolution process by suppressing warnings' usage of standard output and writing to standard error instead.  [#3273](https://github.com/pypa/pipenv/issues/3273)
- Fixed an issue which prevented variables from the environment, such as `PIPENV_DEV` or `PIPENV_SYSTEM`, from being parsed and implemented correctly.  [#3278](https://github.com/pypa/pipenv/issues/3278)
- Clear pythonfinder cache after Python install.  [#3287](https://github.com/pypa/pipenv/issues/3287)
- Fixed a race condition in hash resolution for dependencies for certain dependencies with missing cache entries or fresh Pipenv installs.  [#3289](https://github.com/pypa/pipenv/issues/3289)
- Pipenv will now respect top-level pins over VCS dependency locks.  [#3296](https://github.com/pypa/pipenv/issues/3296)

## Vendored Libraries

- Update vendored dependencies to resolve resolution output parsing and python finding:
  : - `pythonfinder 1.1.9 -> 1.1.10`
    - `requirementslib 1.3.1 -> 1.3.3`
    - `vistir 0.2.3 -> 0.2.5`  [#3280](https://github.com/pypa/pipenv/issues/3280)

# 2018.11.14 (2018-11-14)

## Features & Improvements

- Improved exceptions and error handling on failures.  [#1977](https://github.com/pypa/pipenv/issues/1977)
- Added persistent settings for all CLI flags via `PIPENV_{FLAG_NAME}` environment variables by enabling `auto_envvar_prefix=PIPENV` in click (implements PEEP-0002).  [#2200](https://github.com/pypa/pipenv/issues/2200)
- Added improved messaging about available but skipped updates due to dependency conflicts when running `pipenv update --outdated`.  [#2411](https://github.com/pypa/pipenv/issues/2411)
- Added environment variable `PIPENV_PYUP_API_KEY` to add ability
  to override the bundled PyUP.io API key.  [#2825](https://github.com/pypa/pipenv/issues/2825)
- Added additional output to `pipenv update --outdated` to indicate that the operation succeeded and all packages were already up to date.  [#2828](https://github.com/pypa/pipenv/issues/2828)
- Updated `crayons` patch to enable colors on native powershell but swap native blue for magenta.  [#3020](https://github.com/pypa/pipenv/issues/3020)
- Added support for `--bare` to `pipenv clean`, and fixed `pipenv sync --bare` to actually reduce output.  [#3041](https://github.com/pypa/pipenv/issues/3041)
- Added windows-compatible spinner via upgraded `vistir` dependency.  [#3089](https://github.com/pypa/pipenv/issues/3089)
- - Added support for python installations managed by `asdf`.  [#3096](https://github.com/pypa/pipenv/issues/3096)
- Improved runtime performance of no-op commands such as `pipenv --venv` by around 2/3.  [#3158](https://github.com/pypa/pipenv/issues/3158)
- Do not show error but success for running `pipenv uninstall --all` in a fresh virtual environment.  [#3170](https://github.com/pypa/pipenv/issues/3170)
- Improved asynchronous installation and error handling via queued subprocess parallelization.  [#3217](https://github.com/pypa/pipenv/issues/3217)

## Bug Fixes

- Remote non-PyPI artifacts and local wheels and artifacts will now include their own hashes rather than including hashes from `PyPI`.  [#2394](https://github.com/pypa/pipenv/issues/2394)
- Non-ascii characters will now be handled correctly when parsed by pipenv's `ToML` parsers.  [#2737](https://github.com/pypa/pipenv/issues/2737)
- Updated `pipenv uninstall` to respect the `--skip-lock` argument.  [#2848](https://github.com/pypa/pipenv/issues/2848)
- Fixed a bug which caused uninstallation to sometimes fail to successfully remove packages from `Pipfiles` with comments on preceding or following lines.  [#2885](https://github.com/pypa/pipenv/issues/2885),
  [#3099](https://github.com/pypa/pipenv/issues/3099)
- Pipenv will no longer fail when encountering python versions on Windows that have been uninstalled.  [#2983](https://github.com/pypa/pipenv/issues/2983)
- Fixed unnecessary extras are added when translating markers  [#3026](https://github.com/pypa/pipenv/issues/3026)
- Fixed a virtualenv creation issue which could cause new virtualenvs to inadvertently attempt to read and write to global site packages.  [#3047](https://github.com/pypa/pipenv/issues/3047)
- Fixed an issue with virtualenv path derivation which could cause errors, particularly for users on WSL bash.  [#3055](https://github.com/pypa/pipenv/issues/3055)
- Fixed a bug which caused `Unexpected EOF` errors to be thrown when `pip` was waiting for input from users who had put login credentials in environment variables.  [#3088](https://github.com/pypa/pipenv/issues/3088)
- Fixed a bug in `requirementslib` which prevented successful installation from mercurial repositories.  [#3090](https://github.com/pypa/pipenv/issues/3090)
- Fixed random resource warnings when using pyenv or any other subprocess calls.  [#3094](https://github.com/pypa/pipenv/issues/3094)
- - Fixed a bug which sometimes prevented cloning and parsing `mercurial` requirements.  [#3096](https://github.com/pypa/pipenv/issues/3096)
- Fixed an issue in `delegator.py` related to subprocess calls when using `PopenSpawn` to stream output, which sometimes threw unexpected `EOF` errors.  [#3102](https://github.com/pypa/pipenv/issues/3102),
  [#3114](https://github.com/pypa/pipenv/issues/3114),
  [#3117](https://github.com/pypa/pipenv/issues/3117)
- Fix the path casing issue that makes `pipenv clean` fail on Windows  [#3104](https://github.com/pypa/pipenv/issues/3104)
- Pipenv will avoid leaving build artifacts in the current working directory.  [#3106](https://github.com/pypa/pipenv/issues/3106)
- Fixed issues with broken subprocess calls leaking resource handles and causing random and sporadic failures.  [#3109](https://github.com/pypa/pipenv/issues/3109)
- Fixed an issue which caused `pipenv clean` to sometimes clean packages from the base `site-packages` folder or fail entirely.  [#3113](https://github.com/pypa/pipenv/issues/3113)
- Updated `pythonfinder` to correct an issue with unnesting of nested paths when searching for python versions.  [#3121](https://github.com/pypa/pipenv/issues/3121)
- Added additional logic for ignoring and replacing non-ascii characters when formatting console output on non-UTF-8 systems.  [#3131](https://github.com/pypa/pipenv/issues/3131)
- Fix virtual environment discovery when `PIPENV_VENV_IN_PROJECT` is set, but the in-project `.venv` is a file.  [#3134](https://github.com/pypa/pipenv/issues/3134)
- Hashes for remote and local non-PyPI artifacts will now be included in `Pipfile.lock` during resolution.  [#3145](https://github.com/pypa/pipenv/issues/3145)
- Fix project path hashing logic in purpose to prevent collisions of virtual environments.  [#3151](https://github.com/pypa/pipenv/issues/3151)
- Fix package installation when the virtual environment path contains parentheses.  [#3158](https://github.com/pypa/pipenv/issues/3158)
- Azure Pipelines YAML files are updated to use the latest syntax and product name.  [#3164](https://github.com/pypa/pipenv/issues/3164)
- Fixed new spinner success message to write only one success message during resolution.  [#3183](https://github.com/pypa/pipenv/issues/3183)
- Pipenv will now correctly respect the `--pre` option when used with `pipenv install`.  [#3185](https://github.com/pypa/pipenv/issues/3185)
- Fix a bug where exception is raised when run pipenv graph in a project without created virtualenv  [#3201](https://github.com/pypa/pipenv/issues/3201)
- When sources are missing names, names will now be derived from the supplied URL.  [#3216](https://github.com/pypa/pipenv/issues/3216)

## Vendored Libraries

- Updated `pythonfinder` to correct an issue with unnesting of nested paths when searching for python versions.  [#3061](https://github.com/pypa/pipenv/issues/3061),
  [#3121](https://github.com/pypa/pipenv/issues/3121)
- Updated vendored dependencies:
  : - `certifi 2018.08.24 => 2018.10.15`
    - `urllib3 1.23 => 1.24`
    - `requests 2.19.1 => 2.20.0`
    - ``` shellingham ``1.2.6 => 1.2.7 ```
    - `tomlkit 0.4.4. => 0.4.6`
    - `vistir 0.1.6 => 0.1.8`
    - `pythonfinder 0.1.2 => 0.1.3`
    - `requirementslib 1.1.9 => 1.1.10`
    - `backports.functools_lru_cache 1.5.0 (new)`
    - `cursor 1.2.0 (new)`  [#3089](https://github.com/pypa/pipenv/issues/3089)
- Updated vendored dependencies:
  : - `requests 2.19.1 => 2.20.1`
    - `tomlkit 0.4.46 => 0.5.2`
    - `vistir 0.1.6 => 0.2.4`
    - `pythonfinder 1.1.2 => 1.1.8`
    - `requirementslib 1.1.10 => 1.3.0`  [#3096](https://github.com/pypa/pipenv/issues/3096)
- Switch to `tomlkit` for parsing and writing. Drop `prettytoml` and `contoml` from vendors.  [#3191](https://github.com/pypa/pipenv/issues/3191)
- Updated `requirementslib` to aid in resolution of local and remote archives.  [#3196](https://github.com/pypa/pipenv/issues/3196)

## Improved Documentation

- Expanded development and testing documentation for contributors to get started.  [#3074](https://github.com/pypa/pipenv/issues/3074)

# 2018.10.13 (2018-10-13)

## Bug Fixes

- Fixed a bug in `pipenv clean` which caused global packages to sometimes be inadvertently targeted for cleanup.  [#2849](https://github.com/pypa/pipenv/issues/2849)
- Fix broken backport imports for vendored vistir.  [#2950](https://github.com/pypa/pipenv/issues/2950),
  [#2955](https://github.com/pypa/pipenv/issues/2955),
  [#2961](https://github.com/pypa/pipenv/issues/2961)
- Fixed a bug with importing local vendored dependencies when running `pipenv graph`.  [#2952](https://github.com/pypa/pipenv/issues/2952)
- Fixed a bug which caused executable discovery to fail when running inside a virtualenv.  [#2957](https://github.com/pypa/pipenv/issues/2957)
- Fix parsing of outline tables.  [#2971](https://github.com/pypa/pipenv/issues/2971)
- Fixed a bug which caused `verify_ssl` to fail to drop through to `pip install` correctly as `trusted-host`.  [#2979](https://github.com/pypa/pipenv/issues/2979)
- Fixed a bug which caused canonicalized package names to fail to resolve against PyPI.  [#2989](https://github.com/pypa/pipenv/issues/2989)
- Enhanced CI detection to detect Azure Devops builds.  [#2993](https://github.com/pypa/pipenv/issues/2993)
- Fixed a bug which prevented installing pinned versions which used redirection symbols from the command line.  [#2998](https://github.com/pypa/pipenv/issues/2998)
- Fixed a bug which prevented installing the local directory in non-editable mode.  [#3005](https://github.com/pypa/pipenv/issues/3005)

## Vendored Libraries

- Updated `requirementslib` to version `1.1.9`.  [#2989](https://github.com/pypa/pipenv/issues/2989)
- Upgraded `pythonfinder => 1.1.1` and `vistir => 0.1.7`.  [#3007](https://github.com/pypa/pipenv/issues/3007)

# 2018.10.9 (2018-10-09)

## Features & Improvements

- Added environment variables `PIPENV_VERBOSE` and `PIPENV_QUIET` to control
  output verbosity without needing to pass options.  [#2527](https://github.com/pypa/pipenv/issues/2527)

- Updated test-PyPI add-on to better support json-API access (forward compatibility).
  Improved testing process for new contributors.  [#2568](https://github.com/pypa/pipenv/issues/2568)

- Greatly enhanced python discovery functionality:

  - Added pep514 (windows launcher/finder) support for python discovery.
  - Introduced architecture discovery for python installations which support different architectures.  [#2582](https://github.com/pypa/pipenv/issues/2582)

- Added support for `pipenv shell` on msys and cygwin/mingw/git bash for Windows.  [#2641](https://github.com/pypa/pipenv/issues/2641)

- Enhanced resolution of editable and VCS dependencies.  [#2643](https://github.com/pypa/pipenv/issues/2643)

- Deduplicate and refactor CLI to use stateful arguments and object passing.  See [this issue](https://github.com/pallets/click/issues/108) for reference.  [#2814](https://github.com/pypa/pipenv/issues/2814)

## Behavior Changes

- Virtual environment activation for `run` is revised to improve interpolation
  with other Python discovery tools.  [#2503](https://github.com/pypa/pipenv/issues/2503)
- Improve terminal coloring to display better in Powershell.  [#2511](https://github.com/pypa/pipenv/issues/2511)
- Invoke `virtualenv` directly for virtual environment creation, instead of depending on `pew`.  [#2518](https://github.com/pypa/pipenv/issues/2518)
- `pipenv --help` will now include short help descriptions.  [#2542](https://github.com/pypa/pipenv/issues/2542)
- Add `COMSPEC` to fallback option (along with `SHELL` and `PYENV_SHELL`)
  if shell detection fails, improving robustness on Windows.  [#2651](https://github.com/pypa/pipenv/issues/2651)
- Fallback to shell mode if `run` fails with Windows error 193 to handle non-executable commands. This should improve usability on Windows, where some users run non-executable files without specifying a command, relying on Windows file association to choose the current command.  [#2718](https://github.com/pypa/pipenv/issues/2718)

## Bug Fixes

- Fixed a bug which prevented installation of editable requirements using `ssh://` style URLs  [#1393](https://github.com/pypa/pipenv/issues/1393)
- VCS Refs for locked local editable dependencies will now update appropriately to the latest hash when running `pipenv update`.  [#1690](https://github.com/pypa/pipenv/issues/1690)
- `.tar.gz` and `.zip` artifacts will now have dependencies installed even when they are missing from the Lockfile.  [#2173](https://github.com/pypa/pipenv/issues/2173)
- The command line parser will now handle multiple `-e/--editable` dependencies properly via click's option parser to help mitigate future parsing issues.  [#2279](https://github.com/pypa/pipenv/issues/2279)
- Fixed the ability of pipenv to parse `dependency_links` from `setup.py` when `PIP_PROCESS_DEPENDENCY_LINKS` is enabled.  [#2434](https://github.com/pypa/pipenv/issues/2434)
- Fixed a bug which could cause `-i/--index` arguments to sometimes be incorrectly picked up in packages.  This is now handled in the command line parser.  [#2494](https://github.com/pypa/pipenv/issues/2494)
- Fixed non-deterministic resolution issues related to changes to the internal package finder in `pip 10`.  [#2499](https://github.com/pypa/pipenv/issues/2499),
  [#2529](https://github.com/pypa/pipenv/issues/2529),
  [#2589](https://github.com/pypa/pipenv/issues/2589),
  [#2666](https://github.com/pypa/pipenv/issues/2666),
  [#2767](https://github.com/pypa/pipenv/issues/2767),
  [#2785](https://github.com/pypa/pipenv/issues/2785),
  [#2795](https://github.com/pypa/pipenv/issues/2795),
  [#2801](https://github.com/pypa/pipenv/issues/2801),
  [#2824](https://github.com/pypa/pipenv/issues/2824),
  [#2862](https://github.com/pypa/pipenv/issues/2862),
  [#2879](https://github.com/pypa/pipenv/issues/2879),
  [#2894](https://github.com/pypa/pipenv/issues/2894),
  [#2933](https://github.com/pypa/pipenv/issues/2933)
- Fix subshell invocation on Windows for Python 2.  [#2515](https://github.com/pypa/pipenv/issues/2515)
- Fixed a bug which sometimes caused pipenv to throw a `TypeError` or to run into encoding issues when writing a Lockfile on python 2.  [#2561](https://github.com/pypa/pipenv/issues/2561)
- Improve quoting logic for `pipenv run` so it works better with Windows
  built-in commands.  [#2563](https://github.com/pypa/pipenv/issues/2563)
- Fixed a bug related to parsing VCS requirements with both extras and subdirectory fragments.
  Corrected an issue in the `requirementslib` parser which led to some markers being discarded rather than evaluated.  [#2564](https://github.com/pypa/pipenv/issues/2564)
- Fixed multiple issues with finding the correct system python locations.  [#2582](https://github.com/pypa/pipenv/issues/2582)
- Catch JSON decoding error to prevent exception when the lock file is of
  invalid format.  [#2607](https://github.com/pypa/pipenv/issues/2607)
- Fixed a rare bug which could sometimes cause errors when installing packages with custom sources.  [#2610](https://github.com/pypa/pipenv/issues/2610)
- Update requirementslib to fix a bug which could raise an `UnboundLocalError` when parsing malformed VCS URIs.  [#2617](https://github.com/pypa/pipenv/issues/2617)
- Fixed an issue which prevented passing multiple `--ignore` parameters to `pipenv check`.  [#2632](https://github.com/pypa/pipenv/issues/2632)
- Fixed a bug which caused attempted hashing of `ssh://` style URIs which could cause failures during installation of private ssh repositories.
  \- Corrected path conversion issues which caused certain editable VCS paths to be converted to `ssh://` URIs improperly.  [#2639](https://github.com/pypa/pipenv/issues/2639)
- Fixed a bug which caused paths to be formatted incorrectly when using `pipenv shell` in bash for windows.  [#2641](https://github.com/pypa/pipenv/issues/2641)
- Dependency links to private repositories defined via `ssh://` schemes will now install correctly and skip hashing as long as `PIP_PROCESS_DEPENDENCY_LINKS=1`.  [#2643](https://github.com/pypa/pipenv/issues/2643)
- Fixed a bug which sometimes caused pipenv to parse the `trusted_host` argument to pip incorrectly when parsing source URLs which specify `verify_ssl = false`.  [#2656](https://github.com/pypa/pipenv/issues/2656)
- Prevent crashing when a virtual environment in `WORKON_HOME` is faulty.  [#2676](https://github.com/pypa/pipenv/issues/2676)
- Fixed virtualenv creation failure when a .venv file is present in the project root.  [#2680](https://github.com/pypa/pipenv/issues/2680)
- Fixed a bug which could cause the `-e/--editable` argument on a dependency to be accidentally parsed as a dependency itself.  [#2714](https://github.com/pypa/pipenv/issues/2714)
- Correctly pass `verbose` and `debug` flags to the resolver subprocess so it generates appropriate output. This also resolves a bug introduced by the fix to #2527.  [#2732](https://github.com/pypa/pipenv/issues/2732)
- All markers are now included in `pipenv lock --requirements` output.  [#2748](https://github.com/pypa/pipenv/issues/2748)
- Fixed a bug in marker resolution which could cause duplicate and non-deterministic markers.  [#2760](https://github.com/pypa/pipenv/issues/2760)
- Fixed a bug in the dependency resolver which caused regular issues when handling `setup.py` based dependency resolution.  [#2766](https://github.com/pypa/pipenv/issues/2766)
- Updated vendored dependencies:
  : - `pip-tools` (updated and patched to latest w/ `pip 18.0` compatibility)
    - `pip 10.0.1 => 18.0`
    - `click 6.7 => 7.0`
    - `toml 0.9.4 => 0.10.0`
    - `pyparsing 2.2.0 => 2.2.2`
    - `delegator 0.1.0 => 0.1.1`
    - `attrs 18.1.0 => 18.2.0`
    - `distlib 0.2.7 => 0.2.8`
    - `packaging 17.1.0 => 18.0`
    - `passa 0.2.0 => 0.3.1`
    - `pip_shims 0.1.2 => 0.3.1`
    - `plette 0.1.1 => 0.2.2`
    - `pythonfinder 1.0.2 => 1.1.0`
    - `pytoml 0.1.18 => 0.1.19`
    - `requirementslib 1.1.16 => 1.1.17`
    - `shellingham 1.2.4 => 1.2.6`
    - `tomlkit 0.4.2 => 0.4.4`
    - `vistir 0.1.4 => 0.1.6`
  [#2802](https://github.com/pypa/pipenv/issues/2802),
  [#2867](https://github.com/pypa/pipenv/issues/2867),
  [#2880](https://github.com/pypa/pipenv/issues/2880)
- Fixed a bug where `pipenv` crashes when the `WORKON_HOME` directory does not exist.  [#2877](https://github.com/pypa/pipenv/issues/2877)
- Fixed pip is not loaded from pipenv's patched one but the system one  [#2912](https://github.com/pypa/pipenv/issues/2912)
- Fixed various bugs related to `pip 18.1` release which prevented locking, installation, and syncing, and dumping to a `requirements.txt` file.  [#2924](https://github.com/pypa/pipenv/issues/2924)

## Vendored Libraries

- Pew is no longer vendored. Entry point `pewtwo`, packages `pipenv.pew` and
  `pipenv.patched.pew` are removed.  [#2521](https://github.com/pypa/pipenv/issues/2521)
- Update `pythonfinder` to major release `1.0.0` for integration.  [#2582](https://github.com/pypa/pipenv/issues/2582)
- Update requirementslib to fix a bug which could raise an `UnboundLocalError` when parsing malformed VCS URIs.  [#2617](https://github.com/pypa/pipenv/issues/2617)
- - Vendored new libraries `vistir` and `pip-shims`, `tomlkit`, `modutil`, and `plette`.
  - Update vendored libraries:
    \- `scandir` to `1.9.0`
    \- `click-completion` to `0.4.1`
    \- `semver` to `2.8.1`
    \- `shellingham` to `1.2.4`
    \- `pytoml` to `0.1.18`
    \- `certifi` to `2018.8.24`
    \- `ptyprocess` to `0.6.0`
    \- `requirementslib` to `1.1.5`
    \- `pythonfinder` to `1.0.2`
    \- `pipdeptree` to `0.13.0`
    \- `python-dotenv` to `0.9.1`  [#2639](https://github.com/pypa/pipenv/issues/2639)
- Updated vendored dependencies:
  : - `pip-tools` (updated and patched to latest w/ `pip 18.0` compatibility)
    - `pip 10.0.1 => 18.0`
    - `click 6.7 => 7.0`
    - `toml 0.9.4 => 0.10.0`
    - `pyparsing 2.2.0 => 2.2.2`
    - `delegator 0.1.0 => 0.1.1`
    - `attrs 18.1.0 => 18.2.0`
    - `distlib 0.2.7 => 0.2.8`
    - `packaging 17.1.0 => 18.0`
    - `passa 0.2.0 => 0.3.1`
    - `pip_shims 0.1.2 => 0.3.1`
    - `plette 0.1.1 => 0.2.2`
    - `pythonfinder 1.0.2 => 1.1.0`
    - `pytoml 0.1.18 => 0.1.19`
    - `requirementslib 1.1.16 => 1.1.17`
    - `shellingham 1.2.4 => 1.2.6`
    - `tomlkit 0.4.2 => 0.4.4`
    - `vistir 0.1.4 => 0.1.6`
  [#2902](https://github.com/pypa/pipenv/issues/2902),
  [#2935](https://github.com/pypa/pipenv/issues/2935)

## Improved Documentation

- Simplified the test configuration process.  [#2568](https://github.com/pypa/pipenv/issues/2568)
- Updated documentation to use working fortune cookie add-on.  [#2644](https://github.com/pypa/pipenv/issues/2644)
- Added additional information about troubleshooting `pipenv shell` by using the the `$PIPENV_SHELL` environment variable.  [#2671](https://github.com/pypa/pipenv/issues/2671)
- Added a link to `PEP-440` version specifiers in the documentation for additional detail.  [#2674](https://github.com/pypa/pipenv/issues/2674)
- Added simple example to README.md for installing from git.  [#2685](https://github.com/pypa/pipenv/issues/2685)
- Stopped recommending `--system` for Docker contexts.  [#2762](https://github.com/pypa/pipenv/issues/2762)
- Fixed the example url for doing "pipenv install -e
  some-repository-url#egg=something", it was missing the "egg=" in the fragment
  identifier.  [#2792](https://github.com/pypa/pipenv/issues/2792)
- Fixed link to the "be cordial" essay in the contribution documentation.  [#2793](https://github.com/pypa/pipenv/issues/2793)
- Clarify `pipenv install` documentation  [#2844](https://github.com/pypa/pipenv/issues/2844)
- Replace reference to uservoice with PEEP-000  [#2909](https://github.com/pypa/pipenv/issues/2909)

# 2018.7.1 (2018-07-01)

## Features & Improvements

- All calls to `pipenv shell` are now implemented from the ground up using [shellingham](https://github.com/sarugaku/shellingham), a custom library which was purpose built to handle edge cases and shell detection.  [#2371](https://github.com/pypa/pipenv/issues/2371)
- Added support for python 3.7 via a few small compatibility / bug fixes.  [#2427](https://github.com/pypa/pipenv/issues/2427),
  [#2434](https://github.com/pypa/pipenv/issues/2434),
  [#2436](https://github.com/pypa/pipenv/issues/2436)
- Added new flag `pipenv --support` to replace the diagnostic command `python -m pipenv.help`.  [#2477](https://github.com/pypa/pipenv/issues/2477),
  [#2478](https://github.com/pypa/pipenv/issues/2478)
- Improved import times and CLI run times with minor tweaks.  [#2485](https://github.com/pypa/pipenv/issues/2485)

## Bug Fixes

- Fixed an ongoing bug which sometimes resolved incompatible versions into the project Lockfile.  [#1901](https://github.com/pypa/pipenv/issues/1901)
- Fixed a bug which caused errors when creating virtualenvs which contained leading dash characters.  [#2415](https://github.com/pypa/pipenv/issues/2415)
- Fixed a logic error which caused `--deploy --system` to overwrite editable vcs packages in the Pipfile before installing, which caused any installation to fail by default.  [#2417](https://github.com/pypa/pipenv/issues/2417)
- Updated requirementslib to fix an issue with properly quoting markers in VCS requirements.  [#2419](https://github.com/pypa/pipenv/issues/2419)
- Installed new vendored jinja2 templates for `click-completion` which were causing template errors for users with completion enabled.  [#2422](https://github.com/pypa/pipenv/issues/2422)
- Added support for python 3.7 via a few small compatibility / bug fixes.  [#2427](https://github.com/pypa/pipenv/issues/2427)
- Fixed an issue reading package names from `setup.py` files in projects which imported utilities such as `versioneer`.  [#2433](https://github.com/pypa/pipenv/issues/2433)
- Pipenv will now ensure that its internal package names registry files are written with unicode strings.  [#2450](https://github.com/pypa/pipenv/issues/2450)
- Fixed a bug causing requirements input as relative paths to be output as absolute paths or URIs.
  Fixed a bug affecting normalization of `git+git@host` URLs.  [#2453](https://github.com/pypa/pipenv/issues/2453)
- Pipenv will now always use `pathlib2` for `Path` based filesystem interactions by default on `python<3.5`.  [#2454](https://github.com/pypa/pipenv/issues/2454)
- Fixed a bug which prevented passing proxy PyPI indexes set with `--pypi-mirror` from being passed to pip during virtualenv creation, which could cause the creation to freeze in some cases.  [#2462](https://github.com/pypa/pipenv/issues/2462)
- Using the `python -m pipenv.help` command will now use proper encoding for the host filesystem to avoid encoding issues.  [#2466](https://github.com/pypa/pipenv/issues/2466)
- The new `jinja2` templates for `click_completion` will now be included in pipenv source distributions.  [#2479](https://github.com/pypa/pipenv/issues/2479)
- Resolved a long-standing issue with re-using previously generated `InstallRequirement` objects for resolution which could cause `PKG-INFO` file information to be deleted, raising a `TypeError`.  [#2480](https://github.com/pypa/pipenv/issues/2480)
- Resolved an issue parsing usernames from private PyPI URIs in `Pipfiles` by updating `requirementslib`.  [#2484](https://github.com/pypa/pipenv/issues/2484)

## Vendored Libraries

- All calls to `pipenv shell` are now implemented from the ground up using [shellingham](https://github.com/sarugaku/shellingham), a custom library which was purpose built to handle edge cases and shell detection.  [#2371](https://github.com/pypa/pipenv/issues/2371)
- Updated requirementslib to fix an issue with properly quoting markers in VCS requirements.  [#2419](https://github.com/pypa/pipenv/issues/2419)
- Installed new vendored jinja2 templates for `click-completion` which were causing template errors for users with completion enabled.  [#2422](https://github.com/pypa/pipenv/issues/2422)
- Add patch to `prettytoml` to support Python 3.7.  [#2426](https://github.com/pypa/pipenv/issues/2426)
- Patched `prettytoml.AbstractTable._enumerate_items` to handle `StopIteration` errors in preparation of release of python 3.7.  [#2427](https://github.com/pypa/pipenv/issues/2427)
- Fixed an issue reading package names from `setup.py` files in projects which imported utilities such as `versioneer`.  [#2433](https://github.com/pypa/pipenv/issues/2433)
- Updated `requirementslib` to version `1.0.9`  [#2453](https://github.com/pypa/pipenv/issues/2453)
- Unraveled a lot of old, unnecessary patches to `pip-tools` which were causing non-deterministic resolution errors.  [#2480](https://github.com/pypa/pipenv/issues/2480)
- Resolved an issue parsing usernames from private PyPI URIs in `Pipfiles` by updating `requirementslib`.  [#2484](https://github.com/pypa/pipenv/issues/2484)

## Improved Documentation

- Added instructions for installing using Fedora's official repositories.  [#2404](https://github.com/pypa/pipenv/issues/2404)

# 2018.6.25 (2018-06-25)

## Features & Improvements

- Pipenv-created virtualenvs will now be associated with a `.project` folder
  (features can be implemented on top of this later or users may choose to use
  `pipenv-pipes` to take full advantage of this.)  [#1861](https://github.com/pypa/pipenv/issues/1861)
- Virtualenv names will now appear in prompts for most Windows users.  [#2167](https://github.com/pypa/pipenv/issues/2167)
- Added support for cmder shell paths with spaces.  [#2168](https://github.com/pypa/pipenv/issues/2168)
- Added nested JSON output to the `pipenv graph` command.  [#2199](https://github.com/pypa/pipenv/issues/2199)
- Dropped vendored pip 9 and vendored, patched, and migrated to pip 10. Updated
  patched piptools version.  [#2255](https://github.com/pypa/pipenv/issues/2255)
- PyPI mirror URLs can now be set to override instances of PyPI URLs by passing
  the `--pypi-mirror` argument from the command line or setting the
  `PIPENV_PYPI_MIRROR` environment variable.  [#2281](https://github.com/pypa/pipenv/issues/2281)
- Virtualenv activation lines will now avoid being written to some shell
  history files.  [#2287](https://github.com/pypa/pipenv/issues/2287)
- Pipenv will now only search for `requirements.txt` files when creating new
  projects, and during that time only if the user doesn't specify packages to
  pass in.  [#2309](https://github.com/pypa/pipenv/issues/2309)
- Added support for mounted drives via UNC paths.  [#2331](https://github.com/pypa/pipenv/issues/2331)
- Added support for Windows Subsystem for Linux bash shell detection.  [#2363](https://github.com/pypa/pipenv/issues/2363)
- Pipenv will now generate hashes much more quickly by resolving them in a
  single pass during locking.  [#2384](https://github.com/pypa/pipenv/issues/2384)
- `pipenv run` will now avoid spawning additional `COMSPEC` instances to
  run commands in when possible.  [#2385](https://github.com/pypa/pipenv/issues/2385)
- Massive internal improvements to requirements parsing codebase, resolver, and
  error messaging.  [#2388](https://github.com/pypa/pipenv/issues/2388)
- `pipenv check` now may take multiple of the additional argument
  `--ignore` which takes a parameter `cve_id` for the purpose of ignoring
  specific CVEs.  [#2408](https://github.com/pypa/pipenv/issues/2408)

## Behavior Changes

- Pipenv will now parse & capitalize `platform_python_implementation` markers
  .. warning:: This could cause an issue if you have an out of date `Pipfile`
  which lower-cases the comparison value (e.g. `cpython` instead of
  `CPython`).  [#2123](https://github.com/pypa/pipenv/issues/2123)
- Pipenv will now only search for `requirements.txt` files when creating new
  projects, and during that time only if the user doesn't specify packages to
  pass in.  [#2309](https://github.com/pypa/pipenv/issues/2309)

## Bug Fixes

- Massive internal improvements to requirements parsing codebase, resolver, and
  error messaging.  [#1962](https://github.com/pypa/pipenv/issues/1962),
  [#2186](https://github.com/pypa/pipenv/issues/2186),
  [#2263](https://github.com/pypa/pipenv/issues/2263),
  [#2312](https://github.com/pypa/pipenv/issues/2312)
- Pipenv will now parse & capitalize `platform_python_implementation`
  markers.  [#2123](https://github.com/pypa/pipenv/issues/2123)
- Fixed a bug with parsing and grouping old-style `setup.py` extras during
  resolution  [#2142](https://github.com/pypa/pipenv/issues/2142)
- Fixed a bug causing pipenv graph to throw unhelpful exceptions when running
  against empty or non-existent environments.  [#2161](https://github.com/pypa/pipenv/issues/2161)
- Fixed a bug which caused `--system` to incorrectly abort when users were in
  a virtualenv.  [#2181](https://github.com/pypa/pipenv/issues/2181)
- Removed vendored `cacert.pem` which could cause issues for some users with
  custom certificate settings.  [#2193](https://github.com/pypa/pipenv/issues/2193)
- Fixed a regression which led to direct invocations of `virtualenv`, rather
  than calling it by module.  [#2198](https://github.com/pypa/pipenv/issues/2198)
- Locking will now pin the correct VCS ref during `pipenv update` runs.
  Running `pipenv update` with a new vcs ref specified in the `Pipfile`
  will now properly obtain, resolve, and install the specified dependency at
  the specified ref.  [#2209](https://github.com/pypa/pipenv/issues/2209)
- `pipenv clean` will now correctly ignore comments from `pip freeze` when
  cleaning the environment.  [#2262](https://github.com/pypa/pipenv/issues/2262)
- Resolution bugs causing packages for incompatible python versions to be
  locked have been fixed.  [#2267](https://github.com/pypa/pipenv/issues/2267)
- Fixed a bug causing pipenv graph to fail to display sometimes.  [#2268](https://github.com/pypa/pipenv/issues/2268)
- Updated `requirementslib` to fix a bug in Pipfile parsing affecting
  relative path conversions.  [#2269](https://github.com/pypa/pipenv/issues/2269)
- Windows executable discovery now leverages `os.pathext`.  [#2298](https://github.com/pypa/pipenv/issues/2298)
- Fixed a bug which caused `--deploy --system` to inadvertently create a
  virtualenv before failing.  [#2301](https://github.com/pypa/pipenv/issues/2301)
- Fixed an issue which led to a failure to unquote special characters in file
  and wheel paths.  [#2302](https://github.com/pypa/pipenv/issues/2302)
- VCS dependencies are now manually obtained only if they do not match the
  requested ref.  [#2304](https://github.com/pypa/pipenv/issues/2304)
- Added error handling functionality to properly cope with single-digit
  `Requires-Python` metadata with no specifiers.  [#2377](https://github.com/pypa/pipenv/issues/2377)
- `pipenv update` will now always run the resolver and lock before ensuring
  dependencies are in sync with project Lockfile.  [#2379](https://github.com/pypa/pipenv/issues/2379)
- Resolved a bug in our patched resolvers which could cause nondeterministic
  resolution failures in certain conditions. Running `pipenv install` with no
  arguments in a project with only a `Pipfile` will now correctly lock first
  for dependency resolution before installing.  [#2384](https://github.com/pypa/pipenv/issues/2384)
- Patched `python-dotenv` to ensure that environment variables always get
  encoded to the filesystem encoding.  [#2386](https://github.com/pypa/pipenv/issues/2386)

## Improved Documentation

- Update documentation wording to clarify Pipenv's overall role in the packaging ecosystem.  [#2194](https://github.com/pypa/pipenv/issues/2194)
- Added contribution documentation and guidelines.  [#2205](https://github.com/pypa/pipenv/issues/2205)
- Added instructions for supervisord compatibility.  [#2215](https://github.com/pypa/pipenv/issues/2215)
- Fixed broken links to development philosophy and contribution documentation.  [#2248](https://github.com/pypa/pipenv/issues/2248)

## Vendored Libraries

- Removed vendored `cacert.pem` which could cause issues for some users with
  custom certificate settings.  [#2193](https://github.com/pypa/pipenv/issues/2193)

- Dropped vendored pip 9 and vendored, patched, and migrated to pip 10. Updated
  patched piptools version.  [#2255](https://github.com/pypa/pipenv/issues/2255)

- Updated `requirementslib` to fix a bug in Pipfile parsing affecting
  relative path conversions.  [#2269](https://github.com/pypa/pipenv/issues/2269)

- Added custom shell detection library `shellingham`, a port of our changes
  to `pew`.  [#2363](https://github.com/pypa/pipenv/issues/2363)

- Patched `python-dotenv` to ensure that environment variables always get
  encoded to the filesystem encoding.  [#2386](https://github.com/pypa/pipenv/issues/2386)

- Updated vendored libraries. The following vendored libraries were updated:

  - distlib from version `0.2.6` to `0.2.7`.
  - jinja2 from version `2.9.5` to `2.10`.
  - pathlib2 from version `2.1.0` to `2.3.2`.
  - parse from version `2.8.0` to `2.8.4`.
  - pexpect from version `2.5.2` to `2.6.0`.
  - requests from version `2.18.4` to `2.19.1`.
  - idna from version `2.6` to `2.7`.
  - certifi from version `2018.1.16` to `2018.4.16`.
  - packaging from version `16.8` to `17.1`.
  - six from version `1.10.0` to `1.11.0`.
  - requirementslib from version `0.2.0` to `1.0.1`.

  In addition, scandir was vendored and patched to avoid importing host system binaries when falling back to pathlib2.  [#2368](https://github.com/pypa/pipenv/issues/2368)
