"""Unit tests for :mod:`pipenv.resolver.pure_python_requirement`
(Initiative G Phase 3, T1).

This file is the RED-phase test suite that pins T1's contract.  T11
extends this file later with the broader coverage matrix; the minimum
acceptance gate from the plan brief is:

* Round-trip construction with every field set; per-field accessors
  return what we passed in.
* Equality + hashability — instances must be usable inside a
  ``frozenset``.
* :meth:`Requirement.from_pipfile_entry` handles the three canonical
  Pipfile shapes:

  - ``"*"`` → empty ``SpecifierSet``.
  - ``">=4.0,<6"`` → parsed ``SpecifierSet``.
  - dict ``{"version": ">=4.0", "extras": ["argon2"]}`` → extras
    populated, version parsed.

* Name canonicalisation: ``Django_Rest`` → ``django-rest``.

Everything else (negative paths, marker handling on dict form, the
``constraint`` source label, etc.) is covered by T11.
"""

from __future__ import annotations

import pytest

from pipenv.resolver.pure_python_requirement import Requirement
from pipenv.vendor.packaging.markers import Marker
from pipenv.vendor.packaging.specifiers import SpecifierSet

# ---------------------------------------------------------------------------
# Round-trip + per-field accessors
# ---------------------------------------------------------------------------


def test_requirement_round_trip_all_fields() -> None:
    """A Requirement built with every field set returns every field set."""
    spec = SpecifierSet(">=4.0,<6")
    marker = Marker("python_version >= '3.10'")
    req = Requirement(
        name="django",
        specifier=spec,
        extras=frozenset({"argon2"}),
        marker=marker,
        source="pipfile",
        parent=None,
    )
    assert req.name == "django"
    assert req.specifier == spec
    assert req.extras == frozenset({"argon2"})
    assert req.marker == marker
    assert req.source == "pipfile"
    assert req.parent is None


def test_requirement_transitive_with_parent() -> None:
    """Transitive requirements carry the parent candidate name."""
    req = Requirement(
        name="urllib3",
        specifier=SpecifierSet(">=1.26"),
        extras=frozenset(),
        marker=None,
        source="transitive",
        parent="requests",
    )
    assert req.source == "transitive"
    assert req.parent == "requests"


# ---------------------------------------------------------------------------
# Equality + hashability (frozenset membership)
# ---------------------------------------------------------------------------


def test_requirement_equality_same_fields() -> None:
    """Two Requirements with identical fields compare equal and hash equal."""
    a = Requirement(
        name="django",
        specifier=SpecifierSet(">=4.0"),
        extras=frozenset({"argon2"}),
        marker=None,
        source="pipfile",
        parent=None,
    )
    b = Requirement(
        name="django",
        specifier=SpecifierSet(">=4.0"),
        extras=frozenset({"argon2"}),
        marker=None,
        source="pipfile",
        parent=None,
    )
    assert a == b
    assert hash(a) == hash(b)


def test_requirement_inequality_on_extras() -> None:
    """Different extras → unequal requirements."""
    a = Requirement(
        name="django",
        specifier=SpecifierSet(">=4.0"),
        extras=frozenset({"argon2"}),
        marker=None,
        source="pipfile",
        parent=None,
    )
    b = Requirement(
        name="django",
        specifier=SpecifierSet(">=4.0"),
        extras=frozenset(),
        marker=None,
        source="pipfile",
        parent=None,
    )
    assert a != b


def test_requirement_is_frozenset_member() -> None:
    """Requirement must be usable inside a ``frozenset`` (resolvelib needs this)."""
    a = Requirement(
        name="django",
        specifier=SpecifierSet(">=4.0"),
        extras=frozenset(),
        marker=None,
        source="pipfile",
        parent=None,
    )
    b = Requirement(
        name="django",
        specifier=SpecifierSet(">=4.0"),
        extras=frozenset(),
        marker=None,
        source="pipfile",
        parent=None,
    )
    bag = frozenset({a, b})
    # Equal objects collapse to a single member.
    assert len(bag) == 1
    assert a in bag


def test_requirement_is_frozen() -> None:
    """Frozen dataclass refuses attribute assignment."""
    req = Requirement(
        name="django",
        specifier=SpecifierSet(""),
        extras=frozenset(),
        marker=None,
        source="pipfile",
        parent=None,
    )
    with pytest.raises((AttributeError, Exception)):
        req.name = "flask"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# from_pipfile_entry shapes
# ---------------------------------------------------------------------------


def test_from_pipfile_entry_star_is_empty_specifier() -> None:
    """``"*"`` → empty ``SpecifierSet`` (any version is acceptable)."""
    req = Requirement.from_pipfile_entry("django", "*")
    assert req.name == "django"
    assert req.specifier == SpecifierSet("")
    assert len(list(req.specifier)) == 0
    assert req.extras == frozenset()
    assert req.marker is None
    assert req.source == "pipfile"


def test_from_pipfile_entry_string_specifier() -> None:
    """A bare string is parsed as a specifier."""
    req = Requirement.from_pipfile_entry("django", ">=4.0,<6")
    assert req.name == "django"
    assert req.specifier == SpecifierSet(">=4.0,<6")
    assert req.extras == frozenset()


def test_from_pipfile_entry_dict_with_extras() -> None:
    """Dict form populates version + extras."""
    req = Requirement.from_pipfile_entry(
        "django", {"version": ">=4.0", "extras": ["argon2"]}
    )
    assert req.name == "django"
    assert req.specifier == SpecifierSet(">=4.0")
    assert req.extras == frozenset({"argon2"})


def test_from_pipfile_entry_dict_star_version() -> None:
    """Dict form with ``"version": "*"`` → empty SpecifierSet."""
    req = Requirement.from_pipfile_entry("django", {"version": "*"})
    assert req.specifier == SpecifierSet("")


def test_from_pipfile_entry_dict_with_markers() -> None:
    """Dict form parses a markers string into a Marker."""
    req = Requirement.from_pipfile_entry(
        "django",
        {"version": ">=4.0", "markers": "python_version >= '3.10'"},
    )
    assert req.marker is not None
    assert str(req.marker) == str(Marker("python_version >= '3.10'"))


def test_from_pipfile_entry_canonicalizes_name() -> None:
    """``Django_Rest`` → ``django-rest`` (PEP 503)."""
    req = Requirement.from_pipfile_entry("Django_Rest", "*")
    assert req.name == "django-rest"


def test_from_pipfile_entry_source_default_is_pipfile() -> None:
    """Default ``source`` for a Pipfile entry is ``"pipfile"``."""
    req = Requirement.from_pipfile_entry("django", "*")
    assert req.source == "pipfile"


def test_from_pipfile_entry_source_override() -> None:
    """Caller may override ``source`` (e.g. for constraint entries)."""
    req = Requirement.from_pipfile_entry(
        "django", ">=4.0", source="constraint"
    )
    assert req.source == "constraint"


def test_from_pipfile_entry_parent_propagates() -> None:
    """``parent`` keyword propagates onto the resulting Requirement."""
    req = Requirement.from_pipfile_entry(
        "urllib3",
        ">=1.26",
        source="transitive",
        parent="requests",
    )
    assert req.parent == "requests"
    assert req.source == "transitive"


# ---------------------------------------------------------------------------
# T11 extension — coverage matrix
# ---------------------------------------------------------------------------
#
# The 15 tests above (added under T1) hit 97 % of
# ``pipenv/resolver/pure_python_requirement.py`` on their own; this
# section pins the remaining branch (the unsupported-shape ``TypeError``)
# and the edge cases enumerated in initiative-g-phase3-plan.md T11:
# dict shapes that include keys the dataclass deliberately ignores
# (editable / VCS), empty + whitespace version strings, marker /
# extras / version mixed, the canonicalisation corner-cases, the
# ``source`` Literal escape hatch.


def test_from_pipfile_entry_rejects_unsupported_value_type() -> None:
    """Non-str / non-dict values raise ``TypeError`` with a clear message.

    Covers the ``else`` branch at the bottom of ``from_pipfile_entry``
    (line 174 of pure_python_requirement.py) — the loud-failure rail
    for upstream-parser bugs.
    """
    with pytest.raises(TypeError) as exc_info:
        Requirement.from_pipfile_entry("django", 42)  # type: ignore[arg-type]
    msg = str(exc_info.value)
    assert "django" in msg
    assert "int" in msg


def test_from_pipfile_entry_rejects_list_value() -> None:
    """A list is also rejected (only str / dict are valid)."""
    with pytest.raises(TypeError) as exc_info:
        Requirement.from_pipfile_entry(
            "django", [">=4.0"]  # type: ignore[arg-type]
        )
    assert "list" in str(exc_info.value)


def test_from_pipfile_entry_rejects_none_value() -> None:
    """``None`` is not a valid Pipfile entry shape — raise TypeError."""
    with pytest.raises(TypeError):
        Requirement.from_pipfile_entry(
            "django", None  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Dict-form variants — keys the constraint node deliberately ignores
# ---------------------------------------------------------------------------


def test_from_pipfile_entry_dict_with_editable_key_ignored() -> None:
    """``editable=True`` on the Pipfile dict is silently ignored.

    T11 audit: ``from_pipfile_entry`` builds the *constraint* node only —
    it consumes ``version`` / ``extras`` / ``markers`` and leaves
    artefact-shape keys (``editable``, ``path``, ``git``, ``ref``,
    ``index``, ...) for the Candidate / VCS pipeline.  The pure-Python
    backend doesn't support VCS / editable sources in Phase 3, but
    rejecting them at the constraint-construction layer would be
    premature: Pipfile parsing upstream is expected to route those
    entries away from the pure-python provider.  We pin the current
    "silently ignore" behaviour so a future hardening pass is explicit.
    """
    req = Requirement.from_pipfile_entry(
        "django", {"version": "*", "editable": True}
    )
    assert req.name == "django"
    assert req.specifier == SpecifierSet("")
    assert req.extras == frozenset()
    assert req.marker is None


def test_from_pipfile_entry_dict_with_vcs_keys_ignored() -> None:
    """``git`` / ``ref`` keys on the dict are ignored — see audit note above."""
    req = Requirement.from_pipfile_entry(
        "django",
        {
            "git": "https://github.com/django/django.git",
            "ref": "main",
            "version": "*",
        },
    )
    # The constraint emerges with an empty SpecifierSet — VCS routing
    # is the caller's problem, not Requirement's.
    assert req.specifier == SpecifierSet("")


def test_from_pipfile_entry_dict_with_index_and_path_keys_ignored() -> None:
    """``index`` / ``path`` keys on the dict are ignored — same rationale."""
    req = Requirement.from_pipfile_entry(
        "django",
        {"version": ">=4.0", "index": "pypi", "path": "./local"},
    )
    assert req.specifier == SpecifierSet(">=4.0")


# ---------------------------------------------------------------------------
# Specifier corner cases
# ---------------------------------------------------------------------------


def test_from_pipfile_entry_dict_without_version_key() -> None:
    """A dict missing ``version`` falls through to ``"*"`` (empty specifier)."""
    req = Requirement.from_pipfile_entry("django", {"extras": ["argon2"]})
    assert req.specifier == SpecifierSet("")
    assert req.extras == frozenset({"argon2"})


def test_from_pipfile_entry_dict_with_empty_version_string() -> None:
    """``"version": ""`` is treated the same as ``"*"`` — empty SpecifierSet.

    Covers the ``spec_string in (None, "", "*")`` branch when the
    dict supplies an explicit empty string.
    """
    req = Requirement.from_pipfile_entry("django", {"version": ""})
    assert req.specifier == SpecifierSet("")


def test_from_pipfile_entry_bare_empty_string_is_empty_specifier() -> None:
    """A bare ``""`` value also flattens to an empty SpecifierSet (no error)."""
    req = Requirement.from_pipfile_entry("django", "")
    assert req.specifier == SpecifierSet("")


def test_from_pipfile_entry_string_with_whitespace_normalised() -> None:
    """SpecifierSet strips surrounding whitespace — round-trip equality holds."""
    req = Requirement.from_pipfile_entry("django", "  >=4.0,<6  ")
    assert req.specifier == SpecifierSet(">=4.0,<6")


# ---------------------------------------------------------------------------
# Combined extras + markers + version
# ---------------------------------------------------------------------------


def test_from_pipfile_entry_dict_with_version_extras_and_markers() -> None:
    """Dict with all three Pipfile-relevant keys populates all three fields."""
    req = Requirement.from_pipfile_entry(
        "django",
        {
            "version": ">=4.0",
            "extras": ["argon2", "bcrypt"],
            "markers": "python_version >= '3.10'",
        },
    )
    assert req.specifier == SpecifierSet(">=4.0")
    assert req.extras == frozenset({"argon2", "bcrypt"})
    assert req.marker is not None
    assert str(req.marker) == str(Marker("python_version >= '3.10'"))


def test_from_pipfile_entry_dict_with_extras_none_treated_as_empty() -> None:
    """``"extras": None`` flattens to an empty frozenset (``or ()`` guard)."""
    req = Requirement.from_pipfile_entry(
        "django", {"version": "*", "extras": None}
    )
    assert req.extras == frozenset()


def test_from_pipfile_entry_dict_with_markers_none() -> None:
    """``"markers": None`` results in ``marker is None`` (falsy branch)."""
    req = Requirement.from_pipfile_entry(
        "django", {"version": "*", "markers": None}
    )
    assert req.marker is None


def test_from_pipfile_entry_dict_with_empty_markers_string() -> None:
    """``"markers": ""`` is falsy → ``marker is None``."""
    req = Requirement.from_pipfile_entry(
        "django", {"version": "*", "markers": ""}
    )
    assert req.marker is None


def test_from_pipfile_entry_extras_iterable_coerces_to_strings() -> None:
    """Each extra is run through ``str()`` — non-string iterables coerce."""
    # The dataclass field is ``frozenset[str]``; the loud-failure
    # contract is that *some* iterable yields *some* values that
    # ``str(...)`` accepts.  This pins the coercion.
    req = Requirement.from_pipfile_entry(
        "django", {"version": "*", "extras": ("argon2",)}
    )
    assert req.extras == frozenset({"argon2"})


# ---------------------------------------------------------------------------
# Name canonicalisation corner cases
# ---------------------------------------------------------------------------


def test_from_pipfile_entry_canonicalises_dots_and_underscores() -> None:
    """``"Foo.Bar_Baz"`` → ``"foo-bar-baz"`` (PEP 503 corner case)."""
    req = Requirement.from_pipfile_entry("Foo.Bar_Baz", "*")
    assert req.name == "foo-bar-baz"


def test_from_pipfile_entry_canonicalises_mixed_separator_runs() -> None:
    """Mixed runs of ``_`` / ``-`` / ``.`` collapse per PEP 503."""
    req = Requirement.from_pipfile_entry("a__b--c..d", "*")
    assert req.name == "a-b-c-d"


def test_from_pipfile_entry_canonicalises_numeric_prefix() -> None:
    """``"3M"`` → ``"3m"`` — numeric-prefixed names are valid and lowercased."""
    req = Requirement.from_pipfile_entry("3M", "*")
    assert req.name == "3m"


# ---------------------------------------------------------------------------
# ``source`` Literal — runtime semantics
# ---------------------------------------------------------------------------


def test_requirement_source_literal_not_enforced_at_runtime() -> None:
    """``source`` is a ``typing.Literal`` — static checkers reject bad values
    but the runtime does not.

    T11 audit: the dataclass deliberately omits a ``__post_init__``
    runtime check on ``source``.  The rationale (per
    pure_python_requirement.py line 45–49): pyright / mypy catch
    typos at authoring time; spending CPU on a runtime branch check
    inside the resolver's hot loop is wasteful.  We pin the
    "no runtime guard" behaviour so a future contributor who adds
    validation has to update this test deliberately.
    """
    req = Requirement(
        name="django",
        specifier=SpecifierSet(""),
        extras=frozenset(),
        marker=None,
        source="not-a-valid-value",  # type: ignore[arg-type]
        parent=None,
    )
    # No exception raised; the value flows through verbatim.
    assert req.source == "not-a-valid-value"


def test_from_pipfile_entry_source_literal_passthrough() -> None:
    """``from_pipfile_entry`` does not validate ``source`` either —
    matches the dataclass-level audit above."""
    req = Requirement.from_pipfile_entry(
        "django", "*", source="bogus"  # type: ignore[arg-type]
    )
    assert req.source == "bogus"
