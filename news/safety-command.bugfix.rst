Update ``check`` command to support the new ``scan`` functionality
---------------------------------------------------------------

The ``check`` command has been deprecated and will be unsupported beyond June 1, 2024.
Instead of adding a separate ``scan`` command, we've updated the ``check`` command to include a ``--scan`` option.

Key changes:
- Added a ``--scan`` option to the ``check`` command to use the new scan functionality
- Added a deprecation warning explaining that in future versions, ``check`` will run the scan command by default
- Better temporary file handling using the ``tempfile`` module to ensure proper cleanup
- More robust error handling

Users are encouraged to start using the ``--scan`` option with the ``check`` command to prepare for the future change.
This option requires users to obtain and configure an API key from https://pyup.io.
