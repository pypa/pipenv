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
        return_value=SimpleNamespace(find_best_candidate=mock.Mock(return_value=best_candidate_result))
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
        return_value=SimpleNamespace(find_best_candidate=mock.Mock(return_value=best_candidate_result))
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
