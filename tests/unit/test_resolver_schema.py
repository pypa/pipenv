"""Unit tests for the T_F.3 typed-resolver-schema module.

A1 introduced ``TestLockedRequirementInvariants`` and
``TestEnvelopeRoundtrip``.  Wave C extends the suite:

* C1 adds ``TestFromInstallRequirementParity`` (parametrised against the
  A1 golden snapshots in ``tests/unit/fixtures/resolver_schema/``),
  ``TestResolverResponseDispatch``, ``TestSchemaVersionMismatch``, and
  ``TestVCSPinAndExtras`` (one case per VCS backend).
* C3 adds ``TestCommaInMarkerRegression`` — the Q7 pin against the
  legacy ``str.split(",", 1)`` bug (F.1 §8 row 9).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Golden-snapshot directory committed by A1.
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "resolver_schema"
FORMAT_REQ_DIR = FIXTURE_DIR / "format_requirement_for_lockfile"
ENTRY_CLEANED_DIR = FIXTURE_DIR / "entry_get_cleaned_dict"


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


def _load_format_req_fixtures():
    """Yield ``(case_name, snapshot_dict)`` pairs from the A1 golden set.

    The plan target (16 cases) is enforced by an explicit length check
    so a missing fixture is loud, not silent.
    """
    paths = sorted(FORMAT_REQ_DIR.glob("*.json"))
    return [(p.stem, json.loads(p.read_text())) for p in paths]


def _load_entry_cleaned_fixtures():
    paths = sorted(ENTRY_CLEANED_DIR.glob("*.json"))
    return [(p.stem, json.loads(p.read_text())) for p in paths]


class TestFromInstallRequirementParity:
    """Parity gate: A1 golden snapshots round-trip through the typed schema.

    Per the C1 task description, the plan offered two parameterisation
    strategies:

    1. Reconstruct a pip ``InstallRequirement`` from each snapshot's wire
       form and call ``LockedRequirement.from_install_requirement``.
    2. Round-trip each snapshot's ``entry`` dict through
       ``LockedRequirement.from_lockfile_dict`` /
       ``to_lockfile_dict``.

    Strategy (1) is fragile because the A1 fixtures don't store the
    pre-construction state of the ``InstallRequirement`` (only the post-
    formatter dict).  We therefore use strategy (2): **shape-parity**.
    The input-level parity (real ``InstallRequirement`` -> typed schema)
    is C2's responsibility (integration suite).  Together C1 + C2 cover
    both directions: typed -> dict (here) and pip -> typed -> dict
    (there).
    """

    @pytest.mark.parametrize(
        ("case", "snapshot"),
        _load_format_req_fixtures(),
        ids=[case for case, _ in _load_format_req_fixtures()],
    )
    def test_format_req_snapshot_roundtrip(self, case, snapshot):
        """Each ``format_requirement_for_lockfile`` snapshot must round
        trip byte-for-byte through ``LockedRequirement``.
        """
        from pipenv.resolver.schema import LockedRequirement

        entry = snapshot["entry"]
        lr = LockedRequirement.from_lockfile_dict(entry)
        produced = lr.to_lockfile_dict()
        # Sorted-keys equality is the byte-for-byte guarantee: JSON
        # comparison via dict equality is order-insensitive, and
        # to_lockfile_dict already sorts hashes/extras.
        assert produced == entry, (
            f"snapshot {case!r} did not round-trip:\n"
            f"  expected: {entry}\n"
            f"  produced: {produced}"
        )

    @pytest.mark.parametrize(
        ("case", "snapshot"),
        _load_entry_cleaned_fixtures(),
        ids=[case for case, _ in _load_entry_cleaned_fixtures()],
    )
    def test_entry_cleaned_snapshot_roundtrip(self, case, snapshot):
        """Each ``Entry.get_cleaned_dict`` snapshot must also round trip.

        ``Entry.get_cleaned_dict`` was the subprocess-side dict cleaner;
        these snapshots exercise the simpler VCS-flat shape and the
        ``_clean_version`` / ``_clean_markers`` normalizations.
        """
        from pipenv.resolver.schema import LockedRequirement

        entry = snapshot["entry"]
        lr = LockedRequirement.from_lockfile_dict(entry)
        produced = lr.to_lockfile_dict()
        assert produced == entry, (
            f"snapshot {case!r} did not round-trip:\n"
            f"  expected: {entry}\n"
            f"  produced: {produced}"
        )

    def test_format_req_fixture_count_unchanged(self):
        """If a fixture is added or deleted, fail loud so the plan's
        coverage claim ("16 golden snapshots") stays honest.
        """
        assert len(_load_format_req_fixtures()) == 16

    def test_entry_cleaned_fixture_count_unchanged(self):
        """Mirror of the previous test for the A1 ``Entry.get_cleaned_dict``
        snapshot set (the plan documents 11 snapshots)."""
        assert len(_load_entry_cleaned_fixtures()) == 11


class TestResolverResponseDispatch:
    """``ResolverResponse.from_json_dict`` dispatches on ``result.kind``.

    Each kind in ``{"success", "resolution_error", "internal_error"}``
    must round-trip through ``to_json_dict`` -> ``from_json_dict`` with
    a result object of the correct concrete type.  An unknown ``kind``
    must raise ``ValueError``.
    """

    def test_dispatch_success(self):
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            LockedRequirement,
            ResolverResponse,
            ResolverSuccess,
        )

        wire = {
            "schema_version": SCHEMA_VERSION,
            "result": {
                "kind": "success",
                "locked": [{"name": "foo", "version": "==1.0"}],
            },
        }
        resp = ResolverResponse.from_json_dict(wire)
        assert isinstance(resp.result, ResolverSuccess)
        assert resp.result.kind == "success"
        assert len(resp.result.locked) == 1
        assert resp.result.locked[0] == LockedRequirement(
            name="foo", version="==1.0"
        )
        # Round-trip parity.
        assert ResolverResponse.from_json_dict(resp.to_json_dict()) == resp

    def test_dispatch_resolution_error(self):
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            ConflictRecord,
            ResolutionError,
            ResolverResponse,
        )

        wire = {
            "schema_version": SCHEMA_VERSION,
            "result": {
                "kind": "resolution_error",
                "conflicts": [
                    {"package": "foo", "version": "1.0", "requires": "bar>=2"},
                ],
                "pip_message": "Could not find a version that satisfies",
            },
        }
        resp = ResolverResponse.from_json_dict(wire)
        assert isinstance(resp.result, ResolutionError)
        assert resp.result.kind == "resolution_error"
        assert resp.result.conflicts == (
            ConflictRecord(package="foo", version="1.0", requires="bar>=2"),
        )
        assert resp.result.pip_message.startswith("Could not")
        assert ResolverResponse.from_json_dict(resp.to_json_dict()) == resp

    def test_dispatch_internal_error(self):
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            InternalError,
            ResolverResponse,
        )

        wire = {
            "schema_version": SCHEMA_VERSION,
            "result": {
                "kind": "internal_error",
                "message": "boom",
                "traceback": "Traceback (most recent call last):\n  ...\n",
            },
        }
        resp = ResolverResponse.from_json_dict(wire)
        assert isinstance(resp.result, InternalError)
        assert resp.result.kind == "internal_error"
        assert resp.result.message == "boom"
        assert "Traceback" in resp.result.traceback
        assert ResolverResponse.from_json_dict(resp.to_json_dict()) == resp

    def test_dispatch_unknown_kind_raises(self):
        from pipenv.resolver.schema import SCHEMA_VERSION, ResolverResponse

        wire = {
            "schema_version": SCHEMA_VERSION,
            "result": {"kind": "made_up_kind"},
        }
        with pytest.raises(ValueError, match="unknown result kind"):
            ResolverResponse.from_json_dict(wire)


class TestSchemaVersionMismatch:
    """The schema-version mismatch error must mention both versions.

    Per design Q2, the parent and child each refuse to parse a payload
    whose ``schema_version`` does not match the receiver's
    ``SCHEMA_VERSION``.  The error message must include both numbers so
    a human reading the structured ``InternalError`` can tell what to
    upgrade.
    """

    def test_response_mismatch_message_includes_both_versions(self):
        from pipenv.resolver.schema import SCHEMA_VERSION, ResolverResponse

        bad = {
            "schema_version": 999,
            "result": {"kind": "success", "locked": []},
        }
        with pytest.raises(ValueError) as exc_info:
            ResolverResponse.from_json_dict(bad)
        msg = str(exc_info.value)
        assert "999" in msg, f"received version missing from {msg!r}"
        assert str(SCHEMA_VERSION) in msg, (
            f"expected SCHEMA_VERSION={SCHEMA_VERSION} missing from {msg!r}"
        )

    def test_request_mismatch_message_includes_both_versions(self):
        from pipenv.resolver.schema import SCHEMA_VERSION, ResolverRequest

        bad = {
            "schema_version": 42,
            "category": "default",
            "packages": {"specs": {}},
            "options": {},
            "sources": [],
        }
        with pytest.raises(ValueError) as exc_info:
            ResolverRequest.from_json_dict(bad)
        msg = str(exc_info.value)
        assert "42" in msg, f"received version missing from {msg!r}"
        assert str(SCHEMA_VERSION) in msg, (
            f"expected SCHEMA_VERSION={SCHEMA_VERSION} missing from {msg!r}"
        )


class TestVCSPinAndExtras:
    """One round-trip case per VCS backend (git, hg, svn, bzr).

    Confirms ``VCSPin`` survives the JSON envelope on all four backends
    pipenv supports (``VCS_LIST`` in ``pipenv/utils/constants.py``) and
    that ``ref`` / ``subdirectory`` make it through unaltered.  Extras
    are bundled here because the wire-sort behaviour is exercised
    against arbitrary input order.
    """

    @pytest.mark.parametrize(
        ("backend", "url", "ref", "subdirectory"),
        [
            ("git", "https://github.com/foo/bar.git", "abc123", "subdir"),
            ("hg", "https://example.com/hg-pkg", "tip", None),
            ("svn", "svn://example.com/svn-pkg", "trunk", None),
            ("bzr", "bzr://example.com/bzr-pkg", "1.0", None),
        ],
    )
    def test_vcs_backend_roundtrip(self, backend, url, ref, subdirectory):
        from pipenv.resolver.schema import LockedRequirement, VCSPin

        pin = VCSPin(
            backend=backend, url=url, ref=ref, subdirectory=subdirectory
        )
        lr = LockedRequirement(
            name=f"{backend}-pkg",
            vcs=pin,
            extras=("zeta", "alpha"),  # Unsorted on purpose.
        )
        wire = lr.to_json_dict()
        assert wire["vcs"]["backend"] == backend
        assert wire["vcs"]["url"] == url
        if ref is not None:
            assert wire["vcs"]["ref"] == ref
        # Wire-side extras are sorted (determinism).
        assert wire["extras"] == ["alpha", "zeta"]
        round = LockedRequirement.from_json_dict(wire)
        assert round.vcs == pin
        # Extras tuple is sorted on the wire-out, so the round-tripped
        # value is the sorted order, NOT the original input order.
        assert round.extras == ("alpha", "zeta")
        assert round.name == lr.name

    @pytest.mark.parametrize(
        ("backend",),
        [("git",), ("hg",), ("svn",), ("bzr",)],
    )
    def test_vcs_backend_lockfile_roundtrip(self, backend):
        """Same coverage as above but via ``to_lockfile_dict`` /
        ``from_lockfile_dict`` so the flat top-level shape is exercised.
        """
        from pipenv.resolver.schema import LockedRequirement, VCSPin

        pin = VCSPin(
            backend=backend,
            url=f"https://example.com/{backend}-pkg",
            ref="ref-token",
            subdirectory="some/sub",
        )
        lr = LockedRequirement(name=f"{backend}-pkg", vcs=pin)
        flat = lr.to_lockfile_dict()
        # Backend key lives at the top level in the flat shape.
        assert backend in flat
        assert flat[backend] == pin.url
        assert flat["ref"] == "ref-token"
        assert flat["subdirectory"] == "some/sub"
        # No nested "vcs" dict in the flat form.
        assert "vcs" not in flat
        round = LockedRequirement.from_lockfile_dict(flat)
        assert round.vcs == pin
        assert round.name == lr.name


class TestCommaInMarkerRegression:
    """Regression: commas inside PEP 508 markers must survive the wire.

    Per plan §C3 / design Q7: the legacy constraints-tempfile parser used
    ``str.split(",", 1)`` to separate package name from pip-line
    (F.1 §8 row 9).  PEP 508 markers can contain commas
    (e.g. ``python_version >= "3.10", sys_platform == "linux"``), so the
    legacy parser silently corrupted those markers.

    The typed-schema replacement uses ``PackageSpecs.specs: dict[str, str]``
    — keys ARE the package names, values ARE the full pip-lines, so
    splitting on comma is no longer required.  This test pins that
    invariant: any commaful marker round-trips byte-for-byte through
    ``to_json_dict`` / ``from_json_dict``.
    """

    COMMAFUL_MARKER = 'python_version >= "3.10", sys_platform == "linux"'

    def test_commaful_marker_survives_package_specs(self):
        """A ``PackageSpecs`` value containing a comma round-trips."""
        from pipenv.resolver.schema import (
            SCHEMA_VERSION,
            PackageSpecs,
            ResolverOptions,
            ResolverRequest,
            Source,
        )

        # The pip-line carries the commaful marker; the typed dict-key
        # carries the bare name.  No splitting required.
        pip_line = f'commaful==1.0; {self.COMMAFUL_MARKER}'
        req = ResolverRequest(
            schema_version=SCHEMA_VERSION,
            category="default",
            packages=PackageSpecs(specs={"commaful": pip_line}),
            options=ResolverOptions(),
            sources=(Source(name="pypi", url="https://pypi.org/simple"),),
        )
        wire = req.to_json_dict()
        # Wire form preserves the comma byte-for-byte (this is the bit
        # the legacy str.split(",", 1) parser corrupted).
        assert wire["packages"]["specs"]["commaful"] == pip_line
        # The dict-key form means no splitting on the pip-line is ever
        # required: ``commaful`` -> pip-line is direct.
        assert list(wire["packages"]["specs"].keys()) == ["commaful"]
        # JSON-serialised form survives full round-trip (JSON escapes
        # the quotes inside the marker — ``"`` -> ``\"`` — which is
        # standard, but the comma stays bare).
        serialised = json.dumps(wire, sort_keys=True)
        assert ", sys_platform" in serialised, (
            "marker comma did not survive JSON serialisation"
        )
        reparsed = json.loads(serialised)
        assert reparsed["packages"]["specs"]["commaful"] == pip_line
        # Round-trip through the typed parser is byte-identical.
        round = ResolverRequest.from_json_dict(wire)
        assert round.packages.specs["commaful"] == pip_line
        assert round == req

    def test_commaful_marker_survives_locked_requirement(self):
        """A ``LockedRequirement.markers`` value with a comma round-trips."""
        from pipenv.resolver.schema import LockedRequirement

        lr = LockedRequirement(
            name="commaful",
            version="==1.0",
            markers=self.COMMAFUL_MARKER,
        )
        wire = lr.to_json_dict()
        assert wire["markers"] == self.COMMAFUL_MARKER
        round = LockedRequirement.from_json_dict(wire)
        assert round.markers == self.COMMAFUL_MARKER
        assert round == lr
