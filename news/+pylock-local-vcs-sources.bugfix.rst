Keep path, editable, VCS and file dependencies in ``pylock.toml`` as PEP 751 ``directory``, ``vcs`` and ``archive``
sources, and install them from those sources. Previously they were written as plain index packages, so installing
from ``pylock.toml`` looked the name up on the package index.
