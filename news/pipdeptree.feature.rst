Install pipdeptree on-demand for graph and update commands

This change makes pipdeptree installed on-demand when needed for the ``graph`` and
``update`` commands, similar to how ``pip-audit`` is handled. This means that
``pipdeptree`` will be automatically installed when running these commands if it
is not already present in the environment.

This change ensures that users don't need to manually install ``pipdeptree``
before using these commands, while still maintaining the same behavior for
users who have it installed already.
