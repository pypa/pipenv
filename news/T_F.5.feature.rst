Pipenv now includes scaffolding for pluggable resolver backends. The
``--resolver NAME`` CLI flag, ``PIPENV_RESOLVER`` environment variable,
and ``[pipenv] resolver`` Pipfile setting are now recognized, but only
``pip`` (the default) is shipped in this release. Selecting an unknown
backend will produce a clear error message. Future releases will add
additional backends.
