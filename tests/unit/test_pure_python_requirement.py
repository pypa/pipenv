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
