``[pipenv] resolver_backend`` in the Pipfile is now honored by ``pipenv
update``, ``pipenv upgrade`` and ``pipenv uninstall``.  Previously only
``pipenv lock`` read the documented key; the other commands only checked
the older ``[pipenv] resolver`` alias and silently re-locked with the pip
backend.
