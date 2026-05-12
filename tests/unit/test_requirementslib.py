"""Tests for :mod:`pipenv.utils.requirementslib`.

The primary subject of this file is :func:`merge_items`, which has three
real call sites in pipenv: ``pipenv/utils/pipfile.py:318`` and
``pipenv/utils/locking.py:387,580``. These tests pin the observable
behaviour of those three call patterns so the implementation can be
refactored behaviour-preservingly.

Only the ``sourced=False`` signature is exercised: ``sourced=True`` has
no callers in the pipenv tree.
"""

from pipenv.utils.requirementslib import merge_items
from pipenv.vendor import tomlkit


# ---------------------------------------------------------------------------
# Pattern 1: pipfile.py:318 -- merge_items([deps_dict, dict(packages_table)])
# ---------------------------------------------------------------------------


def test_merge_items_pipfile_shape_empty_plus_plain_dict():
    """The base call from get_deps when no dev-packages have been added:
    ``merge_items([{}, dict(self.pipfile._data.get("packages", {}))])``.

    The outer container is a plain dict; the second arg's keys all win
    because the first is empty.
    """
    deps = {}
    packages = {"requests": "*", "flask": ">=1.0"}
    result = merge_items([deps, packages])
    assert result == {"requests": "*", "flask": ">=1.0"}
    assert isinstance(result, dict)


def test_merge_items_pipfile_shape_with_tomlkit_inline_table_entries():
    """Real-world Pipfile data has tomlkit InlineTable values for entries
    like ``flask = {version = ">=1.0", extras = ["async"]}``. After
    ``dict(packages_table)``, the outer is a plain dict but the inner
    values remain InlineTables. ``merge_items`` must preserve the
    InlineTable type so downstream ``tomlkit_value_to_python`` can
    flatten it correctly.
    """
    doc = tomlkit.parse(
        """
[packages]
requests = "*"
flask = {version = ">=1.0", extras = ["async"]}
"""
    )
    deps = {}
    packages = dict(doc.get("packages", {}))

    result = merge_items([deps, packages])

    assert set(result.keys()) == {"requests", "flask"}
    assert result["requests"] == "*"
    # The InlineTable entry must survive the merge as a dict-like mapping
    # so callers can index it by key (e.g. result["flask"]["version"]).
    flask_entry = result["flask"]
    assert isinstance(flask_entry, dict)
    assert flask_entry["version"] == ">=1.0"
    # `extras` is present (whatever its type or contents).
    assert "extras" in flask_entry


# ---------------------------------------------------------------------------
# Pattern 2: locking.py:387 -- merge_items([deps, self.default._data])
# ---------------------------------------------------------------------------


def test_merge_items_locking_shape_empty_plus_lock_default():
    """``self.default._data`` in plette lockfiles is a plain Python dict
    (lockfiles are JSON-loaded, no tomlkit involved). The merge of an
    empty dict with the default category should return the default
    category's contents unchanged in shape.
    """
    deps = {}
    default = {
        "requests": {
            "version": "==2.31.0",
            "hashes": ["sha256:abc", "sha256:def"],
            "markers": "python_version >= '3.7'",
        },
        "urllib3": {"version": "==2.0.0", "hashes": ["sha256:xyz"]},
    }
    result = merge_items([deps, default])
    assert isinstance(result, dict)
    assert set(result.keys()) == {"requests", "urllib3"}
    assert result["requests"]["version"] == "==2.31.0"
    assert result["urllib3"]["version"] == "==2.0.0"


def test_merge_items_locking_shape_develop_plus_default_recursive_merge():
    """``get_deps(dev=True, only=False)`` builds ``deps`` from
    ``self.develop._data`` then calls
    ``merge_items([deps, self.default._data])``. When the two categories
    share a package name, the default's entry wins at the top-level key,
    and any sub-fields merge recursively (last-write-wins).
    """
    develop = {
        "pytest": {"version": "==7.0", "hashes": ["sha256:111"]},
        "requests": {"version": "==2.28.0"},
    }
    default = {
        "requests": {"version": "==2.31.0", "hashes": ["sha256:222"]},
        "urllib3": {"version": "==2.0.0"},
    }
    result = merge_items([develop, default])
    # Union of top-level keys
    assert set(result.keys()) == {"pytest", "requests", "urllib3"}
    # Develop-only entry preserved.
    assert result["pytest"]["version"] == "==7.0"
    # Default-only entry present.
    assert result["urllib3"]["version"] == "==2.0.0"
    # Conflict: default's value wins at the recursive level (later in the
    # target_list overwrites earlier).
    assert result["requests"]["version"] == "==2.31.0"


# ---------------------------------------------------------------------------
# Pattern 3: locking.py:580 -- merge_items([deps, category_deps]) in a loop
# ---------------------------------------------------------------------------


def test_merge_items_locking_loop_pattern_accumulates_across_categories():
    """``get_requirements(categories=[...])`` loops over user-specified
    categories and folds each into a running ``deps`` dict via
    ``merge_items([deps, category_deps])``. Verify the loop-fold
    accumulates correctly across multiple iterations.
    """
    categories = [
        {"pkg-a": {"version": "==1.0"}},
        {"pkg-b": {"version": "==2.0"}},
        {"pkg-c": {"version": "==3.0"}},
    ]
    deps = {}
    for category_deps in categories:
        deps = merge_items([deps, category_deps])
    assert isinstance(deps, dict)
    assert set(deps.keys()) == {"pkg-a", "pkg-b", "pkg-c"}
    assert deps["pkg-a"]["version"] == "==1.0"
    assert deps["pkg-b"]["version"] == "==2.0"
    assert deps["pkg-c"]["version"] == "==3.0"


# ---------------------------------------------------------------------------
# Signature contract: sourced=False is the default and the only used path
# ---------------------------------------------------------------------------


def test_merge_items_default_signature_returns_merged_dict():
    """``merge_items(target_list)`` with no ``sourced`` arg uses the
    default ``sourced=False`` path and returns a single merged dict
    (not a ``(merged, source_map)`` tuple).
    """
    result = merge_items([{"a": 1}, {"b": 2}])
    # Single value, not a tuple.
    assert isinstance(result, dict)
    assert result == {"a": 1, "b": 2}


def test_merge_items_handles_empty_target_list():
    """An empty target list should not crash; the three production
    call sites never call it with an empty list, but the function
    should still be defined for that edge case.
    """
    # Current behaviour returns None for an empty list; we pin that to
    # catch any accidental change.
    result = merge_items([])
    assert result is None


def test_merge_items_scalar_overwrite():
    """When the same key maps to a scalar in two dicts, the later
    entry in ``target_list`` wins.
    """
    result = merge_items([{"x": "first"}, {"x": "second"}])
    assert result == {"x": "second"}
