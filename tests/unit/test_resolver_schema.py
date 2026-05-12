"""Unit tests for the T_F.3 A1 typed-resolver-schema module.

This file covers the dataclass-level invariants and envelope JSON round-trip
that A1 owns.  C1 (later in the wave) will append a
``TestFromInstallRequirementParity`` class that drives
``LockedRequirement.from_install_requirement`` against the golden snapshots
captured under ``tests/unit/fixtures/resolver_schema/``; A1 leaves room for
that without writing it.

Per the A1 task description, no ``TestFromInstallRequirementParity`` class
is added here; only ``TestLockedRequirementInvariants`` and
``TestEnvelopeRoundtrip``.
"""
from __future__ import annotations

import pytest


class TestLockedRequirementInvariants:
    """Dataclass post-init invariants on :class:`LockedRequirement` (design §3.3)."""

    def test_bare_name_rejected(self):
        """A LockedRequirement with no version, vcs, file, or path must raise."""
        from pipenv.resolver.schema import LockedRequirement

        with pytest.raises(ValueError, match="carries no version"):
            LockedRequirement(name="foo")

    def test_version_only_accepted(self):
        from pipenv.resolver.schema import LockedRequirement

        # Should not raise
        lr = LockedRequirement(name="foo", version="==1.0")
        assert lr.name == "foo"
        assert lr.version == "==1.0"

    def test_file_only_accepted(self):
        from pipenv.resolver.schema import LockedRequirement

        lr = LockedRequirement(name="foo", file="file:///tmp/foo.whl")
        assert lr.file == "file:///tmp/foo.whl"

    def test_path_only_accepted(self):
        from pipenv.resolver.schema import LockedRequirement

        lr = LockedRequirement(name="foo", path="./vendor/foo")
        assert lr.path == "./vendor/foo"

    def test_vcs_only_accepted(self):
        from pipenv.resolver.schema import LockedRequirement, VCSPin

        lr = LockedRequirement(
            name="foo",
            vcs=VCSPin(backend="git", url="https://example.com/foo.git", ref="abc"),
        )
        assert lr.vcs is not None
        assert lr.vcs.backend == "git"

    def test_version_and_vcs_mutually_exclusive(self):
        """version + vcs combo must raise ValueError (design §3.3 invariant)."""
        from pipenv.resolver.schema import LockedRequirement, VCSPin

        with pytest.raises(ValueError, match="mutually exclusive"):
            LockedRequirement(
                name="foo",
                version="==1.0",
                vcs=VCSPin(backend="git", url="https://example.com/foo.git"),
            )


class TestEnvelopeRoundtrip:
    """`ResolverRequest` / `ResolverResponse` JSON round-trips (design §3.1/§3.2)."""

    def _sample_packages(self):
        from pipenv.resolver.schema import PackageSpecs

        return PackageSpecs(specs={"requests": "requests==2.28.1"})

    def _sample_options(self):
        from pipenv.resolver.schema import ResolverOptions

        return ResolverOptions()

    def _sample_sources(self):
        from pipenv.resolver.schema import Source

        return (Source(name="pypi", url="https://pypi.org/simple", verify_ssl=True),)

    def test_request_minimal_roundtrip(self):
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            ResolverRequest,
        )

        req = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=self._sample_packages(),
            options=self._sample_options(),
            sources=self._sample_sources(),
        )
        wire = req.to_json_dict()
        round = ResolverRequest.from_json_dict(wire)
        assert round == req

    def test_request_all_optionals_roundtrip(self):
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            LockedRequirement,
            RequestMetadata,
            ResolvedDeps,
            ResolverRequest,
        )

        rd = ResolvedDeps(
            entries=(LockedRequirement(name="pinned", version="==1.0"),)
        )
        meta = RequestMetadata(
            pipenv_version="2026.1.0", parent_pid=4242, deadline_seconds=30.0
        )
        req = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="dev",
            packages=self._sample_packages(),
            options=self._sample_options(),
            sources=self._sample_sources(),
            python_marker_override="3.10",
            extra_pip_args=("--no-deps", "--no-build-isolation"),
            resolved_default_deps=rd,
            metadata=meta,
        )
        wire = req.to_json_dict()
        round = ResolverRequest.from_json_dict(wire)
        assert round == req

    def test_request_wire_omits_none_values(self):
        """to_json_dict MUST omit None-valued keys (per A1 acceptance criteria)."""
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            ResolverRequest,
        )

        req = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=self._sample_packages(),
            options=self._sample_options(),
            sources=self._sample_sources(),
        )
        wire = req.to_json_dict()
        # No top-level key is None
        for k, v in wire.items():
            assert v is not None, f"key {k!r} serialized as None"
        # The optional fields are absent (not present as None)
        assert "python_marker_override" not in wire

    def test_response_success_roundtrip(self):
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            LockedRequirement,
            ResolverResponse,
            ResolverSuccess,
        )

        # Build the original with hashes ALREADY canonical (sorted) so the
        # round-trip-equality check is direct.  `to_json_dict` is documented
        # to sort hashes; the sort-determinism case is exercised separately
        # in `test_to_json_dict_sorts_hashes_and_extras` below.
        resp = ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=ResolverSuccess(
                kind="success",
                locked=(
                    LockedRequirement(name="foo", version="==1.0", hashes=("sha256:a", "sha256:b")),
                ),
            ),
        )
        wire = resp.to_json_dict()
        round = ResolverResponse.from_json_dict(wire)
        assert round == resp

    def test_response_resolution_error_roundtrip(self):
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            ConflictRecord,
            ResolutionError,
            ResolverResponse,
        )

        resp = ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=ResolutionError(
                kind="resolution_error",
                conflicts=(
                    ConflictRecord(package="foo", version="1.0", requires="bar>=2"),
                ),
                pip_message="some pip message",
            ),
        )
        wire = resp.to_json_dict()
        round = ResolverResponse.from_json_dict(wire)
        assert round == resp

    def test_response_internal_error_roundtrip(self):
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            InternalError,
            ResolverResponse,
        )

        resp = ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=InternalError(
                kind="internal_error",
                message="boom",
                traceback="Traceback...",
            ),
        )
        wire = resp.to_json_dict()
        round = ResolverResponse.from_json_dict(wire)
        assert round == resp

    def test_response_unknown_kind_raises(self):
        from pipenv.resolver.schema import SCHEMA_VERSION, ResolverResponse

        bad = {
            "schema_version": SCHEMA_VERSION,
            "result": {"kind": "not_a_real_kind"},
        }
        with pytest.raises(ValueError, match="kind"):
            ResolverResponse.from_json_dict(bad)

    def test_response_two_stage_schema_version_mismatch(self):
        """The first stage of from_json_dict must reject schema_version
        mismatch BEFORE attempting to dispatch on result.kind.

        Per design §3.6 / plan Risk #6, schema_version is the FIRST field on
        the envelope so a partial parse can still detect mismatch and produce
        a structured rejection.
        """
        from pipenv.resolver.schema import ResolverResponse

        # Result dict is intentionally malformed; the schema-version mismatch
        # must be reported before the malformed result is touched.
        bad = {
            "schema_version": 999,
            "result": "this is not even a dict — but parse must not reach here",
        }
        with pytest.raises(ValueError, match="schema"):
            ResolverResponse.from_json_dict(bad)

    def test_request_two_stage_schema_version_mismatch(self):
        from pipenv.resolver.schema import ResolverRequest

        bad = {"schema_version": 999, "category": "anything"}
        with pytest.raises(ValueError, match="schema"):
            ResolverRequest.from_json_dict(bad)

    def test_to_json_dict_sorts_hashes_and_extras(self):
        """LockedRequirement on the wire must sort hashes/extras for determinism."""
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            LockedRequirement,
            ResolverResponse,
            ResolverSuccess,
        )

        resp = ResolverResponse(
            schema_version=SCHEMA_VERSION,
            result=ResolverSuccess(
                kind="success",
                locked=(
                    LockedRequirement(
                        name="foo",
                        version="==1",
                        hashes=("sha256:zzz", "sha256:aaa", "sha256:mmm"),
                        extras=("zeta", "alpha"),
                    ),
                ),
            ),
        )
        wire = resp.to_json_dict()
        first = wire["result"]["locked"][0]
        assert first["hashes"] == ["sha256:aaa", "sha256:mmm", "sha256:zzz"]
        assert first["extras"] == ["alpha", "zeta"]

    def test_schema_version_constant_is_one(self):
        from pipenv.resolver.schema import SCHEMA_VERSION

        assert SCHEMA_VERSION == 1
