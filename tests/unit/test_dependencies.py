import pytest

from pipenv.utils.dependencies import clean_resolved_dep
from pipenv.vendor.packaging.specifiers import SpecifierSet


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

        # A specifier without a prerelease version has prereleases=False
        # (not None, because SpecifierSet.prereleases returns any(s.prereleases for s in self._specs))
        spec_without_prerelease = SpecifierSet(">=4.2.0")
        assert spec_without_prerelease.prereleases is False

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
