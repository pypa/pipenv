2018.7.1.dev0 (2018-07-15)
==========================


Features & Improvements
-----------------------

- Updated test-pypi addon to better support json-api access (forward compatibility).
  Improved testing process for new contributors.  `#2568 <https://github.com/pypa/pipenv/issues/2568>`_
  

Behavior Changes
----------------

- Virtual environment activation for ``run`` is revised to improve interpolation
  with other Python discovery tools.  `#2503 <https://github.com/pypa/pipenv/issues/2503>`_
  
- Improve terminal coloring to display better in Powershell.  `#2511 <https://github.com/pypa/pipenv/issues/2511>`_
  
- Invoke ``virtualenv`` directly for virtual environment creation, instead of depending on ``pew``.  `#2518 <https://github.com/pypa/pipenv/issues/2518>`_
  
- ``pipenv --help`` will now include short help descriptions.  `#2542 <https://github.com/pypa/pipenv/issues/2542>`_
  

Bug Fixes
---------

- Fix subshell invocation on Windows for Python 2.  `#2515 <https://github.com/pypa/pipenv/issues/2515>`_
  
- Fixed a bug which sometimes caused pipenv to throw a ``TypeError`` or to run into encoding issues when writing lockfiles on python 2.  `#2561 <https://github.com/pypa/pipenv/issues/2561>`_
  
- Improve quoting logic for ``pipenv run`` so it works better with Windows
  built-in commands.  `#2563 <https://github.com/pypa/pipenv/issues/2563>`_
  
- Fixed a bug related to parsing vcs requirements with both extras and subdirectory fragments.
  Corrected an issue in the ``requirementslib`` parser which led to some markers being discarded rather than evaluated.  `#2564 <https://github.com/pypa/pipenv/issues/2564>`_
  

Vendored Libraries
------------------

- Pew is no longer vendored. Entry point ``pewtwo``, packages ``pipenv.pew`` and
  ``pipenv.patched.pew`` are removed.  `#2521 <https://github.com/pypa/pipenv/issues/2521>`_
  

Improved Documentation
----------------------

- Simplified the test configuration process.  `#2568 <https://github.com/pypa/pipenv/issues/2568>`_

