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

import os
from collections.abc import MutableMapping
from typing import Any, Iterator

from pipenv.utils.shell import env_to_bool

# T18 (Initiative G phase 2): settings whose value may be overridden by
# an environment variable using pipenv's standard ``PIPENV_<UPPER>``
# convention.  When the env var is set (to a truthy or falsy string),
# its boolean value wins over both the Pipfile value and the
# caller-supplied default.  Keep this mapping small — it's reserved for
# settings explicitly documented as env-var-overridable so we don't
# silently turn every Pipfile key into a magic env-var read.
_ENV_OVERRIDE_KEYS: dict[str, str] = {
    "prefetch_index_manifests": "PIPENV_PREFETCH_INDEX_MANIFESTS",
}


def _env_override(key: str) -> Any:
    """Return the boolean value of the env-var override for ``key`` if
    one is set, else the sentinel ``None`` (meaning "no override —
    defer to the Pipfile / default").

    Coercion mirrors :func:`pipenv.utils.shell.env_to_bool`; an
    unparseable value is left alone (returned as the raw string) so
    callers can surface a useful error rather than silently coercing
    garbage.
    """
    env_name = _ENV_OVERRIDE_KEYS.get(key)
    if env_name is None:
        return None
    raw = os.environ.get(env_name)
    if raw is None:
        return None
    try:
        return env_to_bool(raw)
    except ValueError:
        # Unparseable: return the raw string so callers / tests can
        # see what was set.  Matches the fallback shape used by
        # :func:`pipenv.environments.get_from_env`.
        return raw


class Settings(MutableMapping):
    """``[pipenv]`` configuration subsystem of :class:`Project`.

    Constructed with a back-reference to its owning ``Project``. The
    backing store is ``project.pipfile.parsed.get("pipenv", {})``; this
    class never caches a reference to that table — every read goes
    through ``project.pipfile.parsed`` so the mtime-invalidated cache
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

        Read through ``project.pipfile.parsed`` on every call so that
        Pipfile-cache invalidation (handled by ``Project.pipfile.write_toml``)
        is honoured automatically. Do not cache the returned reference
        across calls.
        """
        return self._project.pipfile.parsed.get("pipenv", {})

    # ---- Mapping protocol --------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        override = _env_override(key)
        if override is not None:
            return override
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
        # against a tomlkit Table.  An env-var override (T18) counts
        # as "present" so callers checking ``"key" in settings`` see
        # the same view as ``settings.get(key)`` / ``settings[key]``.
        if isinstance(key, str) and _env_override(key) is not None:
            return True
        return key in self._table()

    def get(self, key: str, default: Any = None) -> Any:
        # MutableMapping inherits a ``get`` from Mapping that uses
        # ``__getitem__`` and catches KeyError. The explicit override
        # avoids the exception round-trip on the hot read path and
        # mirrors the previous ``dict.get`` / ``tomlkit.Table.get``
        # signature exactly.  T18: env-var override (when present)
        # wins over both Pipfile and the caller-supplied ``default``,
        # matching pipenv's standard ``PIPENV_<KEY>`` precedence.
        override = _env_override(key)
        if override is not None:
            return override
        return self._table().get(key, default)

    # ---- writers -----------------------------------------------------------

    def update(self, d: dict[str, Any]) -> None:  # type: ignore[override]
        """Persist new keys from ``d`` into the ``[pipenv]`` table.

        Mirrors the previous ``Project.update_settings`` semantics:
        only keys NOT already present are added; pre-existing keys are
        left untouched. If any key is added, the Pipfile is rewritten
        via :meth:`Project.pipfile.write_toml`, which invalidates the parsed
        Pipfile cache.
        """
        settings = self._table()
        changed = False
        for new in d.keys():  # noqa: PLC0206
            if new not in settings:
                settings[new] = d[new]
                changed = True
        if changed:
            p = self._project.pipfile.parsed
            p["pipenv"] = settings
            # Write the changes to disk.
            self._project.pipfile.write_toml(p)

    # ---- typed read accessors ---------------------------------------------

    @property
    def use_pylock(self) -> bool:
        """Returns True if pylock.toml should be generated.

        Was ``Project.use_pylock`` prior to T_D.3.
        """
        return self.get("use_pylock", False)

    @property
    def resolver(self) -> str | None:
        """Return the configured resolver backend name from
        ``[pipenv] resolver = "..."`` in the Pipfile, or ``None`` if
        unset.

        Introduced by T_F.5 (pluggable resolver backends, scaffolding
        only).  Per the maintainer sign-off (2026-05-12, answer 1) the
        Pipfile field is ``resolver`` under the existing ``[pipenv]``
        section — no new subsection.  Equivalent ``pyproject.toml`` /
        ``pylock.toml`` plumbing is a separate hook; see
        ``# TODO(T_F.8)`` markers in those readers.

        The parent-side resolver request builder consults this when it
        stamps the effective backend onto the wire request using the
        precedence chain CLI > env > Pipfile > default.
        """
        value = self.get("resolver")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @property
    def resolver_backend(self) -> str | None:
        """Return the configured resolver backend name from
        ``[pipenv] resolver_backend = "..."`` in the Pipfile, or
        ``None`` if unset.

        Introduced by T_PLUMBING (Initiative G phase 3, 2026-05-12).
        The user-facing Pipfile setting name documented in
        ``docs/pipfile.md`` and the T_SHIP follow-up.  Coexists with
        the T_F.5 ``[pipenv] resolver`` accessor as the back-compat
        alias; the lock routine prefers ``resolver_backend`` over
        ``resolver`` when both are present.

        Accepted values: ``"pip"`` (default), ``"pure-python"``.
        Unknown values still produce a structured ``InternalError``
        response from the dispatcher rather than crashing — see
        :func:`pipenv.resolver.core.resolve_for_pipenv`.
        """
        value = self.get("resolver_backend")
        if value is None:
            return None
        text = str(value).strip()
        return text or None
