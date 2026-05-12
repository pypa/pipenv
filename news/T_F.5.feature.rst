Pipenv now supports pluggable resolver backends. The default behaviour
is unchanged (pip). Future releases will ship additional backends
selectable via the new ``[pipenv] resolver`` Pipfile setting, the
``--resolver NAME`` CLI flag, or the ``PIPENV_RESOLVER`` environment
variable.
