``pipenv check``, ``pipenv scan`` and ``pipenv --support`` now read the Pipfile
and ``Pipfile.lock`` as UTF-8 (with or without a BOM) instead of the locale encoding.
