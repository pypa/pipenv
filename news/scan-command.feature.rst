Add new ``scan`` command to replace deprecated ``check`` command
---------------------------------------------------------------

The ``check`` command has been deprecated and will be unsupported beyond June 1, 2024.
A new ``scan`` command has been added as a replacement, which is easier to use and more powerful.

Key improvements:
- Better temporary file handling using the ``tempfile`` module to ensure proper cleanup
- More robust error handling
- Support for legacy mode with the ``--legacy-mode`` flag to use the old ``check`` command
- Improved code organization and documentation

The ``check`` command will continue to work until the deprecation date, but users are encouraged to switch to the new ``scan`` command.
