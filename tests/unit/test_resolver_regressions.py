from types import SimpleNamespace
from unittest import mock

import pytest

from pipenv.patched.pip._internal.resolution.resolvelib.provider import PipProvider
from pipenv.patched.pip._vendor.resolvelib.structs import RequirementInformation
from pipenv.utils.resolver import Resolver


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
