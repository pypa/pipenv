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



# ---------------------------------------------------------------------------
# Tests for no_binary handling (GitHub issue #5362)
# ---------------------------------------------------------------------------

class TestNoBinaryCleanResolvedDep:
    """Ensure clean_resolved_dep preserves the no_binary flag."""

    def test_no_binary_true_is_preserved(self):
        """no_binary = True must survive clean_resolved_dep so the lockfile
        records it and batch_install can re-apply --no-binary."""
        project = MagicMock()
        project.project_directory = None

        dep = {
            "name": "cartopy",
            "version": "==0.21.0",
            "no_binary": True,
        }
        result = clean_resolved_dep(project, dep)

        assert "cartopy" in result
        assert result["cartopy"].get("no_binary") is True

    def test_no_binary_false_is_not_written(self):
        """When no_binary is falsy it should not appear in the lockfile entry."""
        project = MagicMock()
        project.project_directory = None

        dep = {
            "name": "requests",
            "version": "==2.28.0",
            "no_binary": False,
        }
        result = clean_resolved_dep(project, dep)

        assert "no_binary" not in result.get("requests", {})

    def test_no_binary_absent_is_not_written(self):
        """When no_binary is absent it should not appear in the lockfile entry."""
        project = MagicMock()
        project.project_directory = None

        dep = {
            "name": "requests",
            "version": "==2.28.0",
        }
        result = clean_resolved_dep(project, dep)

        assert "no_binary" not in result.get("requests", {})


class TestShouldUseNoBinary:
    """Tests for the _should_use_no_binary helper in routines/install.py."""

    def _call(self, pkg_name, extra_pip_args=None, env=None):
        import os
        from unittest.mock import patch

        from pipenv.routines.install import _should_use_no_binary

        env = env or {}
        with patch.dict(os.environ, env, clear=False):
            return _should_use_no_binary(pkg_name, extra_pip_args)

    def test_extra_pip_args_space_separated(self):
        assert self._call("cartopy", ["--no-binary", "cartopy"]) is True

    def test_extra_pip_args_equals_form(self):
        assert self._call("cartopy", ["--no-binary=cartopy"]) is True

    def test_extra_pip_args_all(self):
        assert self._call("cartopy", ["--no-binary", ":all:"]) is True

    def test_extra_pip_args_comma_list_matches(self):
        assert self._call("cartopy", ["--no-binary", "numpy,cartopy,scipy"]) is True

    def test_extra_pip_args_comma_list_no_match(self):
        assert self._call("cartopy", ["--no-binary", "numpy,scipy"]) is False

    def test_extra_pip_args_different_package(self):
        assert self._call("cartopy", ["--no-binary", "numpy"]) is False

    def test_pip_no_binary_env_var_matches(self):
        assert self._call("cartopy", env={"PIP_NO_BINARY": "cartopy"}) is True

    def test_pip_no_binary_env_var_all(self):
        assert self._call("cartopy", env={"PIP_NO_BINARY": ":all:"}) is True

    def test_pip_no_binary_env_var_no_match(self):
        assert self._call("cartopy", env={"PIP_NO_BINARY": "numpy"}) is False

    def test_case_insensitive_match(self):
        assert self._call("Cartopy", ["--no-binary", "cartopy"]) is True

    def test_normalised_name_match(self):
        # pip normalises dashes/underscores, ensure we do too
        assert self._call("some-package", ["--no-binary", "some_package"]) is True

    def test_empty_extra_pip_args(self):
        assert self._call("cartopy", []) is False

    def test_none_pkg_name(self):
        assert self._call(None, ["--no-binary", "cartopy"]) is False


# ---------------------------------------------------------------------------
# Tests for ensure_path_is_relative (issue #5925)
# ---------------------------------------------------------------------------


class TestEnsurePathIsRelative:
    """Unit tests for ensure_path_is_relative.

    The function must:
    * Return a ``./``-prefixed POSIX path for same-directory or subdirectory
      paths (so pip treats the string as a local path, not a bare package name).
    * Leave ``"."`` unchanged (it already means "current directory").
    * Leave paths that start with ``..`` unchanged.
    * Return the absolute path when the target is on a different drive (Windows).
    """

    def _call(self, file_path, cwd=None):
        from pathlib import Path
        from unittest.mock import patch

        from pipenv.utils.dependencies import ensure_path_is_relative

        if cwd is None:
            return ensure_path_is_relative(file_path)
        with patch("pipenv.utils.dependencies.Path.cwd", return_value=Path(cwd)):
            return ensure_path_is_relative(file_path)

    def test_subdirectory_gets_dotslash_prefix(self, tmp_path):
        """A subdirectory relative to cwd should be returned as './subdir'."""
        pkg_dir = tmp_path / "mypackage"
        pkg_dir.mkdir()
        result = self._call(str(pkg_dir), cwd=str(tmp_path))
        assert result == "./mypackage"

    def test_nested_subdirectory_gets_dotslash_prefix(self, tmp_path):
        """A nested subdirectory should be returned as './a/b'."""
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        result = self._call(str(nested), cwd=str(tmp_path))
        assert result == "./a/b"

    def test_current_dir_dot_unchanged(self, tmp_path):
        """When the path resolves to cwd itself, '.' is returned unchanged."""
        result = self._call(str(tmp_path), cwd=str(tmp_path))
        assert result == "."

    def test_parent_dir_traversal_unchanged(self, tmp_path):
        """Paths above cwd (e.g. '../sibling') must not gain a './' prefix."""
        sibling = tmp_path.parent / "sibling"
        sibling.mkdir(exist_ok=True)
        result = self._call(str(sibling), cwd=str(tmp_path))
        # Must start with '..' — the './' prefix must NOT be added.
        assert result.startswith(".."), f"Expected '../...' but got: {result!r}"
        assert not result.startswith("./")

    def test_already_dotslash_path_normalised(self, tmp_path):
        """An input that already has './' is resolved and re-emitted as './'."""
        pkg_dir = tmp_path / "mypkg"
        pkg_dir.mkdir()
        # Pass the path with an explicit './' prefix; the function should
        # resolve it and still return './mypkg'.
        result = self._call(str(tmp_path / "." / "mypkg"), cwd=str(tmp_path))
        assert result == "./mypkg"

    def test_uses_forward_slashes(self, tmp_path):
        """Result always uses forward slashes regardless of OS separator."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        result = self._call(str(deep), cwd=str(tmp_path))
        assert "\\" not in result
        assert result == "./a/b/c"


# ---------------------------------------------------------------------------
# Tests for dependency_as_pip_install_line – editable local-path handling
# (issue #5925)
# ---------------------------------------------------------------------------


class TestDependencyAsPipInstallLineEditable:
    """Regression tests for the editable flag handling in
    dependency_as_pip_install_line.

    The function must prepend ``-e`` when ``editable=True`` regardless of
    whether the directory actually exists on the current filesystem.  This is
    important for CI environments and cross-machine lock file consumption.
    """

    def _call(self, dep_name, dep):
        from pipenv.utils.dependencies import dependency_as_pip_install_line

        return dependency_as_pip_install_line(
            dep_name,
            dep,
            include_hashes=False,
            include_markers=True,
            include_index=False,
            indexes=[],
        )

    def test_editable_path_dep_gets_dash_e(self):
        """Editable local-path dep produces '-e <path>' even when dir absent."""
        dep = {"path": "./mypackage", "editable": True}
        result = self._call("mypackage", dep)
        assert result == "-e ./mypackage"

    def test_non_editable_path_dep_no_dash_e(self):
        """Non-editable local-path dep must NOT get '-e'."""
        dep = {"path": "./mypackage"}
        result = self._call("mypackage", dep)
        assert result == "./mypackage"
        assert not result.startswith("-e")

    def test_editable_http_url_dep_no_dash_e(self):
        """Remote HTTP URL deps must never get '-e' even if editable=True."""
        dep = {
            "file": "https://example.com/mypackage-1.0.tar.gz",
            "editable": True,
        }
        result = self._call("mypackage", dep)
        assert "-e" not in result
        assert "mypackage @ https://example.com/mypackage-1.0.tar.gz" in result

    def test_editable_path_dep_without_dotslash(self):
        """Bare path without './' prefix is still treated as editable."""
        dep = {"path": "mypackage", "editable": True}
        result = self._call("mypackage", dep)
        assert result.startswith("-e ")
        assert "mypackage" in result

    def test_editable_path_dep_with_parent_traversal(self):
        """'../sibling' editable paths get '-e ../sibling'."""
        dep = {"path": "../sibling-lib", "editable": True}
        result = self._call("sibling-lib", dep)
        assert result == "-e ../sibling-lib"

    def test_non_editable_file_url_produces_pep508_line(self):
        """Non-editable remote-file dep produces a PEP 508 '@' line."""
        dep = {"file": "https://example.com/pkg-1.0-py3-none-any.whl"}
        result = self._call("pkg", dep)
        assert result == "pkg @ https://example.com/pkg-1.0-py3-none-any.whl"
