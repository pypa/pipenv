from types import SimpleNamespace
from unittest import mock

import pytest

from pipenv.patched.pip._internal.resolution.resolvelib.provider import PipProvider
from pipenv.patched.pip._vendor.resolvelib.structs import RequirementInformation
from pipenv.utils.resolver import Resolver, _get_cool_down_timedelta


def _conflict_info(name, parent=None):
    parent_obj = None if parent is None else SimpleNamespace(name=parent)
    return RequirementInformation(SimpleNamespace(name=name), parent_obj)


@pytest.mark.utils
def test_pip_provider_promotes_repeated_conflict_identifiers():
    provider = PipProvider(mock.sentinel.factory, {}, False, "to-satisfy-only", {})

    for _ in range(5):
        selected = list(
            provider.narrow_requirement_selection(
                identifiers=["sentry-protos"],
                resolutions={},
                candidates={},
                information={},
                backtrack_causes=[_conflict_info("protobuf")],
            )
        )
        assert selected == ["sentry-protos"]

    selected = list(
        provider.narrow_requirement_selection(
            identifiers=["sentry-protos", "protobuf"],
            resolutions={},
            candidates={},
            information={},
            backtrack_causes=[],
        )
    )

    assert selected == ["protobuf"]


@pytest.mark.utils
def test_pip_provider_prefers_promoted_conflict_identifier():
    provider = PipProvider(mock.sentinel.factory, {}, False, "to-satisfy-only", {})

    for _ in range(5):
        list(
            provider.narrow_requirement_selection(
                identifiers=["sentry-protos"],
                resolutions={},
                candidates={},
                information={},
                backtrack_causes=[_conflict_info("protobuf")],
            )
        )

    information = {"protobuf": (), "sentry-protos": ()}
    protobuf_preference = provider.get_preference(
        "protobuf", {}, {}, information, []
    )
    sentry_preference = provider.get_preference(
        "sentry-protos", {}, {}, information, []
    )

    assert protobuf_preference < sentry_preference


def _make_hash_resolver():
    resolver = Resolver.__new__(Resolver)
    resolver.sources = [{"name": "pypi", "url": "https://pypi.org/simple"}]
    resolver.index_lookup = {}
    resolver._hash_cache = mock.sentinel.hash_cache
    resolver.project = mock.MagicMock()
    resolver.project.s.is_verbose.return_value = True
    return resolver


@pytest.mark.utils
def test_collect_hashes_does_not_warn_when_fallback_succeeds(monkeypatch):
    resolver = _make_hash_resolver()
    resolver.project.get_hashes_from_pypi.return_value = None
    resolver.project.get_hash_from_link.return_value = "sha256:abc123"

    candidate = SimpleNamespace(link=mock.sentinel.link)
    best_candidate_result = SimpleNamespace(applicable_candidates=[candidate])
    resolver.finder = mock.Mock(
        return_value=SimpleNamespace(
            find_best_candidate=mock.Mock(return_value=best_candidate_result)
        )
    )

    ireq = mock.MagicMock()
    ireq.link = None
    ireq.name = "regex"
    ireq.specifier = mock.sentinel.specifier

    monkeypatch.setattr("pipenv.utils.resolver.is_pinned_requirement", lambda _: True)

    with mock.patch("pipenv.utils.resolver.err.print") as err_print:
        hashes = resolver.collect_hashes(ireq)

    assert hashes == ["sha256:abc123"]
    err_print.assert_not_called()


@pytest.mark.utils
def test_collect_hashes_warns_once_when_all_strategies_fail(monkeypatch):
    resolver = _make_hash_resolver()
    resolver.project.get_hashes_from_pypi.return_value = None
    best_candidate_result = SimpleNamespace(applicable_candidates=[])
    resolver.finder = mock.Mock(
        return_value=SimpleNamespace(
            find_best_candidate=mock.Mock(return_value=best_candidate_result)
        )
    )

    ireq = mock.MagicMock()
    ireq.link = None
    ireq.name = "regex"
    ireq.specifier = mock.sentinel.specifier

    monkeypatch.setattr("pipenv.utils.resolver.is_pinned_requirement", lambda _: True)

    with mock.patch("pipenv.utils.resolver.err.print") as err_print:
        hashes = resolver.collect_hashes(ireq)

    assert hashes == set()
    err_print.assert_called_once_with(
        "[bold][red]Warning[/red][/bold]: Error generating hash for regex."
    )


@pytest.mark.utils
def test_parsed_constraints_are_cached(monkeypatch, tmp_path):
    project = mock.MagicMock()
    project.s.PIPENV_CACHE_DIR = str(tmp_path / "cache")
    project.settings.get.return_value = False
    project.packages = {}

    resolver = Resolver(set(), str(tmp_path), project, sources=[])
    pip_options = SimpleNamespace(extra_index_urls=[], build_isolation=False)
    calls = {"prepare": 0, "parse": 0}

    def fake_prepare_constraint_file(*args, **kwargs):
        calls["prepare"] += 1
        constraint_file = tmp_path / f"constraints-{calls['prepare']}.txt"
        constraint_file.write_text("")
        return str(constraint_file)

    def fake_parse_requirements(*args, **kwargs):
        calls["parse"] += 1
        return [SimpleNamespace(requirement=f"req-{calls['parse']}")]

    monkeypatch.setattr(Resolver, "pip_options", property(lambda self: pip_options))
    monkeypatch.setattr(Resolver, "session", property(lambda self: mock.sentinel.session))
    monkeypatch.setattr(
        Resolver,
        "finder",
        lambda self, ignore_compatibility=False: mock.sentinel.finder,
    )
    monkeypatch.setattr(
        "pipenv.utils.resolver.prepare_constraint_file",
        fake_prepare_constraint_file,
    )
    monkeypatch.setattr(
        "pipenv.utils.resolver.parse_requirements",
        fake_parse_requirements,
    )

    first = resolver.parsed_constraints
    second = resolver.parsed_constraints

    assert first is second
    assert calls == {"prepare": 1, "parse": 1}


class _ResolvedRequirement:
    def __init__(self, name):
        self.name = name
        self.specifier = ""
        self.comes_from = None
        self.markers = None
        self.req = None

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, _ResolvedRequirement) and self.name == other.name


@pytest.mark.utils
def test_resolve_constraints_reuses_package_finder():
    resolver = Resolver.__new__(Resolver)
    resolver.resolved_tree = {
        _ResolvedRequirement("requests"),
        _ResolvedRequirement("certifi"),
    }
    resolver.markers = {}
    resolver.markers_lookup = {}
    resolver.pipfile_entries = {}

    candidate = SimpleNamespace(link=SimpleNamespace(requires_python=None))
    finder = mock.MagicMock()
    finder.find_best_candidate.return_value = SimpleNamespace(best_candidate=candidate)
    resolver.finder = mock.Mock(return_value=finder)

    Resolver.resolve_constraints(resolver)

    resolver.finder.assert_called_once_with()
    assert finder.find_best_candidate.call_count == 2


@pytest.mark.utils
def test_resolve_hashes_runs_in_parallel():
    """resolve_hashes should dispatch collect_hashes concurrently and still
    populate resolver.hashes with every ireq -> hashes pair."""
    import threading

    resolver = Resolver.__new__(Resolver)

    class _HashableIreq:
        def __init__(self, name):
            self.name = name

        def __hash__(self):
            return hash(self.name)

        def __eq__(self, other):
            return isinstance(other, _HashableIreq) and self.name == other.name

    ireqs = [_HashableIreq(f"pkg-{i}") for i in range(32)]
    resolver.results = ireqs
    resolver.hashes = {}
    # Pre-stub _hash_finder so the eager initialization in resolve_hashes
    # does not attempt to build a real PackageFinder (which requires
    # resolver.project and other live state that the stub resolver lacks).
    resolver._hash_finder = mock.Mock()

    concurrent = 0
    peak = 0
    started = 0
    lock = threading.Lock()
    overlap_barrier = threading.Barrier(2, timeout=5)

    def slow_collect(ireq):
        nonlocal concurrent, peak, started
        should_wait_for_overlap = False
        with lock:
            concurrent += 1
            peak = max(peak, concurrent)
            started += 1
            should_wait_for_overlap = started <= 2
        try:
            # Deterministically require the first two calls to overlap instead of
            # relying on short real-time waits that can be flaky on slow CI.
            if should_wait_for_overlap:
                overlap_barrier.wait()
        except threading.BrokenBarrierError:
            pytest.fail(
                "Timed out waiting for two collect_hashes calls to overlap; "
                "expected resolver hash collection to run in parallel."
            )
        finally:
            with lock:
                concurrent -= 1
        return {f"sha256:hash-for-{ireq.name}"}

    resolver.collect_hashes = slow_collect
    result = Resolver.resolve_hashes.fget(resolver)

    assert peak >= 2, "collect_hashes should have run concurrently"
    assert result is resolver.hashes
    assert len(resolver.hashes) == len(ireqs)
    for ireq in ireqs:
        assert resolver.hashes[ireq] == {f"sha256:hash-for-{ireq.name}"}


@pytest.mark.utils
def test_resolve_constraints_runs_candidate_lookup_in_parallel():
    """resolve_constraints should overlap find_best_candidate calls."""
    import threading

    from pipenv.patched.pip._internal.req.req_install import InstallRequirement  # noqa: F401

    resolver = Resolver.__new__(Resolver)
    resolver.resolved_tree = {
        _ResolvedRequirement(f"pkg-{i}") for i in range(16)
    }
    resolver.markers = {}
    resolver.markers_lookup = {}
    resolver.pipfile_entries = {}

    concurrent = 0
    peak = 0
    started = 0
    lock = threading.Lock()
    overlap_barrier = threading.Barrier(2, timeout=5)

    def slow_find(name, specifier):
        nonlocal concurrent, peak, started
        should_wait_for_overlap = False
        with lock:
            concurrent += 1
            peak = max(peak, concurrent)
            started += 1
            should_wait_for_overlap = started <= 2
        try:
            # Deterministically require the first two calls to overlap instead of
            # relying on short real-time waits that can be flaky on slow CI.
            if should_wait_for_overlap:
                overlap_barrier.wait()
        except threading.BrokenBarrierError:
            pytest.fail(
                "Timed out waiting for two find_best_candidate calls to overlap; "
                "expected resolver candidate lookup to run in parallel."
            )
        finally:
            with lock:
                concurrent -= 1
        return SimpleNamespace(
            best_candidate=SimpleNamespace(link=SimpleNamespace(requires_python=None))
        )

    finder = SimpleNamespace(find_best_candidate=slow_find)
    resolver.finder = mock.Mock(return_value=finder)

    Resolver.resolve_constraints(resolver)

    assert peak >= 2, "find_best_candidate should have run concurrently"


@pytest.mark.utils
def test_prepare_index_lookup_is_cached():
    resolver = Resolver.__new__(Resolver)
    resolver._prepared_index_lookup = None
    resolver.sources = [
        {"name": "pypi", "url": "https://pypi.org/simple"},
        {"name": "internal", "url": "https://example.com/simple"},
    ]
    resolver.index_lookup = {"foo": "internal"}

    first = resolver.prepare_index_lookup()
    # Mutate inputs after the first call — cached result should be returned.
    resolver.sources.append({"name": "other", "url": "https://other"})
    resolver.index_lookup["bar"] = "pypi"
    second = resolver.prepare_index_lookup()

    assert first is second
    assert "bar" not in first


@pytest.mark.utils
def test_process_resolver_results_does_not_scan_reverse_dependencies():
    from pipenv.resolver import process_resolver_results

    project = mock.MagicMock()
    project.parsed_pipfile = {"packages": {}}
    project.environment.reverse_dependencies.side_effect = AssertionError(
        "reverse dependencies should not be loaded while processing lock results"
    )

    resolver = mock.MagicMock()
    resolver.index_lookup = {}
    resolver.parsed_constraints = []

    results = [{"name": "requests", "version": "==2.32.0"}]

    processed = process_resolver_results(results, resolver, project, "packages")

    assert processed == [{"name": "requests", "version": "==2.32.0"}]
    project.environment.reverse_dependencies.assert_not_called()


# ---------------------------------------------------------------------------
# cool-down-period / --uploaded-prior-to tests
# ---------------------------------------------------------------------------

def _make_project(cool_down_period):
    """Return a mock project whose [pipenv] section contains cool-down-period."""
    project = mock.MagicMock()
    settings = {}
    if cool_down_period is not None:
        settings["cool-down-period"] = cool_down_period
    project.settings = settings
    return project


@pytest.mark.utils
@pytest.mark.parametrize("value,expected_days", [
    ("30d",  30),
    ("1d",   1),
    ("365d", 365),
])
def test_get_cool_down_timedelta_valid(value, expected_days):
    import datetime
    project = _make_project(value)
    result = _get_cool_down_timedelta(project)
    assert result == datetime.timedelta(days=expected_days)


@pytest.mark.utils
@pytest.mark.parametrize("value", [None, "", "30days", "30h", "P30D", "1 d", "d"])
def test_get_cool_down_timedelta_invalid_or_absent(value):
    project = _make_project(value)
    assert _get_cool_down_timedelta(project) is None


@pytest.mark.utils
def test_pip_options_sets_uploaded_prior_to_from_cool_down_period(monkeypatch):
    """Resolver.pip_options sets uploaded_prior_to when cool-down-period is configured."""
    import datetime

    project = _make_project("30d")
    project.s.PIPENV_CACHE_DIR = "/tmp/cache"
    project.s.PIPENV_KEYRING_PROVIDER = None
    project.settings = {"cool-down-period": "30d"}

    # Stub parse_args to return a bare namespace so we don't need a real pip command.
    fake_options = SimpleNamespace(pre=False, force_reinstall=False)
    pip_cmd = mock.MagicMock()
    pip_cmd.parser.parse_args.return_value = (fake_options, [])

    resolver = Resolver.__new__(Resolver)
    resolver.project = project
    resolver.pre = False

    monkeypatch.setattr(Resolver, "pip_command", property(lambda self: pip_cmd))
    monkeypatch.setattr(Resolver, "pip_args", property(lambda self: []))
    monkeypatch.setattr(
        "pipenv.utils.resolver.check_release_control_exclusive", lambda opts: None
    )

    before = datetime.datetime.now(datetime.timezone.utc)
    pip_options = resolver.pip_options
    after = datetime.datetime.now(datetime.timezone.utc)

    assert hasattr(pip_options, "uploaded_prior_to"), "uploaded_prior_to not set on pip_options"
    cutoff = pip_options.uploaded_prior_to
    assert before - datetime.timedelta(days=30, seconds=1) < cutoff < after - datetime.timedelta(days=30) + datetime.timedelta(seconds=1)
