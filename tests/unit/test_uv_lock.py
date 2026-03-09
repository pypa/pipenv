"""Unit tests for pipenv.uv_lock module."""

from __future__ import annotations

import json
import os
import textwrap
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# _url_matches
# ---------------------------------------------------------------------------


class TestUrlMatches:
    """Tests for pipenv.uv_lock._url_matches."""

    def test_identical_urls(self):
        from pipenv.uv_lock import _url_matches

        assert _url_matches("https://pypi.org/simple", "https://pypi.org/simple")

    def test_trailing_slash(self):
        from pipenv.uv_lock import _url_matches

        assert _url_matches("https://pypi.org/simple/", "https://pypi.org/simple")
        assert _url_matches("https://pypi.org/simple", "https://pypi.org/simple/")

    def test_case_insensitive(self):
        from pipenv.uv_lock import _url_matches

        assert _url_matches("https://PyPI.org/Simple", "https://pypi.org/simple")

    def test_scheme_difference(self):
        from pipenv.uv_lock import _url_matches

        assert _url_matches("http://pypi.org/simple", "https://pypi.org/simple")

    def test_different_urls(self):
        from pipenv.uv_lock import _url_matches

        assert not _url_matches("https://pypi.org/simple", "https://example.com/simple")

    def test_empty_url(self):
        from pipenv.uv_lock import _url_matches

        assert not _url_matches("", "https://pypi.org/simple")
        assert not _url_matches("https://pypi.org/simple", "")
        assert not _url_matches("", "")

    def test_different_paths(self):
        from pipenv.uv_lock import _url_matches

        assert not _url_matches("https://pypi.org/simple", "https://pypi.org/packages")

    def test_with_port(self):
        from pipenv.uv_lock import _url_matches

        assert _url_matches("http://localhost:8080/simple", "https://localhost:8080/simple")
        assert not _url_matches("http://localhost:8080/simple", "http://localhost:9090/simple")


# ---------------------------------------------------------------------------
# _normalize_marker
# ---------------------------------------------------------------------------


class TestNormalizeMarker:
    """Tests for pipenv.uv_lock._normalize_marker."""

    def test_simple_gte(self):
        from pipenv.uv_lock import _normalize_marker

        result = _normalize_marker("python_full_version >= '3.6'")
        assert result == "python_version >= '3.6'"

    def test_double_quotes(self):
        from pipenv.uv_lock import _normalize_marker

        result = _normalize_marker('python_full_version >= "3.6"')
        assert result == 'python_version >= "3.6"'

    def test_with_micro_version_no_change(self):
        """python_full_version with micro part should NOT be normalized."""
        from pipenv.uv_lock import _normalize_marker

        result = _normalize_marker("python_full_version >= '3.6.1'")
        assert result == "python_full_version >= '3.6.1'"

    def test_compound_markers(self):
        from pipenv.uv_lock import _normalize_marker

        result = _normalize_marker("python_full_version >= '3.6' and os_name == 'posix'")
        assert result == "python_version >= '3.6' and os_name == 'posix'"

    def test_no_python_full_version(self):
        from pipenv.uv_lock import _normalize_marker

        marker = "sys_platform == 'win32'"
        assert _normalize_marker(marker) == marker

    def test_different_operators(self):
        from pipenv.uv_lock import _normalize_marker

        for op in (">=", "<=", ">", "<", "!="):
            result = _normalize_marker(f"python_full_version {op} '3.8'")
            assert result == f"python_version {op} '3.8'"

    def test_eq_operator_no_change(self):
        """Exact == should not be normalized (regex doesn't match ==)."""
        from pipenv.uv_lock import _normalize_marker

        result = _normalize_marker("python_full_version == '3.8'")
        # == has two = chars, our regex matches single-char operators only preceded by nothing
        # Actually, == is not in the regex group (>=|<=|>|<|!=), so no change
        assert result == "python_full_version == '3.8'"


# ---------------------------------------------------------------------------
# _source_url_to_index_name
# ---------------------------------------------------------------------------


class TestSourceUrlToIndexName:
    """Tests for pipenv.uv_lock._source_url_to_index_name."""

    def test_matching_source(self):
        from pipenv.uv_lock import _source_url_to_index_name

        sources = [
            {"name": "pypi", "url": "https://pypi.org/simple"},
            {"name": "local", "url": "http://localhost:8080/simple"},
        ]
        assert _source_url_to_index_name("https://pypi.org/simple", sources) == "pypi"
        assert _source_url_to_index_name("http://localhost:8080/simple/", sources) == "local"

    def test_no_match(self):
        from pipenv.uv_lock import _source_url_to_index_name

        sources = [{"name": "pypi", "url": "https://pypi.org/simple"}]
        assert _source_url_to_index_name("https://example.com/simple", sources) is None


# ---------------------------------------------------------------------------
# _pipfile_entry_to_pep508
# ---------------------------------------------------------------------------


class TestPipfileEntryToPep508:
    """Tests for pipenv.uv_lock._pipfile_entry_to_pep508."""

    def test_star_version(self):
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        assert _pipfile_entry_to_pep508("requests", "*") == "requests"

    def test_string_version(self):
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        assert _pipfile_entry_to_pep508("requests", ">=2.0") == "requests>=2.0"

    def test_dict_star_version(self):
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        assert _pipfile_entry_to_pep508("requests", {"version": "*"}) == "requests"

    def test_dict_with_version(self):
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        result = _pipfile_entry_to_pep508("requests", {"version": ">=1.0"})
        assert result == "requests>=1.0"

    def test_dict_with_extras(self):
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        result = _pipfile_entry_to_pep508("requests", {"version": ">=1.0", "extras": ["socks"]})
        assert result == "requests[socks]>=1.0"

    def test_dict_with_multiple_extras(self):
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        result = _pipfile_entry_to_pep508("requests", {"version": "*", "extras": ["socks", "security"]})
        # packaging.Requirement alphabetizes extras
        assert result == "requests[security,socks]"

    def test_dict_with_markers(self):
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        result = _pipfile_entry_to_pep508("pywin32", {"version": "*", "markers": "sys_platform == 'win32'"})
        # packaging.Requirement normalizes to double quotes
        assert result == 'pywin32; sys_platform == "win32"'

    def test_dict_with_version_and_markers(self):
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        result = _pipfile_entry_to_pep508(
            "pywin32",
            {"version": ">=300", "markers": "sys_platform == 'win32'"},
        )
        # packaging.Requirement normalizes to double quotes
        assert result == 'pywin32>=300; sys_platform == "win32"'

    def test_dict_with_marker_keys(self):
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        result = _pipfile_entry_to_pep508(
            "pkg",
            {"version": "*", "os_name": "== 'posix'", "sys_platform": "== 'linux'"},
        )
        # packaging.Requirement normalizes to double quotes and alphabetizes
        assert 'os_name == "posix"' in result
        assert 'sys_platform == "linux"' in result

    def test_dict_git_no_version(self):
        """Git entries typically have no version; PEP 508 should just be the name."""
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        result = _pipfile_entry_to_pep508("mylib", {"git": "https://github.com/user/mylib.git", "ref": "main"})
        assert result == "mylib"

    def test_dict_index_no_version(self):
        """Index-restricted entry with star version."""
        from pipenv.uv_lock import _pipfile_entry_to_pep508

        result = _pipfile_entry_to_pep508("private-pkg", {"version": "*", "index": "private"})
        assert result == "private-pkg"


# ---------------------------------------------------------------------------
# _pipfile_entry_to_uv_source
# ---------------------------------------------------------------------------


class TestPipfileEntryToUvSource:
    """Tests for pipenv.uv_lock._pipfile_entry_to_uv_source."""

    def test_string_returns_none(self):
        from pipenv.uv_lock import _pipfile_entry_to_uv_source

        assert _pipfile_entry_to_uv_source("pkg", "*") is None
        assert _pipfile_entry_to_uv_source("pkg", ">=1.0") is None

    def test_index_restricted(self):
        from pipenv.uv_lock import _pipfile_entry_to_uv_source

        result = _pipfile_entry_to_uv_source("pkg", {"version": "*", "index": "private"})
        assert result == {"index": "private"}

    def test_git_dependency(self):
        from pipenv.uv_lock import _pipfile_entry_to_uv_source

        result = _pipfile_entry_to_uv_source(
            "mylib",
            {"git": "https://github.com/user/mylib.git", "ref": "main"},
        )
        assert result == {"git": "https://github.com/user/mylib.git", "rev": "main"}

    def test_git_with_subdirectory(self):
        from pipenv.uv_lock import _pipfile_entry_to_uv_source

        result = _pipfile_entry_to_uv_source(
            "mylib",
            {
                "git": "https://github.com/user/mono.git",
                "ref": "v1",
                "subdirectory": "libs/mylib",
            },
        )
        assert result == {
            "git": "https://github.com/user/mono.git",
            "rev": "v1",
            "subdirectory": "libs/mylib",
        }

    def test_path_dependency(self):
        from pipenv.uv_lock import _pipfile_entry_to_uv_source

        result = _pipfile_entry_to_uv_source("mylib", {"path": "./libs/mylib"})
        assert result == {"path": "./libs/mylib"}

    def test_editable_path(self):
        from pipenv.uv_lock import _pipfile_entry_to_uv_source

        result = _pipfile_entry_to_uv_source("mylib", {"path": ".", "editable": True})
        assert result == {"path": ".", "editable": True}

    def test_file_url(self):
        from pipenv.uv_lock import _pipfile_entry_to_uv_source

        result = _pipfile_entry_to_uv_source("mylib", {"file": "https://example.com/mylib-1.0.tar.gz"})
        assert result == {"url": "https://example.com/mylib-1.0.tar.gz"}

    def test_file_local_path(self):
        from pipenv.uv_lock import _pipfile_entry_to_uv_source

        result = _pipfile_entry_to_uv_source("mylib", {"file": "/path/to/mylib-1.0.tar.gz"})
        assert result == {"path": "/path/to/mylib-1.0.tar.gz"}

    def test_plain_dict_returns_none(self):
        from pipenv.uv_lock import _pipfile_entry_to_uv_source

        result = _pipfile_entry_to_uv_source("pkg", {"version": ">=1.0"})
        assert result is None


# ---------------------------------------------------------------------------
# _build_pyproject_toml
# ---------------------------------------------------------------------------


class TestBuildPyprojectToml:
    """Tests for pipenv.uv_lock._build_pyproject_toml."""

    def _make_project(
        self,
        packages=None,
        dev_packages=None,
        sources=None,
        required_python_version="3.10",
        parsed_pipfile=None,
        settings=None,
    ):
        """Create a mock Project object."""
        project = mock.MagicMock()
        project.packages = packages or {}
        project.dev_packages = dev_packages or {}
        project.pipfile_sources.return_value = sources or [{"name": "pypi", "url": "https://pypi.org/simple"}]
        project.required_python_version = required_python_version
        project.parsed_pipfile = parsed_pipfile or {}
        project.settings = settings or {}
        return project

    def test_basic_default_category(self):
        from pipenv.uv_lock import _build_pyproject_toml

        project = self._make_project(packages={"requests": "*", "flask": ">=2.0"})
        toml = _build_pyproject_toml(project, "default")
        assert 'name = "pipenv-resolver"' in toml
        assert 'requires-python = ">= 3.10"' in toml
        assert '"requests",' in toml
        assert '"flask>=2.0",' in toml
        assert "[[tool.uv.index]]" in toml
        assert 'name = "pypi"' in toml

    def test_dev_category_with_constraints(self):
        from pipenv.uv_lock import _build_pyproject_toml

        project = self._make_project(
            packages={"requests": ">=2.0"},
            dev_packages={"pytest": "*"},
            settings={"use_default_constraints": True},
        )
        toml = _build_pyproject_toml(project, "develop")
        assert '"pytest",' in toml
        assert "constraint-dependencies" in toml

    def test_index_restricted_source(self):
        from pipenv.uv_lock import _build_pyproject_toml

        project = self._make_project(
            packages={"private-pkg": {"version": "*", "index": "local"}},
            sources=[
                {"name": "pypi", "url": "https://pypi.org/simple"},
                {"name": "local", "url": "http://localhost:8080/simple"},
            ],
        )
        toml = _build_pyproject_toml(project, "default")
        assert "[tool.uv.sources]" in toml
        assert 'private-pkg = {index = "local"}' in toml

    def test_pre_release_flag(self):
        from pipenv.uv_lock import _build_pyproject_toml

        project = self._make_project(packages={"requests": "*"})
        toml = _build_pyproject_toml(project, "default", pre=True)
        assert 'prerelease = "allow"' in toml

    def test_bare_python_version_gets_prefix(self):
        from pipenv.uv_lock import _build_pyproject_toml

        project = self._make_project(required_python_version="3.10")
        toml = _build_pyproject_toml(project, "default")
        assert 'requires-python = ">= 3.10"' in toml

    def test_version_spec_python_version(self):
        from pipenv.uv_lock import _build_pyproject_toml

        project = self._make_project(required_python_version=">=3.8")
        toml = _build_pyproject_toml(project, "default")
        assert 'requires-python = ">=3.8"' in toml

    def test_no_python_version(self):
        from pipenv.uv_lock import _build_pyproject_toml

        project = self._make_project(required_python_version="")
        toml = _build_pyproject_toml(project, "default")
        assert "requires-python" not in toml

    def test_multiple_indexes(self):
        from pipenv.uv_lock import _build_pyproject_toml

        project = self._make_project(
            sources=[
                {"name": "pypi", "url": "https://pypi.org/simple"},
                {"name": "local", "url": "http://localhost:8080/simple"},
            ]
        )
        toml = _build_pyproject_toml(project, "default")
        assert toml.count("[[tool.uv.index]]") == 2
        assert "default = true" in toml

    def test_git_source(self):
        from pipenv.uv_lock import _build_pyproject_toml

        project = self._make_project(
            packages={
                "mylib": {
                    "git": "https://github.com/user/mylib.git",
                    "ref": "main",
                }
            }
        )
        toml = _build_pyproject_toml(project, "default")
        assert "[tool.uv.sources]" in toml
        assert 'git = "https://github.com/user/mylib.git"' in toml
        assert 'rev = "main"' in toml


# ---------------------------------------------------------------------------
# _collect_hashes
# ---------------------------------------------------------------------------


class TestCollectHashes:
    """Tests for pipenv.uv_lock._collect_hashes."""

    def test_empty_package(self):
        from pipenv.uv_lock import _collect_hashes

        assert _collect_hashes({"name": "pkg", "version": "1.0"}) == []

    def test_sdist_hash(self):
        from pipenv.uv_lock import _collect_hashes

        pkg = {
            "name": "pkg",
            "version": "1.0",
            "sdist": {"hash": "sha256:abc123"},
        }
        assert _collect_hashes(pkg) == ["sha256:abc123"]

    def test_wheel_hashes(self):
        from pipenv.uv_lock import _collect_hashes

        pkg = {
            "name": "pkg",
            "version": "1.0",
            "wheels": [
                {"hash": "sha256:wheel1"},
                {"hash": "sha256:wheel2"},
            ],
        }
        result = _collect_hashes(pkg)
        assert sorted(result) == ["sha256:wheel1", "sha256:wheel2"]

    def test_combined_deduplication(self):
        from pipenv.uv_lock import _collect_hashes

        pkg = {
            "name": "pkg",
            "version": "1.0",
            "sdist": {"hash": "sha256:abc"},
            "wheels": [
                {"hash": "sha256:abc"},  # duplicate
                {"hash": "sha256:def"},
            ],
        }
        result = _collect_hashes(pkg)
        assert sorted(result) == ["sha256:abc", "sha256:def"]

    def test_hashes_are_sorted(self):
        from pipenv.uv_lock import _collect_hashes

        pkg = {
            "name": "pkg",
            "version": "1.0",
            "wheels": [
                {"hash": "sha256:zzz"},
                {"hash": "sha256:aaa"},
                {"hash": "sha256:mmm"},
            ],
        }
        result = _collect_hashes(pkg)
        assert result == ["sha256:aaa", "sha256:mmm", "sha256:zzz"]


# ---------------------------------------------------------------------------
# _find_extras_deps
# ---------------------------------------------------------------------------


class TestFindExtrasDeps:
    """Tests for pipenv.uv_lock._find_extras_deps."""

    def test_empty_packages(self):
        from pipenv.uv_lock import _find_extras_deps

        assert _find_extras_deps([]) == {}

    def test_no_optional_deps(self):
        from pipenv.uv_lock import _find_extras_deps

        pkgs = [
            {"name": "requests", "version": "2.31.0", "dependencies": []},
        ]
        assert _find_extras_deps(pkgs) == {}

    def test_with_optional_deps(self):
        from pipenv.uv_lock import _find_extras_deps

        pkgs = [
            {
                "name": "requests",
                "version": "2.31.0",
                "optional-dependencies": {
                    "socks": [{"name": "PySocks"}],
                    "security": [{"name": "cryptography"}, {"name": "pyOpenSSL"}],
                },
            },
        ]
        result = _find_extras_deps(pkgs)
        assert "requests" in result
        assert result["requests"]["socks"] == ["pysocks"]
        assert sorted(result["requests"]["security"]) == ["cryptography", "pyopenssl"]


# ---------------------------------------------------------------------------
# _get_root_dep_markers
# ---------------------------------------------------------------------------


class TestGetRootDepMarkers:
    """Tests for pipenv.uv_lock._get_root_dep_markers."""

    def test_no_root(self):
        from pipenv.uv_lock import _get_root_dep_markers

        pkgs = [{"name": "requests", "version": "2.31.0", "source": {"registry": "https://pypi.org/simple"}}]
        assert _get_root_dep_markers(pkgs) == {}

    def test_root_with_markers(self):
        from pipenv.uv_lock import _get_root_dep_markers

        pkgs = [
            {
                "name": "pipenv-resolver",
                "version": "0.0.0",
                "source": {"virtual": "."},
                "dependencies": [
                    {"name": "requests"},
                    {"name": "colorama", "marker": "sys_platform == 'win32'"},
                ],
            },
        ]
        result = _get_root_dep_markers(pkgs)
        assert "colorama" in result
        assert result["colorama"] == "sys_platform == 'win32'"
        assert "requests" not in result


# ---------------------------------------------------------------------------
# _get_root_dep_extras
# ---------------------------------------------------------------------------


class TestGetRootDepExtras:
    """Tests for pipenv.uv_lock._get_root_dep_extras."""

    def test_no_root(self):
        from pipenv.uv_lock import _get_root_dep_extras

        pkgs = [{"name": "requests", "version": "2.31.0", "source": {"registry": "https://pypi.org/simple"}}]
        assert _get_root_dep_extras(pkgs) == {}

    def test_root_with_extras(self):
        from pipenv.uv_lock import _get_root_dep_extras

        pkgs = [
            {
                "name": "pipenv-resolver",
                "version": "0.0.0",
                "source": {"virtual": "."},
                "dependencies": [
                    {"name": "requests", "extra": ["socks"]},
                    {"name": "flask"},
                ],
            },
        ]
        result = _get_root_dep_extras(pkgs)
        assert "requests" in result
        assert result["requests"] == ["socks"]
        assert "flask" not in result


# ---------------------------------------------------------------------------
# _parse_uv_lock (integration-style unit test with mock project)
# ---------------------------------------------------------------------------


class TestParseUvLock:
    """Tests for pipenv.uv_lock._parse_uv_lock using synthetic uv.lock files."""

    def _write_lock(self, tmp_path, content: str) -> str:
        lock_file = tmp_path / "uv.lock"
        lock_file.write_text(textwrap.dedent(content))
        return str(lock_file)

    def _make_project(self, packages=None, dev_packages=None, sources=None):
        project = mock.MagicMock()
        project.packages = packages or {}
        project.dev_packages = dev_packages or {}
        project.pipfile_sources.return_value = sources or [{"name": "pypi", "url": "https://pypi.org/simple"}]
        project.parsed_pipfile = {}
        return project

    def test_basic_package(self, tmp_path):
        from pipenv.uv_lock import _parse_uv_lock

        lock_path = self._write_lock(
            tmp_path,
            """\
            version = 1
            requires-python = ">= 3.10"

            [[package]]
            name = "pipenv-resolver"
            version = "0.0.0"
            source = { virtual = "." }
            dependencies = [
                { name = "requests" },
            ]

            [[package]]
            name = "requests"
            version = "2.31.0"
            source = { registry = "https://pypi.org/simple" }
            sdist = { hash = "sha256:abc123" }
        """,
        )
        project = self._make_project(packages={"requests": "*"})
        result = _parse_uv_lock(lock_path, project, "default")

        assert len(result) == 1
        assert result[0]["name"] == "requests"
        assert result[0]["version"] == "==2.31.0"
        assert result[0]["hashes"] == ["sha256:abc123"]
        assert result[0]["index"] == "pypi"

    def test_skips_root_virtual(self, tmp_path):
        from pipenv.uv_lock import _parse_uv_lock

        lock_path = self._write_lock(
            tmp_path,
            """\
            version = 1
            requires-python = ">= 3.10"

            [[package]]
            name = "pipenv-resolver"
            version = "0.0.0"
            source = { virtual = "." }
            dependencies = [
                { name = "six" },
            ]

            [[package]]
            name = "six"
            version = "1.16.0"
            source = { registry = "https://pypi.org/simple" }
        """,
        )
        project = self._make_project(packages={"six": "*"})
        result = _parse_uv_lock(lock_path, project, "default")

        names = [r["name"] for r in result]
        assert "pipenv-resolver" not in names
        assert "six" in names

    def test_markers_from_root_dep(self, tmp_path):
        from pipenv.uv_lock import _parse_uv_lock

        lock_path = self._write_lock(
            tmp_path,
            """\
            version = 1
            requires-python = ">= 3.10"

            [[package]]
            name = "pipenv-resolver"
            version = "0.0.0"
            source = { virtual = "." }
            dependencies = [
                { name = "colorama", marker = "sys_platform == 'win32'" },
            ]

            [[package]]
            name = "colorama"
            version = "0.4.6"
            source = { registry = "https://pypi.org/simple" }
        """,
        )
        project = self._make_project(packages={"colorama": {"version": "*", "markers": "sys_platform == 'win32'"}})
        result = _parse_uv_lock(lock_path, project, "default")

        colorama = result[0]
        assert colorama["name"] == "colorama"
        assert colorama["markers"] == "sys_platform == 'win32'"

    def test_extras_from_root_dep(self, tmp_path):
        from pipenv.uv_lock import _parse_uv_lock

        lock_path = self._write_lock(
            tmp_path,
            """\
            version = 1
            requires-python = ">= 3.10"

            [[package]]
            name = "pipenv-resolver"
            version = "0.0.0"
            source = { virtual = "." }
            dependencies = [
                { name = "requests", extra = ["socks"] },
            ]

            [[package]]
            name = "requests"
            version = "2.31.0"
            source = { registry = "https://pypi.org/simple" }
            [package.optional-dependencies]
            socks = [
                { name = "pysocks" },
            ]

            [[package]]
            name = "pysocks"
            version = "1.7.1"
            source = { registry = "https://pypi.org/simple" }
        """,
        )
        project = self._make_project(packages={"requests": {"version": "*", "extras": ["socks"]}})
        result = _parse_uv_lock(lock_path, project, "default")

        requests_entry = next(r for r in result if r["name"] == "requests")
        assert requests_entry["extras"] == ["socks"]

        pysocks_entry = next(r for r in result if r["name"] == "pysocks")
        # pysocks is extras-only, should have extra marker
        assert "markers" in pysocks_entry
        assert 'extra == "socks"' in pysocks_entry["markers"]

    def test_index_from_registry(self, tmp_path):
        from pipenv.uv_lock import _parse_uv_lock

        lock_path = self._write_lock(
            tmp_path,
            """\
            version = 1
            requires-python = ">= 3.10"

            [[package]]
            name = "pipenv-resolver"
            version = "0.0.0"
            source = { virtual = "." }
            dependencies = [
                { name = "private-pkg" },
            ]

            [[package]]
            name = "private-pkg"
            version = "1.0.0"
            source = { registry = "http://localhost:8080/simple" }
        """,
        )
        project = self._make_project(
            packages={"private-pkg": {"version": "*", "index": "local"}},
            sources=[
                {"name": "pypi", "url": "https://pypi.org/simple"},
                {"name": "local", "url": "http://localhost:8080/simple"},
            ],
        )
        result = _parse_uv_lock(lock_path, project, "default")

        pkg = result[0]
        # Pipfile index override should take precedence
        assert pkg["index"] == "local"

    def test_multiple_packages_with_hashes(self, tmp_path):
        from pipenv.uv_lock import _parse_uv_lock

        lock_path = self._write_lock(
            tmp_path,
            """\
            version = 1
            requires-python = ">= 3.10"

            [[package]]
            name = "pipenv-resolver"
            version = "0.0.0"
            source = { virtual = "." }
            dependencies = [
                { name = "requests" },
            ]

            [[package]]
            name = "certifi"
            version = "2023.7.22"
            source = { registry = "https://pypi.org/simple" }
            sdist = { hash = "sha256:sdist_hash" }
            wheels = [
                { hash = "sha256:wheel_hash" },
            ]

            [[package]]
            name = "requests"
            version = "2.31.0"
            source = { registry = "https://pypi.org/simple" }
            dependencies = [
                { name = "certifi" },
            ]
            sdist = { hash = "sha256:req_sdist" }
        """,
        )
        project = self._make_project(packages={"requests": "*"})
        result = _parse_uv_lock(lock_path, project, "default")

        assert len(result) == 2
        certifi = next(r for r in result if r["name"] == "certifi")
        assert sorted(certifi["hashes"]) == ["sha256:sdist_hash", "sha256:wheel_hash"]

    def test_python_full_version_normalized(self, tmp_path):
        from pipenv.uv_lock import _parse_uv_lock

        lock_path = self._write_lock(
            tmp_path,
            """\
            version = 1
            requires-python = ">= 3.10"

            [[package]]
            name = "pipenv-resolver"
            version = "0.0.0"
            source = { virtual = "." }
            dependencies = [
                { name = "mylib", marker = "python_full_version >= '3.8'" },
            ]

            [[package]]
            name = "mylib"
            version = "1.0.0"
            source = { registry = "https://pypi.org/simple" }
        """,
        )
        project = self._make_project(packages={"mylib": "*"})
        result = _parse_uv_lock(lock_path, project, "default")

        mylib = result[0]
        assert mylib["markers"] == "python_version >= '3.8'"


# ---------------------------------------------------------------------------
# _build_uv_lock_cmd
# ---------------------------------------------------------------------------


class TestBuildUvLockCmd:
    """Tests for pipenv.uv_lock._build_uv_lock_cmd."""

    def test_basic_command(self, tmp_path):
        from pipenv.uv_lock import _build_uv_lock_cmd

        project = mock.MagicMock()
        project.pipfile_sources.return_value = [{"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}]

        with mock.patch("pipenv.uv.find_uv_bin", return_value="/usr/bin/uv"):
            cmd = _build_uv_lock_cmd(project, str(tmp_path))

        assert cmd[0] == "/usr/bin/uv"
        assert cmd[1] == "lock"
        assert f"--project={tmp_path}" in cmd
        assert "--index-strategy=unsafe-best-match" in cmd
        assert "--prerelease=allow" not in cmd

    def test_pre_release_flag(self, tmp_path):
        from pipenv.uv_lock import _build_uv_lock_cmd

        project = mock.MagicMock()
        project.pipfile_sources.return_value = []

        with mock.patch("pipenv.uv.find_uv_bin", return_value="/usr/bin/uv"):
            cmd = _build_uv_lock_cmd(project, str(tmp_path), pre=True)

        assert "--prerelease=allow" in cmd

    def test_insecure_host(self, tmp_path):
        from pipenv.uv_lock import _build_uv_lock_cmd

        project = mock.MagicMock()
        project.pipfile_sources.return_value = [{"name": "local", "url": "http://localhost:8080/simple", "verify_ssl": False}]

        with mock.patch("pipenv.uv.find_uv_bin", return_value="/usr/bin/uv"):
            cmd = _build_uv_lock_cmd(project, str(tmp_path))

        assert "--allow-insecure-host=localhost:8080" in cmd


# ---------------------------------------------------------------------------
# uv_lock_resolve (high-level test with mocks)
# ---------------------------------------------------------------------------


class TestUvLockResolve:
    """Tests for pipenv.uv_lock.uv_lock_resolve."""

    def test_falls_back_when_no_constraints_file(self):
        import pipenv.uv_lock as uv_lock_mod

        original_resolve = mock.MagicMock(return_value=mock.MagicMock(returncode=0))
        uv_lock_mod._original_resolve = original_resolve

        cmd = ["python", "resolver.py", "--write", "/tmp/out.json"]
        result = uv_lock_mod.uv_lock_resolve(cmd, mock.MagicMock(), mock.MagicMock())

        original_resolve.assert_called_once()
        uv_lock_mod._original_resolve = None  # cleanup

    def test_raises_if_no_original_resolve(self):
        import pipenv.uv_lock as uv_lock_mod

        uv_lock_mod._original_resolve = None
        cmd = ["python", "resolver.py"]
        with pytest.raises(RuntimeError, match="Original resolve"):
            uv_lock_mod.uv_lock_resolve(cmd, mock.MagicMock(), mock.MagicMock())


# ---------------------------------------------------------------------------
# patch()
# ---------------------------------------------------------------------------


class TestPatch:
    """Tests for pipenv.uv_lock.patch."""

    def test_patch_noop_when_uv_not_set(self):
        import pipenv.uv_lock as uv_lock_mod

        # Reset state
        uv_lock_mod._original_resolve = None
        uv_lock_mod._original_pip_install_deps = None

        with mock.patch.dict(os.environ, {}, clear=True):
            uv_lock_mod.patch()

        assert uv_lock_mod._original_resolve is None
        assert uv_lock_mod._original_pip_install_deps is None

    def test_patch_noop_when_uv_false(self):
        import pipenv.uv_lock as uv_lock_mod

        uv_lock_mod._original_resolve = None
        uv_lock_mod._original_pip_install_deps = None

        with mock.patch.dict(os.environ, {"PIPENV_UV": "0"}, clear=True):
            uv_lock_mod.patch()

        assert uv_lock_mod._original_resolve is None

    def test_patch_applies_when_uv_set(self):
        import pipenv.uv_lock as uv_lock_mod

        uv_lock_mod._original_resolve = None
        uv_lock_mod._original_pip_install_deps = None

        original_resolver_resolve = mock.MagicMock()
        original_pip_install = mock.MagicMock()

        with (
            mock.patch.dict(os.environ, {"PIPENV_UV": "1"}, clear=True),
            mock.patch("pipenv.uv.find_uv_bin", return_value="/usr/bin/uv"),
            mock.patch("pipenv.utils.resolver.resolve", original_resolver_resolve),
            mock.patch("pipenv.utils.pip.pip_install_deps", original_pip_install),
        ):
            uv_lock_mod.patch()

            # The originals should now be saved
            assert uv_lock_mod._original_resolve is original_resolver_resolve
            assert uv_lock_mod._original_pip_install_deps is original_pip_install

        # Cleanup
        uv_lock_mod._original_resolve = None
        uv_lock_mod._original_pip_install_deps = None

    def test_patch_idempotent(self):
        import pipenv.uv_lock as uv_lock_mod

        # Simulate already patched
        uv_lock_mod._original_resolve = mock.MagicMock()
        uv_lock_mod._original_pip_install_deps = None

        # Should return early without any patches
        uv_lock_mod.patch()

        # Cleanup
        uv_lock_mod._original_resolve = None
