2020.6.2 (2020-06-02)
=====================

Features & Improvements
-----------------------

- Pipenv will now detect existing ``venv`` and ``virtualenv`` based virtual environments more robustly.  `#4276 <https://github.com/pypa/pipenv/issues/4276>`_

Bug Fixes
---------

- ``+`` signs in URL authentication fragments will no longer be incorrectly replaced with space ( `` `` ) characters.  `#4271 <https://github.com/pypa/pipenv/issues/4271>`_
- Fixed a regression which caused Pipenv to fail when running under ``/``.  `#4273 <https://github.com/pypa/pipenv/issues/4273>`_
- ``setup.py`` files with ``version`` variables read from ``os.environ`` are now able to be parsed successfully.  `#4274 <https://github.com/pypa/pipenv/issues/4274>`_
- Fixed a bug which caused Pipenv to fail to install packages in a virtual environment if those packages were already present in the system global environment.  `#4276 <https://github.com/pypa/pipenv/issues/4276>`_
- Fix a bug that caused non-specific versions to be pinned in ``Pipfile.lock``.  `#4278 <https://github.com/pypa/pipenv/issues/4278>`_
- Corrected a missing exception import and invalid function call invocations in ``pipenv.cli.command``.  `#4286 <https://github.com/pypa/pipenv/issues/4286>`_
- Fixed an issue with resolving packages with names defined by function calls in ``setup.py``.  `#4292 <https://github.com/pypa/pipenv/issues/4292>`_
- Fixed a regression with installing the current directory, or ``.``, inside a ``venv`` based virtual environment.  `#4295 <https://github.com/pypa/pipenv/issues/4295>`_
- Fixed a bug with the discovery of python paths on Windows which could prevent installation of environments during ``pipenv install``.  `#4296 <https://github.com/pypa/pipenv/issues/4296>`_
- Fixed an issue in the ``requirementslib`` AST parser which prevented parsing of ``setup.py`` files for dependency metadata.  `#4298 <https://github.com/pypa/pipenv/issues/4298>`_
- Fix a bug where Pipenv doesn't realize the session is interactive  `#4305 <https://github.com/pypa/pipenv/issues/4305>`_

Vendored Libraries
------------------

- Updated requirementslib to version ``1.5.11``.  `#4292 <https://github.com/pypa/pipenv/issues/4292>`_
- Updated vendored dependencies:
    - **pythonfinder**: ``1.2.2`` => ``1.2.4``
    - **requirementslib**: ``1.5.9`` => ``1.5.10``  `#4302 <https://github.com/pypa/pipenv/issues/4302>`_


2020.5.28 (2020-05-28)
======================

Features & Improvements
-----------------------

- ``pipenv install`` and ``pipenv sync`` will no longer attempt to install satisfied dependencies during installation.  `#3057 <https://github.com/pypa/pipenv/issues/3057>`_,
  `#3506 <https://github.com/pypa/pipenv/issues/3506>`_
- Added support for resolution of direct-url dependencies in ``setup.py`` files to respect ``PEP-508`` style URL dependencies.  `#3148 <https://github.com/pypa/pipenv/issues/3148>`_
- Added full support for resolution of all dependency types including direct URLs, zip archives, tarballs, etc.

  - Improved error handling and formatting.

  - Introduced improved cross platform stream wrappers for better ``stdout`` and ``stderr`` consistency.  `#3298 <https://github.com/pypa/pipenv/issues/3298>`_
- For consistency with other commands and the ``--dev`` option
  description, ``pipenv lock --requirements --dev`` now emits
  both default and development dependencies.
  The new ``--dev-only`` option requests the previous
  behaviour (e.g. to generate a ``dev-requirements.txt`` file).  `#3316 <https://github.com/pypa/pipenv/issues/3316>`_
- Pipenv will now successfully recursively lock VCS sub-dependencies.  `#3328 <https://github.com/pypa/pipenv/issues/3328>`_
- Added support for ``--verbose`` output to ``pipenv run``.  `#3348 <https://github.com/pypa/pipenv/issues/3348>`_
- Pipenv will now discover and resolve the intrinsic dependencies of **all** VCS dependencies, whether they are editable or not, to prevent resolution conflicts.  `#3368 <https://github.com/pypa/pipenv/issues/3368>`_
- Added a new environment variable, ``PIPENV_RESOLVE_VCS``, to toggle dependency resolution off for non-editable VCS, file, and URL based dependencies.  `#3577 <https://github.com/pypa/pipenv/issues/3577>`_
- Added the ability for Windows users to enable emojis by setting ``PIPENV_HIDE_EMOJIS=0``.  `#3595 <https://github.com/pypa/pipenv/issues/3595>`_
- Allow overriding PIPENV_INSTALL_TIMEOUT environment variable (in seconds).  `#3652 <https://github.com/pypa/pipenv/issues/3652>`_
- Allow overriding PIP_EXISTS_ACTION evironment variable (value is passed to pip install). 
  Possible values here: https://pip.pypa.io/en/stable/reference/pip/#exists-action-option
  Useful when you need to `PIP_EXISTS_ACTION=i` (ignore existing packages) - great for CI environments, where you need really fast setup.  `#3738 <https://github.com/pypa/pipenv/issues/3738>`_
- Pipenv will no longer forcibly override ``PIP_NO_DEPS`` on all vcs and file dependencies as resolution happens on these in a pre-lock step.  `#3763 <https://github.com/pypa/pipenv/issues/3763>`_
- Improved verbose logging output during ``pipenv lock`` will now stream output to the console while maintaining a spinner.  `#3810 <https://github.com/pypa/pipenv/issues/3810>`_
- Added support for automatic python installs via ``asdf`` and associated ``PIPENV_DONT_USE_ASDF`` environment variable.  `#4018 <https://github.com/pypa/pipenv/issues/4018>`_
- Pyenv/asdf can now be used whether or not they are available on PATH. Setting PYENV_ROOT/ASDF_DIR in a Pipenv's .env allows Pipenv to install an interpreter without any shell customizations, so long as pyenv/asdf is installed.  `#4245 <https://github.com/pypa/pipenv/issues/4245>`_
- Added ``--key`` command line parameter for including personal PyUp.io API tokens when running ``pipenv check``.  `#4257 <https://github.com/pypa/pipenv/issues/4257>`_

Behavior Changes
----------------

- Make conservative checks of known exceptions when subprocess returns output, so user won't see the whole traceback - just the error.  `#2553 <https://github.com/pypa/pipenv/issues/2553>`_
- Do not touch Pipfile early and rely on it so that one can do ``pipenv sync`` without a Pipfile.  `#3386 <https://github.com/pypa/pipenv/issues/3386>`_
- Re-enable ``--help`` option for ``pipenv run`` command.  `#3844 <https://github.com/pypa/pipenv/issues/3844>`_
- Make sure ``pipenv lock -r --pypi-mirror {MIRROR_URL}`` will respect the pypi-mirror in requirements output.  `#4199 <https://github.com/pypa/pipenv/issues/4199>`_

Bug Fixes
---------

- Raise `PipenvUsageError` when [[source]] does not contain url field.  `#2373 <https://github.com/pypa/pipenv/issues/2373>`_
- Fixed a bug which caused editable package resolution to sometimes fail with an unhelpful setuptools-related error message.  `#2722 <https://github.com/pypa/pipenv/issues/2722>`_
- Fixed an issue which caused errors due to reliance on the system utilities ``which`` and ``where`` which may not always exist on some systems.
  - Fixed a bug which caused periodic failures in python discovery when executables named ``python`` were not present on the target ``$PATH``.  `#2783 <https://github.com/pypa/pipenv/issues/2783>`_
- Dependency resolution now writes hashes for local and remote files to the lockfile.  `#3053 <https://github.com/pypa/pipenv/issues/3053>`_
- Fixed a bug which prevented ``pipenv graph`` from correctly showing all dependencies when running from within ``pipenv shell``.  `#3071 <https://github.com/pypa/pipenv/issues/3071>`_
- Fixed resolution of direct-url dependencies in ``setup.py`` files to respect ``PEP-508`` style URL dependencies.  `#3148 <https://github.com/pypa/pipenv/issues/3148>`_
- Fixed a bug which caused failures in warning reporting when running pipenv inside a virtualenv under some circumstances.

  - Fixed a bug with package discovery when running ``pipenv clean``.  `#3298 <https://github.com/pypa/pipenv/issues/3298>`_
- Quote command arguments with carets (``^``) on Windows to work around unintended shell escapes.  `#3307 <https://github.com/pypa/pipenv/issues/3307>`_
- Handle alternate names for UTF-8 encoding.  `#3313 <https://github.com/pypa/pipenv/issues/3313>`_
- Abort pipenv before adding the non-exist package to Pipfile.  `#3318 <https://github.com/pypa/pipenv/issues/3318>`_
- Don't normalize the package name user passes in.  `#3324 <https://github.com/pypa/pipenv/issues/3324>`_
- Fix a bug where custom virtualenv can not be activated with pipenv shell  `#3339 <https://github.com/pypa/pipenv/issues/3339>`_
- Fix a bug that ``--site-packages`` flag is not recognized.  `#3351 <https://github.com/pypa/pipenv/issues/3351>`_
- Fix a bug where pipenv --clear is not working  `#3353 <https://github.com/pypa/pipenv/issues/3353>`_
- Fix unhashable type error during ``$ pipenv install --selective-upgrade``  `#3384 <https://github.com/pypa/pipenv/issues/3384>`_
- Dependencies with direct ``PEP508`` compliant VCS URLs specified in their ``install_requires`` will now be successfully locked during the resolution process.  `#3396 <https://github.com/pypa/pipenv/issues/3396>`_
- Fixed a keyerror which could occur when locking VCS dependencies in some cases.  `#3404 <https://github.com/pypa/pipenv/issues/3404>`_
- Fixed a bug that ``ValidationError`` is thrown when some fields are missing in source section.  `#3427 <https://github.com/pypa/pipenv/issues/3427>`_
- Updated the index names in lock file when source name in Pipfile is changed.  `#3449 <https://github.com/pypa/pipenv/issues/3449>`_
- Fixed an issue which caused ``pipenv install --help`` to show duplicate entries for ``--pre``.  `#3479 <https://github.com/pypa/pipenv/issues/3479>`_
- Fix bug causing ``[SSL: CERTIFICATE_VERIFY_FAILED]`` when Pipfile ``[[source]]`` has verify_ssl=false and url with custom port.  `#3502 <https://github.com/pypa/pipenv/issues/3502>`_
- Fix ``sync --sequential`` ignoring ``pip install`` errors and logs.  `#3537 <https://github.com/pypa/pipenv/issues/3537>`_
- Fix the issue that lock file can't be created when ``PIPENV_PIPFILE`` is not under working directory.  `#3584 <https://github.com/pypa/pipenv/issues/3584>`_
- Pipenv will no longer inadvertently set ``editable=True`` on all vcs dependencies.  `#3647 <https://github.com/pypa/pipenv/issues/3647>`_
- The ``--keep-outdated`` argument to ``pipenv install`` and ``pipenv lock`` will now drop specifier constraints when encountering editable dependencies.
  - In addition, ``--keep-outdated`` will retain specifiers that would otherwise be dropped from any entries that have not been updated.  `#3656 <https://github.com/pypa/pipenv/issues/3656>`_
- Fixed a bug which sometimes caused pipenv to fail to respect the ``--site-packages`` flag when passed with ``pipenv install``.  `#3718 <https://github.com/pypa/pipenv/issues/3718>`_
- Normalize the package names to lowercase when comparing used and in-Pipfile packages.  `#3745 <https://github.com/pypa/pipenv/issues/3745>`_
- ``pipenv update --outdated`` will now correctly handle comparisons between pre/post-releases and normal releases.  `#3766 <https://github.com/pypa/pipenv/issues/3766>`_
- Fixed a ``KeyError`` which could occur when pinning outdated VCS dependencies via ``pipenv lock --keep-outdated``.  `#3768 <https://github.com/pypa/pipenv/issues/3768>`_
- Resolved an issue which caused resolution to fail when encountering poorly formatted ``python_version`` markers in ``setup.py`` and ``setup.cfg`` files.  `#3786 <https://github.com/pypa/pipenv/issues/3786>`_
- Fix a bug that installation errors are displayed as a list.  `#3794 <https://github.com/pypa/pipenv/issues/3794>`_
- Update ``pythonfinder`` to fix a problem that ``python.exe`` will be mistakenly chosen for
  virtualenv creation under WSL.  `#3807 <https://github.com/pypa/pipenv/issues/3807>`_
- Fixed several bugs which could prevent editable VCS dependencies from being installed into target environments, even when reporting successful installation.  `#3809 <https://github.com/pypa/pipenv/issues/3809>`_
- ``pipenv check --system`` should find the correct Python interpreter when ``python`` does not exist on the system.  `#3819 <https://github.com/pypa/pipenv/issues/3819>`_
- Resolve the symlinks when the path is absolute.  `#3842 <https://github.com/pypa/pipenv/issues/3842>`_
- Pass ``--pre`` and ``--clear`` options to ``pipenv update --outdated``.  `#3879 <https://github.com/pypa/pipenv/issues/3879>`_
- Fixed a bug which prevented resolution of direct URL dependencies which have PEP508 style direct url VCS sub-dependencies with subdirectories.  `#3976 <https://github.com/pypa/pipenv/issues/3976>`_
- Honor PIPENV_SPINNER environment variable  `#4045 <https://github.com/pypa/pipenv/issues/4045>`_
- Fixed an issue with ``pipenv check`` failing due to an invalid API key from ``pyup.io``.  `#4188 <https://github.com/pypa/pipenv/issues/4188>`_
- Fixed a bug which caused versions from VCS dependencies to be included in ``Pipfile.lock`` inadvertently.  `#4217 <https://github.com/pypa/pipenv/issues/4217>`_
- Fixed a bug which caused pipenv to search non-existent virtual environments for ``pip`` when installing using ``--system``.  `#4220 <https://github.com/pypa/pipenv/issues/4220>`_
- ``Requires-Python`` values specifying constraint versions of python starting from ``1.x`` will now be parsed successfully.  `#4226 <https://github.com/pypa/pipenv/issues/4226>`_
- Fix a bug of ``pipenv update --outdated`` that can't print output correctly.  `#4229 <https://github.com/pypa/pipenv/issues/4229>`_
- Fixed a bug which caused pipenv to prefer source distributions over wheels from ``PyPI`` during the dependency resolution phase.
  Fixed an issue which prevented proper build isolation using ``pep517`` based builders during dependency resolution.  `#4231 <https://github.com/pypa/pipenv/issues/4231>`_
- Don't fallback to system Python when no matching Python version is found.  `#4232 <https://github.com/pypa/pipenv/issues/4232>`_

Vendored Libraries
------------------

- Updated vendored dependencies:

    - **attrs**: ``18.2.0`` => ``19.1.0``
    - **certifi**: ``2018.10.15`` => ``2019.3.9``
    - **cached_property**: ``1.4.3`` => ``1.5.1``
    - **cerberus**: ``1.2.0`` => ``1.3.1``
    - **click-completion**: ``0.5.0`` => ``0.5.1``
    - **colorama**: ``0.3.9`` => ``0.4.1``
    - **distlib**: ``0.2.8`` => ``0.2.9``
    - **idna**: ``2.7`` => ``2.8``
    - **jinja2**: ``2.10.0`` => ``2.10.1``
    - **markupsafe**: ``1.0`` => ``1.1.1``
    - **orderedmultidict**: ``(new)`` => ``1.0``
    - **packaging**: ``18.0`` => ``19.0``
    - **parse**: ``1.9.0`` => ``1.12.0``
    - **pathlib2**: ``2.3.2`` => ``2.3.3``
    - **pep517**: ``(new)`` => ``0.5.0``
    - **pexpect**: ``4.6.0`` => ``4.7.0``
    - **pipdeptree**: ``0.13.0`` => ``0.13.2``
    - **pyparsing**: ``2.2.2`` => ``2.3.1``
    - **python-dotenv**: ``0.9.1`` => ``0.10.2``
    - **pythonfinder**: ``1.1.10`` => ``1.2.1``
    - **pytoml**: ``(new)`` => ``0.1.20``
    - **requests**: ``2.20.1`` => ``2.21.0``
    - **requirementslib**: ``1.3.3`` => ``1.5.0``
    - **scandir**: ``1.9.0`` => ``1.10.0``
    - **shellingham**: ``1.2.7`` => ``1.3.1``
    - **six**: ``1.11.0`` => ``1.12.0``
    - **tomlkit**: ``0.5.2`` => ``0.5.3``
    - **urllib3**: ``1.24`` => ``1.25.2``
    - **vistir**: ``0.3.0`` => ``0.4.1``
    - **yaspin**: ``0.14.0`` => ``0.14.3``

  - Removed vendored dependency **cursor**.  `#3298 <https://github.com/pypa/pipenv/issues/3298>`_
- Updated ``pip_shims`` to support ``--outdated`` with new pip versions.  `#3766 <https://github.com/pypa/pipenv/issues/3766>`_
- Update vendored dependencies and invocations

  - Update vendored and patched dependencies
    - Update patches on ``piptools``, ``pip``, ``pip-shims``, ``tomlkit`
  - Fix invocations of dependencies
    - Fix custom ``InstallCommand` instantiation
    - Update ``PackageFinder` usage
    - Fix ``Bool` stringify attempts from ``tomlkit`

  Updated vendored dependencies:
    - **attrs**: ```18.2.0`` => ```19.1.0``
    - **certifi**: ```2018.10.15`` => ```2019.3.9``
    - **cached_property**: ```1.4.3`` => ```1.5.1``
    - **cerberus**: ```1.2.0`` => ```1.3.1``
    - **click**: ```7.0.0`` => ```7.1.1``
    - **click-completion**: ```0.5.0`` => ```0.5.1``
    - **colorama**: ```0.3.9`` => ```0.4.3``
    - **contextlib2**: ```(new)`` => ```0.6.0.post1``
    - **distlib**: ```0.2.8`` => ```0.2.9``
    - **funcsigs**: ```(new)`` => ```1.0.2``
    - **importlib_metadata** ```1.3.0`` => ```1.5.1``
    - **importlib-resources**:  ```(new)`` => ```1.4.0``
    - **idna**: ```2.7`` => ```2.9``
    - **jinja2**: ```2.10.0`` => ```2.11.1``
    - **markupsafe**: ```1.0`` => ```1.1.1``
    - **more-itertools**: ```(new)`` => ```5.0.0``
    - **orderedmultidict**: ```(new)`` => ```1.0``
    - **packaging**: ```18.0`` => ```19.0``
    - **parse**: ```1.9.0`` => ```1.15.0``
    - **pathlib2**: ```2.3.2`` => ```2.3.3``
    - **pep517**: ```(new)`` => ```0.5.0``
    - **pexpect**: ```4.6.0`` => ```4.8.0``
    - **pip-shims**: ```0.2.0`` => ```0.5.1``
    - **pipdeptree**: ```0.13.0`` => ```0.13.2``
    - **pyparsing**: ```2.2.2`` => ```2.4.6``
    - **python-dotenv**: ```0.9.1`` => ```0.10.2``
    - **pythonfinder**: ```1.1.10`` => ```1.2.2``
    - **pytoml**: ```(new)`` => ```0.1.20``
    - **requests**: ```2.20.1`` => ```2.23.0``
    - **requirementslib**: ```1.3.3`` => ```1.5.4``
    - **scandir**: ```1.9.0`` => ```1.10.0``
    - **shellingham**: ```1.2.7`` => ```1.3.2``
    - **six**: ```1.11.0`` => ```1.14.0``
    - **tomlkit**: ```0.5.2`` => ```0.5.11``
    - **urllib3**: ```1.24`` => ```1.25.8``
    - **vistir**: ```0.3.0`` => ```0.5.0``
    - **yaspin**: ```0.14.0`` => ```0.14.3``
    - **zipp**: ```0.6.0``

  - Removed vendored dependency **cursor**.  `#4169 <https://github.com/pypa/pipenv/issues/4169>`_
- Add and update vendored dependencies to accommodate ``safety`` vendoring:
  - **safety** ``(none)`` => ``1.8.7``
  - **dparse** ``(none)`` => ``0.5.0``
  - **pyyaml** ``(none)`` => ``5.3.1``
  - **urllib3** ``1.25.8`` => ``1.25.9``
  - **certifi** ``2019.11.28`` => ``2020.4.5.1``
  - **pyparsing** ``2.4.6`` => ``2.4.7``
  - **resolvelib** ``0.2.2`` => ``0.3.0``
  - **importlib-metadata** ``1.5.1`` => ``1.6.0``
  - **pip-shims** ``0.5.1`` => ``0.5.2``
  - **requirementslib** ``1.5.5`` => ``1.5.6``  `#4188 <https://github.com/pypa/pipenv/issues/4188>`_
- Updated vendored ``pip`` => ``20.0.2`` and ``pip-tools`` => ``5.0.0``.  `#4215 <https://github.com/pypa/pipenv/issues/4215>`_
- Updated vendored dependencies to latest versions for security and bug fixes:

  - **requirementslib** ``1.5.8`` => ``1.5.9``
  - **vistir** ``0.5.0`` => ``0.5.1``
  - **jinja2** ``2.11.1`` => ``2.11.2``
  - **click** ``7.1.1`` => ``7.1.2``
  - **dateutil** ``(none)`` => ``2.8.1``
  - **backports.functools_lru_cache** ``1.5.0`` => ``1.6.1``
  - **enum34** ``1.1.6`` => ``1.1.10``
  - **toml** ``0.10.0`` => ``0.10.1``
  - **importlib_resources** ``1.4.0`` => ``1.5.0``  `#4226 <https://github.com/pypa/pipenv/issues/4226>`_
- Changed attrs import path in vendored dependencies to always import from ``pipenv.vendor``.  `#4267 <https://github.com/pypa/pipenv/issues/4267>`_

Improved Documentation
----------------------

- Added documenation about variable expansion in ``Pipfile`` entries.  `#2317 <https://github.com/pypa/pipenv/issues/2317>`_
- Consolidate all contributing docs in the rst file  `#3120 <https://github.com/pypa/pipenv/issues/3120>`_
- Update the out-dated manual page.  `#3246 <https://github.com/pypa/pipenv/issues/3246>`_
- Move CLI docs to its own page.  `#3346 <https://github.com/pypa/pipenv/issues/3346>`_
- Replace (non-existant) video on docs index.rst with equivalent gif.  `#3499 <https://github.com/pypa/pipenv/issues/3499>`_
- Clarify wording in Basic Usage example on using double quotes to escape shell redirection  `#3522 <https://github.com/pypa/pipenv/issues/3522>`_
- Ensure docs show navigation on small-screen devices  `#3527 <https://github.com/pypa/pipenv/issues/3527>`_
- Added a link to the TOML Spec under General Recommendations & Version Control to clarify how Pipfiles should be written.  `#3629 <https://github.com/pypa/pipenv/issues/3629>`_
- Updated the documentation with the new ``pytest`` entrypoint.  `#3759 <https://github.com/pypa/pipenv/issues/3759>`_
- Fix link to GIF in README.md demonstrating Pipenv's usage, and add descriptive alt text.  `#3911 <https://github.com/pypa/pipenv/issues/3911>`_
- Added a line describing potential issues in fancy extension.  `#3912 <https://github.com/pypa/pipenv/issues/3912>`_
- Documental description of how Pipfile works and association with Pipenv.  `#3913 <https://github.com/pypa/pipenv/issues/3913>`_
- Clarify the proper value of ``python_version`` and ``python_full_version``.  `#3914 <https://github.com/pypa/pipenv/issues/3914>`_
- Write description for --deploy extension and few extensions differences.  `#3915 <https://github.com/pypa/pipenv/issues/3915>`_
- More documentation for ``.env`` files  `#4100 <https://github.com/pypa/pipenv/issues/4100>`_
- Updated documentation to point to working links.  `#4137 <https://github.com/pypa/pipenv/issues/4137>`_
- Replace docs.pipenv.org with pipenv.pypa.io  `#4167 <https://github.com/pypa/pipenv/issues/4167>`_
- Added functionality to check spelling in documentation and cleaned up existing typographical issues.  `#4209 <https://github.com/pypa/pipenv/issues/4209>`_


2018.11.26 (2018-11-26)
=======================

Bug Fixes
---------

- Environment variables are expanded correctly before running scripts on POSIX.  `#3178 <https://github.com/pypa/pipenv/issues/3178>`_
- Pipenv will no longer disable user-mode installation when the ``--system`` flag is passed in.  `#3222 <https://github.com/pypa/pipenv/issues/3222>`_
- Fixed an issue with attempting to render unicode output in non-unicode locales.  `#3223 <https://github.com/pypa/pipenv/issues/3223>`_
- Fixed a bug which could cause failures to occur when parsing python entries from global pyenv version files.  `#3224 <https://github.com/pypa/pipenv/issues/3224>`_
- Fixed an issue which prevented the parsing of named extras sections from certain ``setup.py`` files.  `#3230 <https://github.com/pypa/pipenv/issues/3230>`_
- Correctly detect the virtualenv location inside an activated virtualenv.  `#3231 <https://github.com/pypa/pipenv/issues/3231>`_
- Fixed a bug which caused spinner frames to be written to standard output during locking operations which could cause redirection pipes to fail.  `#3239 <https://github.com/pypa/pipenv/issues/3239>`_
- Fixed a bug that editable packages can't be uninstalled correctly.  `#3240 <https://github.com/pypa/pipenv/issues/3240>`_
- Corrected an issue with installation timeouts which caused dependency resolution to fail for longer duration resolution steps.  `#3244 <https://github.com/pypa/pipenv/issues/3244>`_
- Adding normal pep 508 compatible markers is now fully functional when using VCS dependencies.  `#3249 <https://github.com/pypa/pipenv/issues/3249>`_
- Updated ``requirementslib`` and ``pythonfinder`` for multiple bug fixes.  `#3254 <https://github.com/pypa/pipenv/issues/3254>`_
- Pipenv will now ignore hashes when installing with ``--skip-lock``.  `#3255 <https://github.com/pypa/pipenv/issues/3255>`_
- Fixed an issue where pipenv could crash when multiple pipenv processes attempted to create the same directory.  `#3257 <https://github.com/pypa/pipenv/issues/3257>`_
- Fixed an issue which sometimes prevented successful creation of a project Pipfile.  `#3260 <https://github.com/pypa/pipenv/issues/3260>`_
- ``pipenv install`` will now unset the ``PYTHONHOME`` environment variable when not combined with ``--system``.  `#3261 <https://github.com/pypa/pipenv/issues/3261>`_
- Pipenv will ensure that warnings do not interfere with the resolution process by suppressing warnings' usage of standard output and writing to standard error instead.  `#3273 <https://github.com/pypa/pipenv/issues/3273>`_
- Fixed an issue which prevented variables from the environment, such as ``PIPENV_DEV`` or ``PIPENV_SYSTEM``, from being parsed and implemented correctly.  `#3278 <https://github.com/pypa/pipenv/issues/3278>`_
- Clear pythonfinder cache after Python install.  `#3287 <https://github.com/pypa/pipenv/issues/3287>`_
- Fixed a race condition in hash resolution for dependencies for certain dependencies with missing cache entries or fresh Pipenv installs.  `#3289 <https://github.com/pypa/pipenv/issues/3289>`_
- Pipenv will now respect top-level pins over VCS dependency locks.  `#3296 <https://github.com/pypa/pipenv/issues/3296>`_

Vendored Libraries
------------------

- Update vendored dependencies to resolve resolution output parsing and python finding:
    - ``pythonfinder 1.1.9 -> 1.1.10``
    - ``requirementslib 1.3.1 -> 1.3.3``
    - ``vistir 0.2.3 -> 0.2.5``  `#3280 <https://github.com/pypa/pipenv/issues/3280>`_


2018.11.14 (2018-11-14)
=======================

Features & Improvements
-----------------------

- Improved exceptions and error handling on failures.  `#1977 <https://github.com/pypa/pipenv/issues/1977>`_
- Added persistent settings for all CLI flags via ``PIPENV_{FLAG_NAME}`` environment variables by enabling ``auto_envvar_prefix=PIPENV`` in click (implements PEEP-0002).  `#2200 <https://github.com/pypa/pipenv/issues/2200>`_
- Added improved messaging about available but skipped updates due to dependency conflicts when running ``pipenv update --outdated``.  `#2411 <https://github.com/pypa/pipenv/issues/2411>`_
- Added environment variable ``PIPENV_PYUP_API_KEY`` to add ability
  to override the bundled PyUP.io API key.  `#2825 <https://github.com/pypa/pipenv/issues/2825>`_
- Added additional output to ``pipenv update --outdated`` to indicate that the operation succeeded and all packages were already up to date.  `#2828 <https://github.com/pypa/pipenv/issues/2828>`_
- Updated ``crayons`` patch to enable colors on native powershell but swap native blue for magenta.  `#3020 <https://github.com/pypa/pipenv/issues/3020>`_
- Added support for ``--bare`` to ``pipenv clean``, and fixed ``pipenv sync --bare`` to actually reduce output.  `#3041 <https://github.com/pypa/pipenv/issues/3041>`_
- Added windows-compatible spinner via upgraded ``vistir`` dependency.  `#3089 <https://github.com/pypa/pipenv/issues/3089>`_
- - Added support for python installations managed by ``asdf``.  `#3096 <https://github.com/pypa/pipenv/issues/3096>`_
- Improved runtime performance of no-op commands such as ``pipenv --venv`` by around 2/3.  `#3158 <https://github.com/pypa/pipenv/issues/3158>`_
- Do not show error but success for running ``pipenv uninstall --all`` in a fresh virtual environment.  `#3170 <https://github.com/pypa/pipenv/issues/3170>`_
- Improved asynchronous installation and error handling via queued subprocess parallelization.  `#3217 <https://github.com/pypa/pipenv/issues/3217>`_

Bug Fixes
---------

- Remote non-PyPI artifacts and local wheels and artifacts will now include their own hashes rather than including hashes from ``PyPI``.  `#2394 <https://github.com/pypa/pipenv/issues/2394>`_
- Non-ascii characters will now be handled correctly when parsed by pipenv's ``ToML`` parsers.  `#2737 <https://github.com/pypa/pipenv/issues/2737>`_
- Updated ``pipenv uninstall`` to respect the ``--skip-lock`` argument.  `#2848 <https://github.com/pypa/pipenv/issues/2848>`_
- Fixed a bug which caused uninstallation to sometimes fail to successfully remove packages from ``Pipfiles`` with comments on preceding or following lines.  `#2885 <https://github.com/pypa/pipenv/issues/2885>`_,
  `#3099 <https://github.com/pypa/pipenv/issues/3099>`_
- Pipenv will no longer fail when encountering python versions on Windows that have been uninstalled.  `#2983 <https://github.com/pypa/pipenv/issues/2983>`_
- Fixed unnecessary extras are added when translating markers  `#3026 <https://github.com/pypa/pipenv/issues/3026>`_
- Fixed a virtualenv creation issue which could cause new virtualenvs to inadvertently attempt to read and write to global site packages.  `#3047 <https://github.com/pypa/pipenv/issues/3047>`_
- Fixed an issue with virtualenv path derivation which could cause errors, particularly for users on WSL bash.  `#3055 <https://github.com/pypa/pipenv/issues/3055>`_
- Fixed a bug which caused ``Unexpected EOF`` errors to be thrown when ``pip`` was waiting for input from users who had put login credentials in environment variables.  `#3088 <https://github.com/pypa/pipenv/issues/3088>`_
- Fixed a bug in ``requirementslib`` which prevented successful installation from mercurial repositories.  `#3090 <https://github.com/pypa/pipenv/issues/3090>`_
- Fixed random resource warnings when using pyenv or any other subprocess calls.  `#3094 <https://github.com/pypa/pipenv/issues/3094>`_
- - Fixed a bug which sometimes prevented cloning and parsing ``mercurial`` requirements.  `#3096 <https://github.com/pypa/pipenv/issues/3096>`_
- Fixed an issue in ``delegator.py`` related to subprocess calls when using ``PopenSpawn`` to stream output, which sometimes threw unexpected ``EOF`` errors.  `#3102 <https://github.com/pypa/pipenv/issues/3102>`_,
  `#3114 <https://github.com/pypa/pipenv/issues/3114>`_,
  `#3117 <https://github.com/pypa/pipenv/issues/3117>`_
- Fix the path casing issue that makes `pipenv clean` fail on Windows  `#3104 <https://github.com/pypa/pipenv/issues/3104>`_
- Pipenv will avoid leaving build artifacts in the current working directory.  `#3106 <https://github.com/pypa/pipenv/issues/3106>`_
- Fixed issues with broken subprocess calls leaking resource handles and causing random and sporadic failures.  `#3109 <https://github.com/pypa/pipenv/issues/3109>`_
- Fixed an issue which caused ``pipenv clean`` to sometimes clean packages from the base ``site-packages`` folder or fail entirely.  `#3113 <https://github.com/pypa/pipenv/issues/3113>`_
- Updated ``pythonfinder`` to correct an issue with unnesting of nested paths when searching for python versions.  `#3121 <https://github.com/pypa/pipenv/issues/3121>`_
- Added additional logic for ignoring and replacing non-ascii characters when formatting console output on non-UTF-8 systems.  `#3131 <https://github.com/pypa/pipenv/issues/3131>`_
- Fix virtual environment discovery when ``PIPENV_VENV_IN_PROJECT`` is set, but the in-project `.venv` is a file.  `#3134 <https://github.com/pypa/pipenv/issues/3134>`_
- Hashes for remote and local non-PyPI artifacts will now be included in ``Pipfile.lock`` during resolution.  `#3145 <https://github.com/pypa/pipenv/issues/3145>`_
- Fix project path hashing logic in purpose to prevent collisions of virtual environments.  `#3151 <https://github.com/pypa/pipenv/issues/3151>`_
- Fix package installation when the virtual environment path contains parentheses.  `#3158 <https://github.com/pypa/pipenv/issues/3158>`_
- Azure Pipelines YAML files are updated to use the latest syntax and product name.  `#3164 <https://github.com/pypa/pipenv/issues/3164>`_
- Fixed new spinner success message to write only one success message during resolution.  `#3183 <https://github.com/pypa/pipenv/issues/3183>`_
- Pipenv will now correctly respect the ``--pre`` option when used with ``pipenv install``.  `#3185 <https://github.com/pypa/pipenv/issues/3185>`_
- Fix a bug where exception is raised when run pipenv graph in a project without created virtualenv  `#3201 <https://github.com/pypa/pipenv/issues/3201>`_
- When sources are missing names, names will now be derived from the supplied URL.  `#3216 <https://github.com/pypa/pipenv/issues/3216>`_

Vendored Libraries
------------------

- Updated ``pythonfinder`` to correct an issue with unnesting of nested paths when searching for python versions.  `#3061 <https://github.com/pypa/pipenv/issues/3061>`_,
  `#3121 <https://github.com/pypa/pipenv/issues/3121>`_
- Updated vendored dependencies:
    - ``certifi 2018.08.24 => 2018.10.15``
    - ``urllib3 1.23 => 1.24``
    - ``requests 2.19.1 => 2.20.0``
    - ``shellingham ``1.2.6 => 1.2.7``
    - ``tomlkit 0.4.4. => 0.4.6``
    - ``vistir 0.1.6 => 0.1.8``
    - ``pythonfinder 0.1.2 => 0.1.3``
    - ``requirementslib 1.1.9 => 1.1.10``
    - ``backports.functools_lru_cache 1.5.0 (new)``
    - ``cursor 1.2.0 (new)``  `#3089 <https://github.com/pypa/pipenv/issues/3089>`_
- Updated vendored dependencies:
    - ``requests 2.19.1 => 2.20.1``
    - ``tomlkit 0.4.46 => 0.5.2``
    - ``vistir 0.1.6 => 0.2.4``
    - ``pythonfinder 1.1.2 => 1.1.8``
    - ``requirementslib 1.1.10 => 1.3.0``  `#3096 <https://github.com/pypa/pipenv/issues/3096>`_
- Switch to ``tomlkit`` for parsing and writing. Drop ``prettytoml`` and ``contoml`` from vendors.  `#3191 <https://github.com/pypa/pipenv/issues/3191>`_
- Updated ``requirementslib`` to aid in resolution of local and remote archives.  `#3196 <https://github.com/pypa/pipenv/issues/3196>`_

Improved Documentation
----------------------

- Expanded development and testing documentation for contributors to get started.  `#3074 <https://github.com/pypa/pipenv/issues/3074>`_


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

- Updated test-PyPI add-on to better support json-API access (forward compatibility).
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

- Fixed a bug which prevented installation of editable requirements using ``ssh://`` style URLs  `#1393 <https://github.com/pypa/pipenv/issues/1393>`_

- VCS Refs for locked local editable dependencies will now update appropriately to the latest hash when running ``pipenv update``.  `#1690 <https://github.com/pypa/pipenv/issues/1690>`_

- ``.tar.gz`` and ``.zip`` artifacts will now have dependencies installed even when they are missing from the Lockfile.  `#2173 <https://github.com/pypa/pipenv/issues/2173>`_

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

- Fixed a bug which sometimes caused pipenv to throw a ``TypeError`` or to run into encoding issues when writing a Lockfile on python 2.  `#2561 <https://github.com/pypa/pipenv/issues/2561>`_

- Improve quoting logic for ``pipenv run`` so it works better with Windows
  built-in commands.  `#2563 <https://github.com/pypa/pipenv/issues/2563>`_

- Fixed a bug related to parsing VCS requirements with both extras and subdirectory fragments.
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

- Correctly pass ``verbose`` and ``debug`` flags to the resolver subprocess so it generates appropriate output. This also resolves a bug introduced by the fix to #2527.  `#2732 <https://github.com/pypa/pipenv/issues/2732>`_

- All markers are now included in ``pipenv lock --requirements`` output.  `#2748 <https://github.com/pypa/pipenv/issues/2748>`_

- Fixed a bug in marker resolution which could cause duplicate and non-deterministic markers.  `#2760 <https://github.com/pypa/pipenv/issues/2760>`_

- Fixed a bug in the dependency resolver which caused regular issues when handling ``setup.py`` based dependency resolution.  `#2766 <https://github.com/pypa/pipenv/issues/2766>`_

- Updated vendored dependencies:
    - ``pip-tools`` (updated and patched to latest w/ ``pip 18.0`` compatibility)
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
    - ``pip-tools`` (updated and patched to latest w/ ``pip 18.0`` compatibility)
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

- Updated documentation to use working fortune cookie add-on.  `#2644 <https://github.com/pypa/pipenv/issues/2644>`_

- Added additional information about troubleshooting ``pipenv shell`` by using the the ``$PIPENV_SHELL`` environment variable.  `#2671 <https://github.com/pypa/pipenv/issues/2671>`_

- Added a link to ``PEP-440`` version specifiers in the documentation for additional detail.  `#2674 <https://github.com/pypa/pipenv/issues/2674>`_

- Added simple example to README.md for installing from git.  `#2685 <https://github.com/pypa/pipenv/issues/2685>`_

- Stopped recommending `--system` for Docker contexts.  `#2762 <https://github.com/pypa/pipenv/issues/2762>`_

- Fixed the example url for doing "pipenv install -e
  some-repository-url#egg=something", it was missing the "egg=" in the fragment
  identifier.  `#2792 <https://github.com/pypa/pipenv/issues/2792>`_

- Fixed link to the "be cordial" essay in the contribution documentation.  `#2793 <https://github.com/pypa/pipenv/issues/2793>`_

- Clarify `pipenv install` documentation  `#2844 <https://github.com/pypa/pipenv/issues/2844>`_

- Replace reference to uservoice with PEEP-000  `#2909 <https://github.com/pypa/pipenv/issues/2909>`_


2018.7.1 (2018-07-01)
=====================

Features & Improvements
-----------------------

- All calls to ``pipenv shell`` are now implemented from the ground up using `shellingham  <https://github.com/sarugaku/shellingham>`_, a custom library which was purpose built to handle edge cases and shell detection.  `#2371 <https://github.com/pypa/pipenv/issues/2371>`_

- Added support for python 3.7 via a few small compatibility / bug fixes.  `#2427 <https://github.com/pypa/pipenv/issues/2427>`_,
  `#2434 <https://github.com/pypa/pipenv/issues/2434>`_,
  `#2436 <https://github.com/pypa/pipenv/issues/2436>`_

- Added new flag ``pipenv --support`` to replace the diagnostic command ``python -m pipenv.help``.  `#2477 <https://github.com/pypa/pipenv/issues/2477>`_,
  `#2478 <https://github.com/pypa/pipenv/issues/2478>`_

- Improved import times and CLI run times with minor tweaks.  `#2485 <https://github.com/pypa/pipenv/issues/2485>`_


Bug Fixes
---------

- Fixed an ongoing bug which sometimes resolved incompatible versions into the project Lockfile.  `#1901 <https://github.com/pypa/pipenv/issues/1901>`_

- Fixed a bug which caused errors when creating virtualenvs which contained leading dash characters.  `#2415 <https://github.com/pypa/pipenv/issues/2415>`_

- Fixed a logic error which caused ``--deploy --system`` to overwrite editable vcs packages in the Pipfile before installing, which caused any installation to fail by default.  `#2417 <https://github.com/pypa/pipenv/issues/2417>`_

- Updated requirementslib to fix an issue with properly quoting markers in VCS requirements.  `#2419 <https://github.com/pypa/pipenv/issues/2419>`_

- Installed new vendored jinja2 templates for ``click-completion`` which were causing template errors for users with completion enabled.  `#2422 <https://github.com/pypa/pipenv/issues/2422>`_

- Added support for python 3.7 via a few small compatibility / bug fixes.  `#2427 <https://github.com/pypa/pipenv/issues/2427>`_

- Fixed an issue reading package names from ``setup.py`` files in projects which imported utilities such as ``versioneer``.  `#2433 <https://github.com/pypa/pipenv/issues/2433>`_

- Pipenv will now ensure that its internal package names registry files are written with unicode strings.  `#2450 <https://github.com/pypa/pipenv/issues/2450>`_

- Fixed a bug causing requirements input as relative paths to be output as absolute paths or URIs.
  Fixed a bug affecting normalization of ``git+git@host`` URLs.  `#2453 <https://github.com/pypa/pipenv/issues/2453>`_

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

- PyPI mirror URLs can now be set to override instances of PyPI URLs by passing
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
  which lower-cases the comparison value (e.g. ``cpython`` instead of
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

- Updated ``requirementslib`` to fix a bug in Pipfile parsing affecting
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
  ``Requires-Python`` metadata with no specifiers.  `#2377
  <https://github.com/pypa/pipenv/issues/2377>`_

- ``pipenv update`` will now always run the resolver and lock before ensuring
  dependencies are in sync with project Lockfile.  `#2379
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

- Updated ``requirementslib`` to fix a bug in Pipfile parsing affecting
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
