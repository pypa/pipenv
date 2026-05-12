"""Unit tests for T_F.7: structured ``Diagnostics.resolver_log`` capture.

T_F.4 left a hook in :func:`pipenv.resolver.core.resolve_for_pipenv` that
emitted an empty :class:`pipenv.resolver.schema.Diagnostics`.  T_F.7
populates the ``resolver_log`` slot with formatted log records captured
from the resolver's loggers during the resolve call.

These tests pin down:

1. The capture mechanism collects records emitted on the targeted
   loggers while ``resolve_for_pipenv`` runs (mocked ``resolve_packages``
   stand-in fires log records, then we assert they show up in
   ``response.diagnostics.resolver_log``).
2. Records are formatted as ``"[LEVELNAME] message"`` (single-string per
   record, no embedded newlines from formatter side).
3. The capture is bounded: a forced-flood logger does not produce more
   than ~500 records; truncation is signalled with an ``"... (N records
   elided)"`` sentinel as the final entry.
4. Capture is restored cleanly: the installed handler is removed after
   ``resolve_for_pipenv`` returns, even if the resolver raises.
5. Empty case: when no records are emitted, ``resolver_log`` is an empty
   tuple (the T_F.3 reserved-empty contract still holds for silent
   resolves).
"""
from __future__ import annotations

import logging
from unittest import mock

from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    Diagnostics,
    PackageSpecs,
    ResolverOptions,
    ResolverRequest,
    ResolverResponse,
    ResolverSuccess,
    Source,
)


def _build_request(**overrides) -> ResolverRequest:
    kwargs = dict(
        schema_version=SCHEMA_VERSION,
        category="default",
        packages=PackageSpecs(specs={"requests": "requests==2.31.0"}),
        options=ResolverOptions(),
        sources=(
            Source(name="pypi", url="https://pypi.org/simple", verify_ssl=True),
        ),
    )
    kwargs.update(overrides)
    return ResolverRequest(**kwargs)


class TestResolverLogCapture:
    """The capture handler records log lines emitted by the resolver-side
    loggers during the ``resolve_packages`` call and surfaces them on
    ``response.diagnostics.resolver_log``.
    """

    def test_pipenv_logger_records_are_captured(self):
        from pipenv.resolver import core

        def _fake_resolve(_request):
            logging.getLogger("pipenv").info("source pypi resolved")
            return ([], None)

        with mock.patch.object(core, "resolve_packages", side_effect=_fake_resolve):
            response = core.resolve_for_pipenv(_build_request())

        assert isinstance(response, ResolverResponse)
        assert isinstance(response.result, ResolverSuccess)
        log = list(response.diagnostics.resolver_log)
        assert any("source pypi resolved" in line for line in log), log

    def test_pip_resolution_logger_records_are_captured(self):
        from pipenv.resolver import core

        def _fake_resolve(_request):
            logging.getLogger("pip._internal.resolution").info("looking up requests")
            return ([], None)

        with mock.patch.object(core, "resolve_packages", side_effect=_fake_resolve):
            response = core.resolve_for_pipenv(_build_request())

        log = list(response.diagnostics.resolver_log)
        assert any("looking up requests" in line for line in log), log

    def test_records_are_formatted_with_level_prefix(self):
        from pipenv.resolver import core

        def _fake_resolve(_request):
            logging.getLogger("pipenv").warning("mirror substituted")
            return ([], None)

        with mock.patch.object(core, "resolve_packages", side_effect=_fake_resolve):
            response = core.resolve_for_pipenv(_build_request())

        log = list(response.diagnostics.resolver_log)
        # Single string per record; level name is embedded so consumers
        # can distinguish info / warning / error without re-parsing.
        assert any(
            line.startswith("[WARNING]") and "mirror substituted" in line
            for line in log
        ), log

    def test_silent_resolve_yields_empty_resolver_log(self):
        from pipenv.resolver import core

        with mock.patch.object(core, "resolve_packages", return_value=([], None)):
            response = core.resolve_for_pipenv(_build_request())

        # No logging side-effects in the fake — log is empty tuple, the
        # default the T_F.3 reserved-but-empty contract permitted.
        assert tuple(response.diagnostics.resolver_log) == ()

    def test_capture_handler_is_removed_after_resolve(self):
        """The capture handler must NOT leak onto the loggers after
        ``resolve_for_pipenv`` returns — otherwise records keep piling
        up in a stale list across subsequent calls in the same process
        (the in-process branch is in the same interpreter as pipenv
        itself).
        """
        from pipenv.resolver import core

        target_loggers = [
            logging.getLogger("pipenv"),
            logging.getLogger("pip._internal.resolution"),
        ]
        before = {lg.name: list(lg.handlers) for lg in target_loggers}

        with mock.patch.object(core, "resolve_packages", return_value=([], None)):
            core.resolve_for_pipenv(_build_request())

        after = {lg.name: list(lg.handlers) for lg in target_loggers}
        assert before == after

    def test_capture_handler_is_removed_even_when_resolve_raises(self):
        from pipenv.resolver import core

        target_loggers = [
            logging.getLogger("pipenv"),
            logging.getLogger("pip._internal.resolution"),
        ]
        before = {lg.name: list(lg.handlers) for lg in target_loggers}

        def _explode(_request):
            raise AttributeError("pip exploded")

        with mock.patch.object(core, "resolve_packages", side_effect=_explode):
            # NEVER raises — InternalError variant returned.
            core.resolve_for_pipenv(_build_request())

        after = {lg.name: list(lg.handlers) for lg in target_loggers}
        assert before == after


class TestResolverLogCap:
    """The captured list is capped so a runaway logger can't OOM the
    parent or balloon the JSON envelope.
    """

    def test_volume_is_capped_with_truncation_sentinel(self):
        from pipenv.resolver import core

        def _flood(_request):
            lg = logging.getLogger("pipenv")
            # Flood well past the configured cap to force truncation.
            for i in range(core._RESOLVER_LOG_CAP + 50):
                lg.info("noise %d", i)
            return ([], None)

        with mock.patch.object(core, "resolve_packages", side_effect=_flood):
            response = core.resolve_for_pipenv(_build_request())

        log = list(response.diagnostics.resolver_log)
        # Cap respected; one trailing sentinel describing how many were
        # dropped.
        assert len(log) == core._RESOLVER_LOG_CAP + 1
        assert "records elided" in log[-1]


class TestResolverLogDiagnosticsAttachment:
    """The captured records actually land on the typed response's
    ``Diagnostics`` field, not anywhere else.  This is the contract the
    parent-side verbose surface depends on.
    """

    def test_diagnostics_is_a_dataclass_instance_not_dict(self):
        from pipenv.resolver import core

        def _fake_resolve(_request):
            logging.getLogger("pipenv").info("hello")
            return ([], None)

        with mock.patch.object(core, "resolve_packages", side_effect=_fake_resolve):
            response = core.resolve_for_pipenv(_build_request())

        assert isinstance(response.diagnostics, Diagnostics)
        assert isinstance(response.diagnostics.resolver_log, tuple)

    def test_resolver_log_survives_json_roundtrip(self):
        from pipenv.resolver import core

        def _fake_resolve(_request):
            logging.getLogger("pipenv").info("source substituted: mirror -> upstream")
            return ([], None)

        with mock.patch.object(core, "resolve_packages", side_effect=_fake_resolve):
            response = core.resolve_for_pipenv(_build_request())

        # Subprocess adapter writes ``to_json_dict`` to disk; the parent
        # reads it back via ``from_json_dict``.  resolver_log must
        # round-trip through that envelope.
        as_json = response.to_json_dict()
        round_tripped = ResolverResponse.from_json_dict(as_json)
        assert tuple(round_tripped.diagnostics.resolver_log) == tuple(
            response.diagnostics.resolver_log
        )
