from unittest.mock import MagicMock

from pipenv.patched.pip._internal.index.package_finder import CandidateEvaluator
from pipenv.patched.pip._internal.models.candidate import InstallationCandidate
from pipenv.patched.pip._internal.models.release_control import ReleaseControl
from pipenv.patched.pip._vendor.packaging.specifiers import (
    SpecifierSet as PipSpecifierSet,
)
from pipenv.resolver import Entry
from pipenv.utils.dependencies import _file_url_to_relative_path, clean_resolved_dep
from pipenv.vendor.packaging.specifiers import SpecifierSet


def _make_entry(entry_dict, category="packages"):
    """Helper to create an Entry with mocked project/resolver dependencies."""
    project = MagicMock()
    project.parsed_pipfile = {category: {}}
    resolver = MagicMock()
    resolver.index_lookup = {}
    return Entry(
        name=entry_dict["name"],
        entry_dict=entry_dict,
        project=project,
        resolver=resolver,
        category=category,
    )


def test_entry_get_cleaned_dict_preserves_file_url():
    """Test that file:// URLs are preserved in get_cleaned_dict.

    Regression test for https://github.com/pypa/pipenv/issues/6521.
    When a transitive dependency uses a PEP 508 file:// URL,
    the file key must be preserved in the lockfile entry.
    """
    entry = _make_entry({
        "name": "local-child-pkg",
        "file": "file:///home/user/project/vendor/local-child-pkg",
    })
    cleaned = entry.get_cleaned_dict
    assert "file" in cleaned
    assert cleaned["file"] == "file:///home/user/project/vendor/local-child-pkg"
    assert "version" not in cleaned  # file deps shouldn't have a version


def test_entry_get_cleaned_dict_preserves_path():
    """Test that path entries are preserved in get_cleaned_dict."""
    entry = _make_entry({
        "name": "my-local-pkg",
        "path": "vendor/my-local-pkg",
    })
    cleaned = entry.get_cleaned_dict
    assert "path" in cleaned
    assert cleaned["path"] == "vendor/my-local-pkg"


def test_entry_get_cleaned_dict_no_file_or_path():
    """Test that regular PyPI packages don't get spurious file/path keys."""
    entry = _make_entry({
        "name": "requests",
        "version": "==2.28.1",
        "hashes": ["sha256:abc123"],
    })
    cleaned = entry.get_cleaned_dict
    assert "file" not in cleaned
    assert "path" not in cleaned
    assert cleaned["version"] == "==2.28.1"


def test_clean_resolved_dep_with_vcs_url():
    project = {}  # Mock project object, adjust as needed
    dep = {
        "name": "example-package",
        "git": "git+https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/username/repo.git",
        "ref": "main"
    }

    result = clean_resolved_dep(project, dep)

    assert "example-package" in result
    assert result["example-package"]["git"] == "git+https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/username/repo.git"
    assert result["example-package"]["ref"] == "main"

def test_clean_resolved_dep_with_vcs_url_and_extras():
    project = {}  # Mock project object, adjust as needed
    dep = {
        "name": "example-package",
        "git": "git+https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/username/repo.git[extra1,extra2]",
        "ref": "main"
    }

    result = clean_resolved_dep(project, dep)

    assert "example-package" in result
    assert result["example-package"]["git"] == "git+https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/username/repo.git[extra1,extra2]"
    assert result["example-package"]["ref"] == "main"
    assert result["example-package"]["extras"] == ["extra1", "extra2"]


# ---------------------------------------------------------------------------
# Tests for GH-6119: transitive local-file sub-dependency path normalisation
# ---------------------------------------------------------------------------

class TestFileUrlToRelativePath:
    """Unit tests for the _file_url_to_relative_path helper."""

    def test_posix_file_url_becomes_relative(self):
        base = "/home/user/my-project"
        url = "file:///home/user/namespace-utils"
        result = _file_url_to_relative_path(url, base)
        assert result == "../namespace-utils"

    def test_already_relative_path_unchanged(self):
        base = "/home/user/my-project"
        result = _file_url_to_relative_path("../some-lib", base)
        assert result == "../some-lib"

    def test_http_url_unchanged(self):
        url = "https://example.com/packages/pkg-1.0.tar.gz"
        result = _file_url_to_relative_path(url, "/some/dir")
        assert result == url

    def test_non_string_input_unchanged(self):
        assert _file_url_to_relative_path(None, "/base") is None
        assert _file_url_to_relative_path(42, "/base") == 42

    def test_nested_subdirectory(self):
        base = "/home/user/my-project"
        url = "file:///home/user/my-project/vendor/local-pkg"
        result = _file_url_to_relative_path(url, base)
        assert result == "vendor/local-pkg"


def test_clean_resolved_dep_converts_file_url_subdep():
    """Transitive local deps whose file:// URL is resolved by pip are
    converted to a project-relative path in the lockfile.

    Regression test for https://github.com/pypa/pipenv/issues/6119.
    """
    project = MagicMock()
    project.project_directory = "/home/user/my-project"

    dep = {
        "name": "namespace-utils",
        "file": "file:///home/user/namespace-utils",
    }
    result = clean_resolved_dep(project, dep)

    assert "namespace-utils" in result
    entry = result["namespace-utils"]
    assert "file" in entry
    # Must be a relative path, not an absolute file:// URL
    assert not entry["file"].startswith("file://"), (
        f"Expected a relative path but got: {entry['file']!r}"
    )
    assert entry["file"] == "../namespace-utils"


def test_clean_resolved_dep_preserves_relative_file_toplevel():
    """Already-relative file paths are not modified by the normalisation logic.

    The normalisation only applies to absolute ``file://`` URLs; plain relative
    paths (as stored by top-level Pipfile entries after get_locked_dep merges
    the Pipfile data) must pass through unchanged.
    """
    project = MagicMock()
    project.project_directory = "/home/user/my-project"

    # Use is_top_level=False to avoid the unearth_hashes_for_dep code path
    # that requires an actual filesystem path.  The normalisation logic under
    # test runs before is_top_level is considered.
    dep = {
        "name": "namespace-library",
        "file": "../namespace-library-file",
        "editable": True,
    }
    result = clean_resolved_dep(project, dep, is_top_level=False)

    assert "namespace-library" in result
    entry = result["namespace-library"]
    assert entry["file"] == "../namespace-library-file"
    assert entry["editable"] is True


def test_clean_resolved_dep_file_url_no_project():
    """When project has no project_directory attribute the file:// URL is
    stored as-is (graceful degradation, no crash).
    """
    dep = {
        "name": "namespace-utils",
        "file": "file:///home/user/namespace-utils",
    }
    # Use a plain dict as the project mock (no project_directory attribute)
    result = clean_resolved_dep({}, dep)

    assert "namespace-utils" in result
    # URL is unchanged when we cannot compute a relative path
    assert result["namespace-utils"]["file"] == "file:///home/user/namespace-utils"


class TestPrereleaseFiltering:
    """Tests for prerelease version filtering behavior.

    These tests verify the fix for https://github.com/pypa/pipenv/issues/6395
    where transitive dependencies with prerelease specifiers (e.g., ">=4.2.0rc1")
    would cause prereleases to be selected even when the user didn't request them.
    """

    def test_specifier_with_prerelease_version_enables_prereleases(self):
        """Verify that a specifier containing a prerelease version has prereleases=True.

        This is the root cause of issue #6395 - when a transitive dependency
        specifies a prerelease version (e.g., ">=4.2.0rc1"), the SpecifierSet's
        prereleases property returns True.
        """
        # A specifier with a prerelease version has prereleases=True
        spec_with_prerelease = SpecifierSet(">=4.2.0rc1")
        assert spec_with_prerelease.prereleases is True

        # A specifier without a prerelease version has prereleases that is falsy
        # (None or False depending on the packaging version)
        spec_without_prerelease = SpecifierSet(">=4.2.0")
        assert not spec_without_prerelease.prereleases

    def test_filter_with_explicit_false_excludes_prereleases(self):
        """Verify that filter(prereleases=False) excludes prereleases when stable versions exist."""
        spec = SpecifierSet(">=4.2.0rc1")
        versions = ["4.2.0rc1", "4.2.0", "4.3.0", "5.0.0b1", "5.0.0"]

        # With prereleases=False, only stable versions should be returned
        filtered = list(spec.filter(versions, prereleases=False))
        assert "4.2.0rc1" not in filtered
        assert "5.0.0b1" not in filtered
        assert "4.2.0" in filtered
        assert "4.3.0" in filtered
        assert "5.0.0" in filtered

    def test_filter_with_explicit_false_no_fallback(self):
        """Verify that filter(prereleases=False) does NOT fall back to prereleases.

        When prereleases=False is explicitly passed, prereleases are excluded
        even if no stable versions match. This is the expected behavior for
        pipenv when --pre is not specified - if no stable versions satisfy
        the constraints, the resolver should fail rather than silently
        selecting a prerelease.
        """
        spec = SpecifierSet(">=6.0.0")
        versions = ["4.2.0", "5.0.0", "6.0.0b1", "6.0.0rc1"]

        # With prereleases=False, no versions should be returned (no stable versions match)
        filtered = list(spec.filter(versions, prereleases=False))
        assert filtered == []

    def test_filter_with_none_uses_specifier_prereleases(self):
        """Verify that filter(prereleases=None) defers to the specifier's prereleases property.

        This is the problematic behavior that issue #6395 addresses - when
        prereleases=None is passed, the specifier's own prereleases property
        is used, which returns True if the specifier contains a prerelease version.
        """
        spec = SpecifierSet(">=4.2.0rc1")
        versions = ["4.2.0rc1", "4.2.0", "4.3.0", "5.0.0b1", "5.0.0"]

        # With prereleases=None, the specifier's prereleases property is used
        # Since spec.prereleases is True (due to "rc1" in the specifier),
        # prereleases will be included
        filtered = list(spec.filter(versions, prereleases=None))
        assert "4.2.0rc1" in filtered
        assert "5.0.0b1" in filtered

    def test_issue_6395_transitive_prerelease_specifier(self):
        """Test the exact scenario from issue #6395.

        When a transitive dependency specifies a prerelease version (e.g., pottery
        requires redis>=4.2.0rc1), the combined specifier's prereleases property
        returns True. If we pass prereleases=None to filter(), prereleases will
        be included. But if we pass prereleases=False, they will be excluded.
        """
        # Simulate the combined specifier from issue #6395:
        # User wants redis>=4.5.0, transitive dep wants redis>=4.2.0rc1
        user_spec = SpecifierSet(">=4.5.0")
        transitive_spec = SpecifierSet(">=4.2.0rc1")
        combined = user_spec & transitive_spec

        # The combined specifier has prereleases=True due to the transitive dep
        assert combined.prereleases is True

        versions = ["4.5.0", "5.0.0", "5.3.0b5", "5.2.0"]

        # With prereleases=None (the old behavior), prereleases are included
        filtered_none = list(combined.filter(versions, prereleases=None))
        assert "5.3.0b5" in filtered_none

        # With prereleases=False (the fix), prereleases are excluded
        filtered_false = list(combined.filter(versions, prereleases=False))
        assert "5.3.0b5" not in filtered_false
        assert "4.5.0" in filtered_false
        assert "5.0.0" in filtered_false
        assert "5.2.0" in filtered_false

    def test_prerelease_only_package_with_none_fallback(self):
        """Verify that prereleases=None allows prereleases when no stable versions exist.

        This is the PEP 440 behavior that we need to preserve for packages like
        opentelemetry-semantic-conventions that only have prerelease versions.
        See: https://github.com/pypa/pipenv/issues/6485
        """
        spec = SpecifierSet("")
        prerelease_only_versions = ["0.20b0", "0.21b0", "0.60b0"]

        # With prereleases=False, no versions should be returned
        filtered_false = list(spec.filter(prerelease_only_versions, prereleases=False))
        assert filtered_false == []

        # With prereleases=None, the PEP 440 fallback kicks in and returns prereleases
        filtered_none = list(spec.filter(prerelease_only_versions, prereleases=None))
        assert "0.20b0" in filtered_none
        assert "0.21b0" in filtered_none
        assert "0.60b0" in filtered_none

    def test_issue_6485_prerelease_only_package(self):
        """Test the exact scenario from issue #6485.

        The package opentelemetry-semantic-conventions only has prerelease versions
        (all versions are beta like 0.60b0). When prereleases=False is used, the
        package cannot be resolved. The fix is to fall back to prereleases=None
        when no stable versions match, which allows PEP 440's fallback behavior
        to accept prereleases when they are the only versions available.
        """
        spec = SpecifierSet("")
        versions = ["0.20b0", "0.21b0", "0.60b0"]

        # This simulates what get_applicable_candidates should do:
        # 1. First try with prereleases=False
        filtered_strict = list(spec.filter(versions, prereleases=False))
        assert filtered_strict == []  # No stable versions

        # 2. If no matches and candidates exist, try with prereleases=None
        if not filtered_strict and versions:
            filtered_fallback = list(spec.filter(versions, prereleases=None))
            assert len(filtered_fallback) == 3  # All prereleases are returned
            assert "0.60b0" in filtered_fallback

    def test_mixed_versions_no_fallback_to_prereleases(self):
        """Verify that when stable versions exist, prereleases are not selected.

        This ensures the fix for #6485 doesn't regress #6395 behavior.
        """
        spec = SpecifierSet(">=1.0.0")
        mixed_versions = ["1.0.0", "1.1.0", "2.0.0b1", "2.0.0"]

        # With prereleases=False, only stable versions should be returned
        filtered = list(spec.filter(mixed_versions, prereleases=False))
        assert "2.0.0b1" not in filtered
        assert "1.0.0" in filtered
        assert "1.1.0" in filtered
        assert "2.0.0" in filtered


class TestCandidateEvaluatorPrereleases:
    """Tests for CandidateEvaluator.get_applicable_candidates prerelease handling.

    These tests verify the fix for https://github.com/pypa/pipenv/issues/6485
    where packages with only prerelease versions could not be installed.
    """

    def _make_candidate(self, name, version):
        """Create a mock InstallationCandidate."""
        from pipenv.patched.pip._internal.models.link import Link
        link = Link(f"https://example.com/{name}-{version}.tar.gz")
        # InstallationCandidate expects a string version, not a parsed version
        return InstallationCandidate(name, version, link)

    def _make_evaluator(self, specifier="", allow_prereleases=False):
        """Create a CandidateEvaluator for testing."""
        # Use ReleaseControl to manage prerelease handling
        release_control = None
        if allow_prereleases:
            release_control = ReleaseControl(all_releases={":all:"})
        return CandidateEvaluator.create(
            project_name="test-package",
            target_python=None,
            release_control=release_control,
            specifier=PipSpecifierSet(specifier),
        )

    def test_prerelease_only_package_allowed(self):
        """Test that packages with only prereleases are allowed.

        This is the fix for issue #6485 - opentelemetry-semantic-conventions
        only has prerelease versions, so they should be allowed.
        """
        candidates = [
            self._make_candidate("test-package", "0.20b0"),
            self._make_candidate("test-package", "0.21b0"),
            self._make_candidate("test-package", "0.60b0"),
        ]
        evaluator = self._make_evaluator(allow_prereleases=False)

        applicable = evaluator.get_applicable_candidates(candidates)

        # All prereleases should be returned since there are no stable versions
        assert len(applicable) == 3
        versions = [str(c.version) for c in applicable]
        assert "0.60b0" in versions

    def test_mixed_versions_excludes_prereleases(self):
        """Test that prereleases are excluded when stable versions exist.

        This ensures the fix for #6485 doesn't regress #6395.
        """
        candidates = [
            self._make_candidate("test-package", "1.0.0"),
            self._make_candidate("test-package", "1.1.0"),
            self._make_candidate("test-package", "2.0.0b1"),
            self._make_candidate("test-package", "2.0.0"),
        ]
        evaluator = self._make_evaluator(allow_prereleases=False)

        applicable = evaluator.get_applicable_candidates(candidates)

        # Only stable versions should be returned
        versions = [str(c.version) for c in applicable]
        assert "2.0.0b1" not in versions
        assert "1.0.0" in versions
        assert "1.1.0" in versions
        assert "2.0.0" in versions

    def test_allow_prereleases_flag_includes_all(self):
        """Test that allow_prereleases=True includes all versions."""
        candidates = [
            self._make_candidate("test-package", "1.0.0"),
            self._make_candidate("test-package", "2.0.0b1"),
        ]
        evaluator = self._make_evaluator(allow_prereleases=True)

        applicable = evaluator.get_applicable_candidates(candidates)

        versions = [str(c.version) for c in applicable]
        assert "1.0.0" in versions
        assert "2.0.0b1" in versions

    def test_specifier_constraint_with_prerelease_only(self):
        """Test that specifier constraints work with prerelease-only packages."""
        candidates = [
            self._make_candidate("test-package", "0.20b0"),
            self._make_candidate("test-package", "0.50b0"),
            self._make_candidate("test-package", "0.60b0"),
        ]
        evaluator = self._make_evaluator(specifier=">=0.50b0", allow_prereleases=False)

        applicable = evaluator.get_applicable_candidates(candidates)

        # Only prereleases matching the constraint should be returned
        versions = [str(c.version) for c in applicable]
        assert "0.20b0" not in versions
        assert "0.50b0" in versions
        assert "0.60b0" in versions
