"""Unit smoke for FU2: per-source ``verify_ssl`` fan-out in the prefetcher.

Initiative G Phase-3 follow-up #2.  Pins the contract that
``pipenv.routines.lock._prefetch_index_manifests_if_enabled`` builds
one :class:`pipenv.resolver.fetcher.ParallelFetcher` per unique
``verify_ssl`` policy among Pipfile sources, and dispatches each
target through the fetcher matching its source's policy.

Why a unit smoke (not just integration)
---------------------------------------
T20's integration tests exercise the prefetch from the user's vantage
point, but they cannot easily prove per-source fan-out without a
self-signed-cert fixture (gap documented in
``tests/integration/test_prefetch_manifest.py::test_prefetch_with_self_signed_source``).
This file mocks the import surface to drive the helper directly with a
fake project, observing the constructed-fetchers list and each
populate call's targets — fast, hermetic, no network.

T19 regression: the previous "majority-verify wins" heuristic
constructed exactly one fetcher even for mixed-policy Pipfiles.  These
tests fail RED against that code and pass GREEN after the FU2 refactor.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fake-project plumbing — minimal duck-types matching what the helper
# touches via ``project.<attr>``.  Kept inline (no fixture sprawl) so the
# whole test surface is readable in one screenful.
# ---------------------------------------------------------------------------


class _FakePipfile:
    """Stand-in for ``project.pipfile``."""

    def __init__(self, packages: dict[str, Any]) -> None:
        self.exists = True
        # The helper reads ``project.pipfile.parsed.get(pipfile_category, {})``.
        # ``packages`` is keyed by the *pipfile* category (e.g. ``"packages"``).
        self.parsed = packages


class _FakeSources:
    """Stand-in for ``project.sources``.  Holds the configured Pipfile sources."""

    def __init__(self, sources: list[dict[str, Any]]) -> None:
        self._sources = sources

    def pipfile_sources(self) -> list[dict[str, Any]]:
        return list(self._sources)


class _FakeSettings:
    """Minimal mapping with a ``.get`` matching ``project.s``'s contract."""

    def __init__(self, **kwargs: Any) -> None:
        self._data = dict(kwargs)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class _FakeS:
    """Stand-in for ``project.s`` (the :class:`Environment` object)."""

    def __init__(self, cache_dir: str) -> None:
        self.PIPENV_CACHE_DIR = cache_dir

    def is_quiet(self) -> bool:
        return False

    def is_verbose(self) -> bool:
        return False


class _FakeProject:
    """Minimal stand-in matching the helper's read-only access pattern."""

    def __init__(
        self,
        sources: list[dict[str, Any]],
        packages: dict[str, Any],
        cache_dir: str,
        *,
        prefetch: bool = True,
    ) -> None:
        self.sources = _FakeSources(sources)
        self.pipfile = _FakePipfile(packages)
        self.settings = _FakeSettings(prefetch_index_manifests=prefetch)
        self.s = _FakeS(cache_dir)


# ---------------------------------------------------------------------------
# Helper: install a fake ``pipenv.resolver.fetcher`` module so the helper's
# lazy import picks up *our* ``ParallelFetcher`` recorder instead of the
# real implementation.  Returns the recorder list of ``(fetcher_instance,
# client, targets)`` tuples.
# ---------------------------------------------------------------------------


class _RecordingFetcher:
    """Fake ParallelFetcher that records every populate call."""

    # Class-level recorder so different instances funnel into one list.
    instances: list[Any] = []
    populate_calls: list[tuple[Any, Any, list[tuple[str, str]]]] = []

    def __init__(self, client: Any, cache: Any, **kwargs: Any) -> None:
        self.client = client
        self.cache = cache
        self.kwargs = kwargs
        _RecordingFetcher.instances.append(self)

    def populate(self, targets: list[tuple[str, str]]) -> dict[str, Any]:
        _RecordingFetcher.populate_calls.append(
            (self, self.client, list(targets))
        )
        return {}


class _RecordingClient:
    """Fake PEP691Client that exposes its session + verify flag."""

    instances: list[Any] = []

    def __init__(self, session: Any, *, verify: bool = True, **kwargs: Any) -> None:
        self.session = session
        self.verify = verify
        _RecordingClient.instances.append(self)


class _NullCache:
    """Fake ParsedManifestCache — the helper never reads from it."""

    instances: list[Any] = []

    def __init__(self, cache_root: Any) -> None:
        self.cache_root = cache_root
        _NullCache.instances.append(self)


@pytest.fixture
def install_recording_imports(monkeypatch, tmp_path):
    """Patch the lazy imports inside ``_prefetch_index_manifests_if_enabled``.

    The helper imports from ``pipenv.resolver.fetcher``,
    ``pipenv.resolver.manifest_cache``, ``pipenv.resolver.pep691``, and
    ``pipenv.utils.internet`` inside the function body (lazy by design —
    zero cost when the setting is off).  We patch the real modules in
    ``sys.modules`` so the lazy ``from ... import ...`` lines pick up our
    recorders.
    """
    # Reset the class-level recorders so cross-test pollution is impossible.
    _RecordingFetcher.instances = []
    _RecordingFetcher.populate_calls = []
    _RecordingClient.instances = []
    _NullCache.instances = []

    # Sessions distinguished by verify_ssl — distinct sentinel mocks so we
    # can assert which session was wired to which client.
    sessions_by_verify: dict[bool, Any] = {
        True: MagicMock(name="session-verify-true"),
        False: MagicMock(name="session-verify-false"),
    }

    def _fake_get_requests_session(*args: Any, **kwargs: Any) -> Any:
        verify = kwargs.get("verify_ssl", True)
        return sessions_by_verify[bool(verify)]

    # Patch ``pipenv.utils.internet.get_requests_session`` in-place — the
    # helper does ``from pipenv.utils.internet import get_requests_session``,
    # which binds the name at call time, so a module attribute swap is
    # sufficient.
    import pipenv.utils.internet as _internet_mod

    monkeypatch.setattr(
        _internet_mod, "get_requests_session", _fake_get_requests_session
    )

    # Patch the resolver modules' class symbols similarly.
    import pipenv.resolver.fetcher as _fetcher_mod
    import pipenv.resolver.manifest_cache as _cache_mod
    import pipenv.resolver.pep691 as _pep691_mod

    monkeypatch.setattr(_fetcher_mod, "ParallelFetcher", _RecordingFetcher)
    monkeypatch.setattr(_cache_mod, "ParsedManifestCache", _NullCache)
    monkeypatch.setattr(_pep691_mod, "PEP691Client", _RecordingClient)

    return sessions_by_verify


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.utils
def test_single_policy_constructs_one_fetcher(install_recording_imports, tmp_path):
    """The common case — single PyPI source, ``verify_ssl=true`` — must
    still build exactly one ParallelFetcher, identical to T19's
    behaviour (regression guard).
    """
    from pipenv.routines.lock import _prefetch_index_manifests_if_enabled

    project = _FakeProject(
        sources=[
            {"url": "https://pypi.org/simple", "verify_ssl": True, "name": "pypi"},
        ],
        packages={"packages": {"six": "*", "click": "*"}},
        cache_dir=str(tmp_path / "cache"),
    )

    _prefetch_index_manifests_if_enabled(
        project, ["default"], clear=False
    )

    assert len(_RecordingFetcher.instances) == 1, (
        "single-policy project must build exactly one fetcher; got "
        f"{len(_RecordingFetcher.instances)}"
    )
    assert len(_RecordingFetcher.populate_calls) == 1
    _, _, targets = _RecordingFetcher.populate_calls[0]
    # Two packages x one source = two targets.
    assert sorted((u, n) for u, n in targets) == sorted(
        [
            ("https://pypi.org/simple", "six"),
            ("https://pypi.org/simple", "click"),
        ]
    )


@pytest.mark.utils
def test_mixed_verify_ssl_fans_out_per_policy(
    install_recording_imports, tmp_path
):
    """FU2 contract: two sources with differing ``verify_ssl`` policies
    each get their own ParallelFetcher, and each fetcher receives ONLY
    the targets belonging to its policy.

    This is the test that fails RED against T19's "majority-verify wins"
    code (which builds one fetcher and dumps all targets through it).
    """
    from pipenv.routines.lock import _prefetch_index_manifests_if_enabled

    sessions_by_verify = install_recording_imports

    project = _FakeProject(
        sources=[
            {"url": "https://pypi.org/simple", "verify_ssl": True, "name": "pypi"},
            {
                "url": "https://private.example.test/simple",
                "verify_ssl": False,
                "name": "private",
            },
        ],
        packages={"packages": {"six": "*"}},
        cache_dir=str(tmp_path / "cache"),
    )

    _prefetch_index_manifests_if_enabled(
        project, ["default"], clear=False
    )

    # Two fetchers — one per verify policy.
    assert len(_RecordingFetcher.instances) == 2, (
        "mixed-verify project must build one fetcher per policy; got "
        f"{len(_RecordingFetcher.instances)}"
    )
    # Both fetchers must have been populate'd.
    assert len(_RecordingFetcher.populate_calls) == 2

    # Build a (verify_flag -> targets) map by looking at each client's
    # ``verify`` attribute (which we recorded in _RecordingClient.__init__).
    targets_by_verify: dict[bool, list[tuple[str, str]]] = {}
    sessions_used_by_verify: dict[bool, Any] = {}
    for _fetcher, client, targets in _RecordingFetcher.populate_calls:
        targets_by_verify[client.verify] = sorted(targets)
        sessions_used_by_verify[client.verify] = client.session

    # The verify=True fetcher saw ONLY the pypi target.
    assert targets_by_verify[True] == [("https://pypi.org/simple", "six")]
    # The verify=False fetcher saw ONLY the private-index target.
    assert targets_by_verify[False] == [
        ("https://private.example.test/simple", "six")
    ]

    # And each client was wired to the matching session — proves the
    # session-per-verify dispatch flowed end-to-end.
    assert sessions_used_by_verify[True] is sessions_by_verify[True]
    assert sessions_used_by_verify[False] is sessions_by_verify[False]


@pytest.mark.utils
def test_clear_short_circuits_fan_out(install_recording_imports, tmp_path):
    """``clear=True`` must bypass the whole helper — no fetchers, no
    populate calls.  Regression guard against accidentally re-introducing
    work on the ``--clear`` path during the refactor.
    """
    from pipenv.routines.lock import _prefetch_index_manifests_if_enabled

    project = _FakeProject(
        sources=[
            {"url": "https://pypi.org/simple", "verify_ssl": True, "name": "pypi"},
            {
                "url": "https://private.example.test/simple",
                "verify_ssl": False,
                "name": "private",
            },
        ],
        packages={"packages": {"six": "*"}},
        cache_dir=str(tmp_path / "cache"),
    )

    _prefetch_index_manifests_if_enabled(
        project, ["default"], clear=True
    )

    assert _RecordingFetcher.instances == []
    assert _RecordingFetcher.populate_calls == []


@pytest.mark.utils
def test_setting_disabled_short_circuits(install_recording_imports, tmp_path):
    """Setting OFF (the default) must bypass the helper entirely."""
    from pipenv.routines.lock import _prefetch_index_manifests_if_enabled

    project = _FakeProject(
        sources=[
            {"url": "https://pypi.org/simple", "verify_ssl": True, "name": "pypi"},
        ],
        packages={"packages": {"six": "*"}},
        cache_dir=str(tmp_path / "cache"),
        prefetch=False,
    )

    _prefetch_index_manifests_if_enabled(
        project, ["default"], clear=False
    )

    assert _RecordingFetcher.instances == []
