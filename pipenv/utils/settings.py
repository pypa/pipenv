"""The ``Settings`` subsystem of :class:`pipenv.project.Project`.

Second of the Initiative D extractions (after ``Sources`` in T_D.2).
The ``Settings``-classified methods on ``pipenv.project.Project`` move
into this module, accessed via a ``@cached_property`` ``Project.settings``.

Behaviour is preserved verbatim from the previous in-``Project``
implementation; this is a relocation, not a rewrite. The class
implements :class:`collections.abc.MutableMapping` so that every existing
``project.settings.get(key, default)`` / ``key in project.settings`` /
``project.settings[key]`` call site continues to work unchanged.

See ``docs/dev/initiative-d-inventory.md`` for the T_D.1 inventory and
``docs/dev/modernization-plan.md`` for the task spec.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Iterator


class Settings(MutableMapping):
    """``[pipenv]`` configuration subsystem of :class:`Project`.

    Constructed with a back-reference to its owning ``Project``. The
    backing store is ``project.parsed_pipfile.get("pipenv", {})``; this
    class never caches a reference to that table — every read goes
    through ``project.parsed_pipfile`` so the mtime-invalidated cache
    semantics on :class:`Project` are honoured.

    The ``MutableMapping`` ABC lets legacy callers continue to use the
    full mapping protocol against ``project.settings``:

    - ``project.settings.get("allow_prereleases", False)`` — primary
      read shape; used by every external caller.
    - ``"key" in project.settings``
    - ``project.settings["key"]``
    - ``iter(project.settings)``, ``len(project.settings)``

    The writer ``Settings.update(d)`` replaces the previous
    ``Project.update_settings(d)`` method, with identical semantics:
    new keys from ``d`` are added; pre-existing keys are preserved.
    """

    def __init__(self, project):
        self._project = project

    # ---- read-path helpers -------------------------------------------------

    def _table(self):
        """Return the live ``[pipenv]`` table view, or an empty dict if
        the section is absent.

        Read through ``project.parsed_pipfile`` on every call so that
        Pipfile-cache invalidation (handled by ``Project.write_toml``)
        is honoured automatically. Do not cache the returned reference
        across calls.
        """
        return self._project.parsed_pipfile.get("pipenv", {})

    # ---- Mapping protocol --------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._table()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        # In-place mutation of the live tomlkit table. Caller is
        # responsible for triggering a Pipfile write afterwards (see
        # :meth:`update` for the canonical writer).
        table = self._table()
        table[key] = value

    def __delitem__(self, key: str) -> None:
        table = self._table()
        del table[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._table())

    def __len__(self) -> int:
        return len(self._table())

    def __contains__(self, key: object) -> bool:
        # MutableMapping supplies a default implementation via
        # __getitem__/KeyError, but the explicit form is faster and
        # matches the legacy behaviour of ``key in project.settings``
        # against a tomlkit Table.
        return key in self._table()

    def get(self, key: str, default: Any = None) -> Any:
        # MutableMapping inherits a ``get`` from Mapping that uses
        # ``__getitem__`` and catches KeyError. The explicit override
        # avoids the exception round-trip on the hot read path and
        # mirrors the previous ``dict.get`` / ``tomlkit.Table.get``
        # signature exactly.
        return self._table().get(key, default)

    # ---- writers -----------------------------------------------------------

    def update(self, d: dict[str, Any]) -> None:  # type: ignore[override]
        """Persist new keys from ``d`` into the ``[pipenv]`` table.

        Mirrors the previous ``Project.update_settings`` semantics:
        only keys NOT already present are added; pre-existing keys are
        left untouched. If any key is added, the Pipfile is rewritten
        via :meth:`Project.write_toml`, which invalidates the parsed
        Pipfile cache.
        """
        settings = self._table()
        changed = False
        for new in d.keys():  # noqa: PLC0206
            if new not in settings:
                settings[new] = d[new]
                changed = True
        if changed:
            p = self._project.parsed_pipfile
            p["pipenv"] = settings
            # Write the changes to disk.
            self._project.write_toml(p)

    # ---- typed read accessors ---------------------------------------------

    @property
    def use_pylock(self) -> bool:
        """Returns True if pylock.toml should be generated.

        Was ``Project.use_pylock`` prior to T_D.3.
        """
        return self.get("use_pylock", False)
