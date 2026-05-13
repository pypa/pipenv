"""Unit tests for the ``pipenv.utils.pipfile.Pipfile`` subsystem.

These tests pin the behaviour of the ``Pipfile`` subsystem that was
extracted from ``pipenv.project.Project`` in task T_D.6 (the fifth and
final Initiative D extraction). They cover the constructor, the
``@cached_property`` ``Project.pipfile`` accessor, the location /
existence / name / project-directory accessors, the mtime-invalidated
``parsed`` cache, ``read`` / ``is_empty`` / ``write_toml`` round-trip
semantics, section / category accessors, build-system parsing, scripts,
proper-names DB, hash computation, package add/remove mutators, and
the case-fixing helpers.

A few of the section accessors (``packages``, ``dev_packages``,
``all_packages``, ``package_names``) are smoke-tested for shape only —
the heavy mutation paths exercise them indirectly.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from pipenv.project import Project
from pipenv.utils.pipfile import NON_CATEGORY_SECTIONS, Pipfile

PIPFILE_BARE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]

[dev-packages]
"""

PIPFILE_WITH_PACKAGES = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"
flask = "==2.0.0"

[dev-packages]
pytest = "*"

[requires]
python_version = "3.11"

[scripts]
test = "pytest tests/"

[build-system]
requires = ["setuptools>=40.8.0", "wheel"]
"""


@pytest.fixture
def project_bare(tmp_path, monkeypatch):
    """Project with a minimal Pipfile, no lockfile."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_BARE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    return Project(chdir=False)


@pytest.fixture
def project_with_packages(tmp_path, monkeypatch):
    """Project with a more populated Pipfile."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_WITH_PACKAGES)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    return Project(chdir=False)


@pytest.fixture
def project_no_pipfile(tmp_path, monkeypatch):
    """Project where no Pipfile exists on disk."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    return Project(chdir=False)


# ---- Constructor / accessor -----------------------------------------------


@pytest.mark.utils
def test_pipfile_constructor_takes_project(project_bare):
    """``Pipfile(project)`` accepts a ``Project`` back-reference."""
    pf = Pipfile(project_bare)
    assert pf._project is project_bare


@pytest.mark.utils
def test_project_pipfile_returns_pipfile_subsystem(project_bare):
    """``project.pipfile`` returns a cached ``Pipfile`` instance."""
    assert isinstance(project_bare.pipfile, Pipfile)
    # Cached: two accesses return the same instance.
    assert project_bare.pipfile is project_bare.pipfile


# ---- Location / existence / name -----------------------------------------


@pytest.mark.utils
def test_location_resolves_to_pipfile_path(project_bare, tmp_path):
    assert project_bare.pipfile.location == str(tmp_path / "Pipfile")


@pytest.mark.utils
def test_exists_when_file_present(project_bare):
    assert project_bare.pipfile.exists is True


@pytest.mark.utils
def test_exists_when_file_absent(project_no_pipfile):
    assert project_no_pipfile.pipfile.exists is False


@pytest.mark.utils
def test_name_is_parent_dir_slug(project_bare, tmp_path):
    assert project_bare.pipfile.name == tmp_path.name


@pytest.mark.utils
def test_project_directory_is_parent_of_pipfile(project_bare, tmp_path):
    assert project_bare.pipfile.project_directory == str(tmp_path.absolute())


# ---- requirements.txt sibling --------------------------------------------


@pytest.mark.utils
def test_requirements_exists_false_when_no_requirements(project_bare):
    # Bare project has no requirements.txt.
    assert project_bare.pipfile.requirements_exists is False


# ---- required_python_version --------------------------------------------


@pytest.mark.utils
def test_required_python_version_none_when_no_pipfile(project_no_pipfile):
    assert project_no_pipfile.pipfile.required_python_version is None


@pytest.mark.utils
def test_required_python_version_reads_requires_section(project_with_packages):
    assert project_with_packages.pipfile.required_python_version == "3.11"


# ---- parsed cache + mtime invalidation -----------------------------------


@pytest.mark.utils
def test_parsed_pipfile_caches_between_accesses(project_bare):
    """``parsed`` returns the same document across back-to-back reads
    without re-parsing the file."""
    with mock.patch.object(Pipfile, "_parse", wraps=Pipfile._parse) as spy:
        first = project_bare.pipfile.parsed
        second = project_bare.pipfile.parsed
    assert first is second
    assert spy.call_count == 1


@pytest.mark.utils
def test_parsed_pipfile_reparses_when_mtime_changes(project_with_packages, tmp_path):
    """When the on-disk file changes (mtime bump), the next ``parsed``
    access re-reads the file."""
    _ = project_with_packages.pipfile.parsed  # prime cache
    pipfile = tmp_path / "Pipfile"
    updated = PIPFILE_WITH_PACKAGES.replace('flask = "==2.0.0"', 'django = "*"')
    stat = pipfile.stat()
    pipfile.write_text(updated)
    # Bump mtime deterministically (coarse mtime resolutions).
    os.utime(pipfile, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    with mock.patch.object(Pipfile, "_parse", wraps=Pipfile._parse) as spy:
        reparsed = project_with_packages.pipfile.parsed
    assert spy.call_count == 1
    assert "django" in reparsed.get("packages", {})


# ---- write_toml round-trip + cache invalidation -------------------------


@pytest.mark.utils
def test_write_toml_persists_to_disk_and_invalidates_cache(
    project_with_packages, tmp_path
):
    """``write_toml(...)`` writes to the Pipfile and drops the cache so
    the next read picks up the new contents."""
    doc = project_with_packages.pipfile.parsed
    doc["packages"]["newpkg"] = "*"
    project_with_packages.pipfile.write_toml(doc)

    on_disk = (tmp_path / "Pipfile").read_text()
    assert "newpkg" in on_disk

    # Cache invalidated, re-parse happens on next access.
    with mock.patch.object(Pipfile, "_parse", wraps=Pipfile._parse) as spy:
        reloaded = project_with_packages.pipfile.parsed
    assert spy.call_count == 1
    assert "newpkg" in reloaded.get("packages", {})


@pytest.mark.utils
def test_write_toml_to_other_path_does_not_invalidate_cache(
    project_with_packages, tmp_path
):
    """Writing to a path that is NOT the Pipfile must not drop the cache."""
    doc = project_with_packages.pipfile.parsed
    other = tmp_path / "snapshot.toml"
    project_with_packages.pipfile.write_toml(doc, path=str(other))

    with mock.patch.object(Pipfile, "_parse", wraps=Pipfile._parse) as spy:
        again = project_with_packages.pipfile.parsed
    assert spy.call_count == 0
    assert again is doc


# ---- read / is_empty ------------------------------------------------------


@pytest.mark.utils
def test_read_returns_file_contents(project_bare):
    contents = project_bare.pipfile.read()
    assert contents.startswith("[[source]]")


@pytest.mark.utils
def test_read_returns_empty_string_when_no_pipfile(project_no_pipfile):
    assert project_no_pipfile.pipfile.read() == ""


@pytest.mark.utils
def test_is_empty_true_when_no_pipfile(project_no_pipfile):
    assert project_no_pipfile.pipfile.is_empty is True


@pytest.mark.utils
def test_is_empty_false_when_pipfile_has_contents(project_bare):
    assert project_bare.pipfile.is_empty is False


# ---- section / category accessors ----------------------------------------


@pytest.mark.utils
def test_get_section_returns_packages(project_with_packages):
    pkgs = project_with_packages.pipfile.get_section("packages")
    assert "requests" in pkgs


@pytest.mark.utils
def test_get_section_returns_empty_dict_for_missing_section(project_bare):
    assert project_bare.pipfile.get_section("unknown") == {}


@pytest.mark.utils
def test_get_package_categories_defaults_to_packages_first(project_with_packages):
    cats = project_with_packages.pipfile.get_package_categories()
    # Must start with the two canonical categories.
    assert cats[:2] == ["packages", "dev-packages"]


@pytest.mark.utils
def test_get_package_categories_lockfile_form_renames_to_default_develop(
    project_with_packages,
):
    cats = project_with_packages.pipfile.get_package_categories(for_lockfile=True)
    assert cats[:2] == ["default", "develop"]


@pytest.mark.utils
def test_get_package_categories_excludes_non_category_sections(
    project_with_packages,
):
    cats = project_with_packages.pipfile.get_package_categories()
    for excluded in NON_CATEGORY_SECTIONS:
        assert excluded not in cats


@pytest.mark.utils
def test_package_names_includes_combined_set(project_with_packages):
    names = project_with_packages.pipfile.package_names
    assert "combined" in names
    assert "requests" in names["combined"]
    assert "pytest" in names["combined"]


# ---- build-system --------------------------------------------------------


@pytest.mark.utils
def test_build_requires_reads_pyproject_style_block(project_with_packages):
    reqs = project_with_packages.pipfile.build_requires
    assert "setuptools>=40.8.0" in reqs
    assert "wheel" in reqs


@pytest.mark.utils
def test_build_requires_empty_when_no_pipfile(project_no_pipfile):
    assert project_no_pipfile.pipfile.build_requires == []


@pytest.mark.utils
def test_build_requires_empty_when_no_build_system_section(project_bare):
    assert project_bare.pipfile.build_requires == []


# ---- scripts -------------------------------------------------------------


@pytest.mark.utils
def test_has_script_finds_defined_script(project_with_packages):
    assert project_with_packages.pipfile.has_script("test") is True


@pytest.mark.utils
def test_has_script_missing_script_returns_false(project_with_packages):
    assert project_with_packages.pipfile.has_script("missing") is False


@pytest.mark.utils
def test_build_script_returns_script_object(project_with_packages):
    script = project_with_packages.pipfile.build_script("test")
    assert script is not None
    # The script.cmd shape carries the command name.
    assert script.command == "pytest"


# ---- package mutators ----------------------------------------------------


@pytest.mark.utils
def test_remove_package_drops_entry_and_writes(project_with_packages, tmp_path):
    ok = project_with_packages.pipfile.remove_package("flask", category="packages")
    assert ok is True
    on_disk = (tmp_path / "Pipfile").read_text()
    assert "flask" not in on_disk


@pytest.mark.utils
def test_remove_package_returns_false_when_missing(project_with_packages):
    ok = project_with_packages.pipfile.remove_package("nope", category="packages")
    assert ok is False


@pytest.mark.utils
def test_reset_category_clears_entries(project_with_packages, tmp_path):
    project_with_packages.pipfile.reset_category("packages")
    parsed = project_with_packages.pipfile.parsed
    assert dict(parsed.get("packages", {})) == {}


@pytest.mark.utils
def test_remove_packages_bulk_drops_named_entries(project_with_packages):
    project_with_packages.pipfile.remove_packages(["flask", "pytest"])
    parsed = project_with_packages.pipfile.parsed
    assert "flask" not in parsed.get("packages", {})
    assert "pytest" not in parsed.get("dev-packages", {})


# ---- key lookup / casing --------------------------------------------------


@pytest.mark.utils
def test_get_package_name_returns_canonical_match(project_with_packages):
    # The Pipfile has ``flask``; querying with mixed casing should find it.
    name = project_with_packages.pipfile.get_package_name("FLASK", "packages")
    assert name == "flask"


@pytest.mark.utils
def test_get_entry_returns_pipfile_entry(project_with_packages):
    entry = project_with_packages.pipfile.get_entry("flask", "packages")
    assert entry == "==2.0.0"


@pytest.mark.utils
def test_get_entry_returns_none_for_missing_key(project_with_packages):
    assert project_with_packages.pipfile.get_entry("missing", "packages") is None


# ---- add_entry / add_package --------------------------------------------


@pytest.mark.utils
def test_add_entry_appends_to_category(project_with_packages, tmp_path):
    newly, cat, normalized = project_with_packages.pipfile.add_entry(
        "django", "django", "*", category="packages"
    )
    assert newly is True
    assert cat == "packages"
    assert normalized == "django"
    on_disk = (tmp_path / "Pipfile").read_text()
    assert "django" in on_disk


# ---- hash ----------------------------------------------------------------


@pytest.mark.utils
def test_calculate_hash_returns_hex_digest(project_bare):
    h = project_bare.pipfile.calculate_hash()
    assert isinstance(h, str)
    assert len(h) == 64  # sha256 hex length
    # Stable across calls when the file does not change.
    assert h == project_bare.pipfile.calculate_hash()


@pytest.mark.utils
def test_calculate_hash_is_casing_invariant(tmp_path, monkeypatch):
    """PEP 503 canonical hash should be the same regardless of casing."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(
        """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"

[dev-packages]
pytest = "*"
"""
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIPENV_PIPFILE", raising=False)
    project = Project(chdir=False)
    h1 = project.pipfile.calculate_hash()

    pipfile.write_text(
        """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
Requests = "*"

[dev-packages]
PyTest = "*"
"""
    )
    # Invalidate cache.
    project.pipfile._parsed_cache = None
    project.pipfile._parsed_mtime_ns = None
    h2 = project.pipfile.calculate_hash()
    assert h1 == h2


# ---- proper-names DB -----------------------------------------------------


@pytest.mark.utils
def test_register_proper_name_appends_to_db(project_bare):
    project_bare.pipfile.register_proper_name("Sphinx")
    names = project_bare.pipfile.proper_names
    assert "Sphinx" in names


# ---- ensure_proper_casing / proper_case_section -------------------------


@pytest.mark.utils
def test_ensure_proper_casing_returns_false_when_no_change_needed(
    project_with_packages,
):
    # Even if proper_case lookup fails (no network), it should not crash.
    # Run with a stub to keep the test offline.
    with mock.patch(
        "pipenv.utils.pipfile.proper_case", side_effect=OSError
    ):
        # Should run without raising and return False (no changes possible
        # when proper_case can't resolve a name).
        changed = project_with_packages.pipfile.ensure_proper_casing()
        assert changed is False


@pytest.mark.utils
def test_recase_is_noop_by_default(project_with_packages):
    # Default mode (``[pipenv] package_name_case`` unset) must not touch
    # the network — protects ``pipenv install -r`` from per-package PyPI
    # HTTP probes.
    with mock.patch("pipenv.utils.pipfile.proper_case") as probe:
        project_with_packages.pipfile.recase()
        probe.assert_not_called()


def _override_settings(project, mapping: dict) -> None:
    """Replace the cached ``project.settings`` mapping for one test.

    ``Project.settings`` is a ``@cached_property``; assigning the same
    name on the instance ``__dict__`` shadows the descriptor for the
    rest of the project's lifetime, which is exactly the scope we want
    for a single fixture-bound test.
    """
    project.__dict__["settings"] = mapping


@pytest.mark.utils
def test_recase_canonical_mode_lowercases_offline(project_with_packages):
    pf = project_with_packages.pipfile
    pf.parsed.setdefault("packages", {})["Pillow"] = "*"
    _override_settings(
        project_with_packages, {"package_name_case": "canonical"}
    )
    with mock.patch("pipenv.utils.pipfile.proper_case") as probe:
        pf.recase()
        probe.assert_not_called()
    assert "Pillow" not in pf.parsed["packages"]
    assert "pillow" in pf.parsed["packages"]


@pytest.mark.utils
def test_recase_pypi_mode_invokes_probe(project_with_packages):
    pf = project_with_packages.pipfile
    _override_settings(
        project_with_packages, {"package_name_case": "pypi"}
    )
    with mock.patch(
        "pipenv.utils.pipfile.proper_case", side_effect=OSError
    ) as probe:
        pf.recase()
        assert probe.called


@pytest.mark.utils
@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "off"),
        ("", "off"),
        ("off", "off"),
        ("OFF", "off"),
        ("none", "off"),
        ("no", "off"),
        ("false", "off"),
        ("0", "off"),
        ("canonical", "canonical"),
        ("CANONICAL", "canonical"),
        ("pypi", "pypi"),
        ("PyPI", "pypi"),
        ("garbage", "off"),
        (False, "off"),
        (True, "canonical"),
    ],
)
def test_normalize_package_name_case(raw, expected):
    from pipenv.utils.pipfile import _normalize_package_name_case

    assert _normalize_package_name_case(raw) == expected
