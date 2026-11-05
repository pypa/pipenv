"""Unit tests for :class:`UvBackend` (gh-6109).

The backend shells out to ``uv pip compile``; every test here mocks the
subprocess (and the Pipfile read) so no ``uv`` binary or network is
needed.  Coverage:

* **Spec translation** — pip-install argument lines (extras, markers,
  ``-i`` index pins, VCS, file URLs, editable paths) become uv inputs.
* **Index restriction** — the generated ``pyproject.toml`` marks every
  non-primary source ``explicit = true`` so unpinned packages resolve
  only from the primary index.
* **Output parsing** — ``--hash`` and ``# via`` annotations, editable
  lines, and marker folding onto transitive dependencies.
* **Failure modes** — uv exit 1 → ``ResolutionError``; other non-zero
  exits → ``InternalError``; missing binary → ``InternalError`` with
  the install hint, both from the backend and from the dispatcher.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from pipenv.resolver.backends import get_backend, list_backends
from pipenv.resolver.backends import uv as uv_backend
from pipenv.resolver.backends.uv import (
    UvBackend,
    _fold_markers,
    _parse_compile_output,
    _parse_spec,
    _render_constraints,
    _render_pyproject,
    _unneeded_pin_only,
    _uv_environment,
    _vcs_pin,
)
from pipenv.resolver.schema import (
    SCHEMA_VERSION,
    InternalError,
    LockedRequirement,
    PackageSpecs,
    ResolutionError,
    ResolvedDeps,
    ResolverOptions,
    ResolverRequest,
    ResolverSuccess,
    Source,
    VCSPin,
)

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    tomllib = None

_PYPI = "https://pypi.org/simple"
_PRIVATE = "https://private.example.com/simple"
_URL_TO_NAME = {_PYPI: "pypi", _PRIVATE: "private"}


def _request(specs, *, category="packages", resolved_default_deps=None, pre=False):
    return ResolverRequest(
        schema_version=SCHEMA_VERSION,
        category=category,
        packages=PackageSpecs(specs=specs),
        options=ResolverOptions(backend="uv", pre=pre),
        sources=(
            Source(name="pypi", url=_PYPI),
            Source(name="private", url=_PRIVATE, verify_ssl=False),
        ),
        python_marker_override="3.11.4",
        resolved_default_deps=resolved_default_deps,
    )


# ---------------------------------------------------------------------------
# Registry / availability
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_uv_is_registered(self):
        assert "uv" in list_backends()
        assert isinstance(get_backend("uv"), UvBackend)

    def test_is_available_follows_path_lookup(self):
        backend = UvBackend()
        with mock.patch.object(uv_backend.shutil, "which", return_value="/bin/uv"):
            assert backend.is_available() is True
        with mock.patch.object(uv_backend.shutil, "which", return_value=None):
            assert backend.is_available() is False

    def test_dispatcher_reports_install_hint_when_uv_missing(self):
        from pipenv.resolver.core import resolve_for_pipenv

        with mock.patch.object(uv_backend.shutil, "which", return_value=None):
            response = resolve_for_pipenv(_request({"six": "six"}))
        assert isinstance(response.result, InternalError)
        assert "uv was not found on $PATH" in response.result.message
        assert "pip install uv" in response.result.message


# ---------------------------------------------------------------------------
# Spec translation
# ---------------------------------------------------------------------------


class TestParseSpec:
    def test_extras_and_markers(self):
        dep = _parse_spec(
            "requests",
            "requests[socks]>=2.30; sys_platform == 'linux'",
            None,
            _URL_TO_NAME,
        )
        assert dep.extras == ("socks",)
        assert dep.markers == "sys_platform == 'linux'"
        assert dep.specifier == ">=2.30"
        assert dep.index is None

    def test_index_flag_maps_to_source_name(self):
        dep = _parse_spec("torch", f"torch -i {_PRIVATE}", None, _URL_TO_NAME)
        assert dep.index == "private"
        assert dep.pep508 == "torch"

    def test_index_flag_matches_source_with_credentials(self):
        dep = _parse_spec(
            "torch",
            "torch -i https://user:secret@private.example.com/simple/",
            None,
            _URL_TO_NAME,
        )
        assert dep.index == "private"

    def test_lock_index_follows_pip_backend_rule(self):
        # Plain string Pipfile entry → records the index it resolves from.
        string_entry = _parse_spec("six", "six", "*", _URL_TO_NAME)
        assert string_entry.lock_index == "pypi"
        # Dict entry without ``index`` → no ``index`` in the lockfile,
        # even though ``convert_deps_to_pip`` added ``-i <primary>``.
        dict_entry = _parse_spec(
            "requests", f"requests -i {_PYPI}", {"version": "*"}, _URL_TO_NAME
        )
        assert dict_entry.lock_index is None
        assert dict_entry.index == "pypi"

    def test_vcs_spec(self):
        dep = _parse_spec(
            "attrs",
            "attrs @ git+https://github.com/python-attrs/attrs.git@25.3.0#subdirectory=src",
            {"git": "https://github.com/python-attrs/attrs.git", "editable": True},
            _URL_TO_NAME,
        )
        assert dep.vcs.backend == "git"
        assert dep.vcs.url == "https://github.com/python-attrs/attrs.git"
        assert dep.vcs.ref == "25.3.0"
        assert dep.vcs.subdirectory == "src"
        assert dep.editable is True
        assert dep.lock_index is None

    def test_editable_path(self, tmp_path):
        pkg = tmp_path / "localpkg"
        pkg.mkdir()
        dep = _parse_spec(
            "localpkg",
            f"-e {pkg}",
            {"path": "./localpkg", "editable": True},
            _URL_TO_NAME,
        )
        assert dep.editable is True
        assert dep.path == "./localpkg"
        assert dep.abs_path == str(pkg)

    def test_editable_path_with_extras_and_markers(self, tmp_path):
        pkg = tmp_path / "localpkg"
        pkg.mkdir()
        dep = _parse_spec(
            "localpkg",
            f"-e {pkg}[test,docs]; sys_platform == 'linux'",
            {"path": str(pkg), "editable": True},
            _URL_TO_NAME,
        )
        assert dep.abs_path == str(pkg)
        assert dep.extras == ("docs", "test")
        assert dep.markers == "sys_platform == 'linux'"

    def test_non_editable_local_file_is_a_direct_reference(self, tmp_path):
        wheel = tmp_path / "pkg-1.0-py3-none-any.whl"
        dep = _parse_spec(
            "pkg",
            f"{wheel}[extra]; os_name == 'posix'",
            {"file": str(wheel)},
            _URL_TO_NAME,
        )
        assert dep.pep508 == f"pkg[extra] @ {wheel.as_uri()} ; os_name == 'posix'"
        assert dep.file == str(wheel)
        assert dep.path is None

    def test_package_named_like_a_local_directory_is_not_a_path(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "flask").mkdir()
        monkeypatch.chdir(tmp_path)
        dep = _parse_spec("flask", "flask", "*", _URL_TO_NAME)
        assert dep.abs_path is None
        assert dep.path is None
        assert dep.pep508 == "flask"

    @pytest.mark.parametrize(
        "spec, url, vcs",
        [
            (
                "pkg @ https://example.com/pkg-1.0.whl; os_name == 'posix'",
                "https://example.com/pkg-1.0.whl",
                False,
            ),
            (
                "pkg @ git+https://example.com/r.git@v1; os_name == 'posix'",
                "git+https://example.com/r.git@v1",
                True,
            ),
        ],
    )
    def test_url_with_marker_and_no_space(self, spec, url, vcs):
        dep = _parse_spec("pkg", spec, None, _URL_TO_NAME)
        assert dep.markers == "os_name == 'posix'"
        assert dep.pep508.startswith(f"pkg @ {url} ;")
        assert bool(dep.vcs) is vcs

    def test_legacy_local_vcs_spec(self):
        entry = {
            "git": "file:///repo",
            "ref": "abc",
            "editable": True,
            "extras": ["x"],
            "subdirectory": "sub",
            "markers": "os_name == 'posix'",
        }
        dep = _parse_spec(
            "pkg",
            "-e git+file:///repo@abc#egg=pkg&subdirectory=sub[x]",
            entry,
            _URL_TO_NAME,
        )
        assert dep.pep508.startswith("pkg[x] @ git+file:///repo@abc#subdirectory=sub ;")
        assert dep.vcs == VCSPin(
            backend="git", url="file:///repo", ref="abc", subdirectory="sub"
        )
        assert dep.extras == ("x",)
        assert dep.markers == "os_name == 'posix'"
        assert dep.editable is True

    def test_legacy_vcs_editable_follows_pipfile(self):
        dep = _parse_spec(
            "pkg", "-e git+file:///repo#egg=pkg", {"git": "file:///repo"}, _URL_TO_NAME
        )
        assert dep.pep508 == "pkg @ git+file:///repo"
        assert dep.editable is False

    def test_legacy_vcs_local_path_repository(self, tmp_path):
        dep = _parse_spec(
            "pkg",
            f"-e git+{tmp_path}@abc#egg=pkg",
            {"git": str(tmp_path), "ref": "abc"},
            _URL_TO_NAME,
        )
        assert dep.pep508 == f"pkg @ git+{tmp_path.as_uri()}@abc"
        assert dep.vcs.ref == "abc"

    def test_remote_file(self):
        url = "https://files.example.com/idna-3.20-py3-none-any.whl"
        dep = _parse_spec("idna", f"idna @ {url}", {"file": url}, _URL_TO_NAME)
        assert dep.file == url
        assert dep.abs_path is None

    def test_vcs_pin_ssh_url_keeps_user(self):
        pin = _vcs_pin("git+ssh://git@github.com/org/repo.git@abc123")
        assert pin.url == "ssh://git@github.com/org/repo.git"
        assert pin.ref == "abc123"


# ---------------------------------------------------------------------------
# Generated pyproject.toml
# ---------------------------------------------------------------------------


class TestRenderPyproject:
    def _render(self, specs, entries=None, pins=None):
        deps = [
            _parse_spec(name, spec, (entries or {}).get(name), _URL_TO_NAME)
            for name, spec in specs.items()
        ]
        index_pins = dict(pins or {})
        for dep in deps:
            if dep.index:
                index_pins[dep.name] = dep.index
        sources = [Source(name="pypi", url=_PYPI), Source(name="private", url=_PRIVATE)]
        return _render_pyproject(deps, sources, index_pins)

    def test_non_primary_sources_are_explicit(self):
        text = self._render({"six": "six", "torch": f"torch -i {_PRIVATE}"})
        if tomllib is None:
            pytest.skip("tomllib unavailable")
        data = tomllib.loads(text)
        # The primary index is passed as UV_DEFAULT_INDEX, not declared here.
        indexes = data["tool"]["uv"]["index"]
        assert indexes == [{"name": "private", "url": _PRIVATE, "explicit": True}]
        sources = data["tool"]["uv"]["sources"]
        assert sources == {"torch": {"index": "private"}}
        assert data["project"]["dependencies"] == ["six", "torch"]

    def test_pins_to_primary_are_omitted(self):
        text = self._render({"requests": f"requests -i {_PYPI}"})
        if tomllib is None:
            pytest.skip("tomllib unavailable")
        assert tomllib.loads(text)["tool"]["uv"].get("sources", {}) == {}

    def test_editable_path_becomes_path_source(self, tmp_path):
        pkg = tmp_path / "localpkg"
        pkg.mkdir()
        text = self._render(
            {"localpkg": f"-e {pkg}"},
            entries={"localpkg": {"path": str(pkg), "editable": True}},
        )
        if tomllib is None:
            pytest.skip("tomllib unavailable")
        data = tomllib.loads(text)
        assert data["project"]["dependencies"] == ["localpkg"]
        assert data["tool"]["uv"]["sources"]["localpkg"] == {
            "path": str(pkg),
            "editable": True,
        }

    def test_skip_resolver_entries_are_not_resolved(self):
        text = self._render(
            {"six": "six", "odd": "odd"}, entries={"odd": {"skip_resolver": True}}
        )
        if tomllib is None:
            pytest.skip("tomllib unavailable")
        assert tomllib.loads(text)["project"]["dependencies"] == ["six"]


# ---------------------------------------------------------------------------
# Output parsing and marker folding
# ---------------------------------------------------------------------------


_COMPILE_OUTPUT = """\
-e /work/localpkg
    # via your-pipfile (pyproject.toml)
attrs @ git+https://github.com/python-attrs/attrs.git@3dca08ce5bbe673d7df25f44f3dda92505d1043d
    # via your-pipfile (pyproject.toml)
pluggy==1.7.0 \\
    --hash=sha256:bbb \\
    --hash=sha256:aaa
    # via pytest
pytest==9.2.0 \\
    --hash=sha256:ccc
    # via your-pipfile (pyproject.toml)
six==1.17.0 \\
    --hash=sha256:ddd
    # via
    #   localpkg
    #   pytest
"""


class TestParseCompileOutput:
    def test_blocks_hashes_and_via(self):
        entries = {e.line.split("==")[0]: e for e in _parse_compile_output(_COMPILE_OUTPUT)}
        assert entries["pluggy"].hashes == ["sha256:bbb", "sha256:aaa"]
        assert entries["pluggy"].via == ["pytest"]
        assert entries["six"].via == ["localpkg", "pytest"]
        assert entries["-e /work/localpkg"].via == ["your-pipfile (pyproject.toml)"]


class TestFoldMarkers:
    def _deps(self, **markers):
        return {
            name: mock.Mock(markers=marker)
            for name, marker in markers.items()
        }

    def test_marker_guarded_root_propagates(self):
        parents = {"pytest": {""}, "pluggy": {"pytest"}}
        folded = _fold_markers(parents, self._deps(pytest="sys_platform == 'linux'"))
        assert folded["pluggy"] == "sys_platform == 'linux'"

    def test_unconditional_path_wins(self):
        parents = {"a": {""}, "b": {""}, "shared": {"a", "b"}}
        folded = _fold_markers(parents, self._deps(a="os_name == 'nt'", b=None))
        assert folded["shared"] is None

    def test_alternative_markers_are_ored(self):
        parents = {"a": {""}, "b": {""}, "shared": {"a", "b"}}
        folded = _fold_markers(
            parents, self._deps(a="os_name == 'nt'", b="sys_platform == 'darwin'")
        )
        assert folded["shared"] == "(os_name == 'nt') or (sys_platform == 'darwin')"

    def test_cycle_through_other_root_keeps_every_marker(self):
        parents = {"a": {"", "b"}, "b": {"c"}, "c": {"a", "d"}, "d": {""}}
        folded = _fold_markers(
            parents, self._deps(a="os_name == 'posix'", d="os_name == 'nt'")
        )
        both = "(os_name == 'nt') or (os_name == 'posix')"
        assert folded["a"] == both
        assert folded["b"] == both
        assert folded["c"] == both
        assert folded["d"] == "os_name == 'nt'"

    def test_cycles_terminate(self):
        parents = {"a": {"", "b"}, "b": {"a"}}
        folded = _fold_markers(parents, self._deps(a="os_name == 'nt'"))
        assert folded["b"] == "os_name == 'nt'"


class TestUnneededPinOnly:
    def test_unused_pin_and_its_dependencies_are_unneeded(self):
        parents = {"app": {""}, "pinned": {""}, "helper": {"pinned"}}
        assert _unneeded_pin_only(parents, frozenset({"pinned"})) == {
            "pinned",
            "helper",
        }

    def test_used_pin_is_kept_without_its_root_edge(self):
        parents = {"app": {""}, "pinned": {"", "app"}, "helper": {"pinned"}}
        assert _unneeded_pin_only(parents, frozenset({"pinned"})) == set()
        assert parents["pinned"] == {"app"}

    def test_cycle_among_unused_pins_is_unneeded(self):
        parents = {"app": {""}, "x": {"", "y"}, "y": {"x"}}
        assert _unneeded_pin_only(parents, frozenset({"x"})) == {"x", "y"}


# ---------------------------------------------------------------------------
# End-to-end resolve() with the uv subprocess mocked
# ---------------------------------------------------------------------------


def _run_resolve(request, *, stdout="", stderr="", returncode=0, pipfile=({}, {})):
    completed = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)
    with mock.patch.object(uv_backend.shutil, "which", return_value="/usr/bin/uv"), \
            mock.patch.object(uv_backend, "_pipfile_context", return_value=pipfile), \
            mock.patch.object(uv_backend.subprocess, "run", return_value=completed) as run:
        response = UvBackend().resolve(request)
    return response, run


class TestResolve:
    def test_success_translates_entries(self, tmp_path):
        pkg = tmp_path / "localpkg"
        pkg.mkdir()
        output = _COMPILE_OUTPUT.replace("/work/localpkg", str(pkg))
        request = _request(
            {
                "localpkg": f"-e {pkg}",
                "attrs": "attrs @ git+https://github.com/python-attrs/attrs.git@25.3.0",
                "pytest": f"pytest; sys_platform == 'linux' -i {_PYPI}",
                "colorama": f"colorama; sys_platform == 'win32' -i {_PYPI}",
            }
        )
        entries = {
            "localpkg": {"path": "./localpkg", "editable": True},
            "pytest": {"version": "*", "markers": "sys_platform == 'linux'"},
            "colorama": {"version": "*", "markers": "sys_platform == 'win32'"},
        }
        response, run = _run_resolve(request, stdout=output, pipfile=(entries, {}))

        assert isinstance(response.result, ResolverSuccess), response.result
        locked = {entry.name: entry for entry in response.result.locked}
        assert locked["localpkg"].path == "./localpkg"
        assert locked["localpkg"].editable is True
        assert locked["attrs"].vcs.ref == "3dca08ce5bbe673d7df25f44f3dda92505d1043d"
        assert locked["pytest"].version == "==9.2.0"
        assert locked["pytest"].markers == "sys_platform == 'linux'"
        assert locked["pytest"].hashes == ("sha256:ccc",)
        assert locked["pluggy"].markers == "sys_platform == 'linux'"
        assert locked["pluggy"].hashes == ("sha256:aaa", "sha256:bbb")
        # ``six`` is needed unconditionally via localpkg.
        assert locked["six"].markers is None
        # colorama doesn't apply to this environment; recorded like the
        # pip backend does (no hashes, original specifier).
        assert locked["colorama"] == LockedRequirement(
            name="colorama", version="*", markers="sys_platform == 'win32'"
        )

        cmd = run.call_args.args[0]
        assert cmd[:3] == ["/usr/bin/uv", "pip", "compile"]
        assert "--generate-hashes" in cmd
        assert cmd[cmd.index("--python-version") + 1] == "3.11.4"
        assert cmd[cmd.index("--allow-insecure-host") + 1] == "private.example.com"
        assert cmd[cmd.index("--prerelease") + 1] == "explicit"

    def test_resolved_default_deps_become_constraints(self):
        resolved = ResolvedDeps(
            entries=(
                LockedRequirement(name="six", version="==1.17.0"),
                LockedRequirement(name="colorama", version="*"),
            )
        )
        request = _request({"pytest": "pytest"}, category="dev-packages",
                           resolved_default_deps=resolved, pre=True)
        captured = {}

        def fake_run(cmd, **kwargs):
            path = cmd[cmd.index("--constraint") + 1]
            with open(path, encoding="utf-8") as fh:
                captured["constraints"] = fh.read()
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(uv_backend.shutil, "which", return_value="/usr/bin/uv"), \
                mock.patch.object(uv_backend, "_pipfile_context", return_value=({}, {})), \
                mock.patch.object(uv_backend.subprocess, "run", side_effect=fake_run):
            UvBackend().resolve(request)
        assert captured["constraints"] == "six==1.17.0\n"

    def test_resolved_vcs_constraint_keeps_subdirectory(self):
        request = _request(
            {"six": "six"},
            category="dev-packages",
            resolved_default_deps=ResolvedDeps(
                entries=(
                    LockedRequirement(
                        name="pkg",
                        vcs=VCSPin(
                            backend="git",
                            url="https://example.com/r.git",
                            ref="abc",
                            subdirectory="sub",
                        ),
                    ),
                )
            ),
        )
        assert _render_constraints(request) == (
            "pkg @ git+https://example.com/r.git@abc#subdirectory=sub\n"
        )

    def test_foreign_pin_is_required_then_dropped_when_unused(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["pyproject"] = Path(cmd[3]).read_text(encoding="utf-8")
            return mock.Mock(
                returncode=0,
                stderr="",
                stdout=(
                    "app==1.0\n    # via your-pipfile (pyproject.toml)\n"
                    "helper==1.0\n    # via pinned\n"
                    "pinned==1.0\n    # via your-pipfile (pyproject.toml)\n"
                ),
            )

        with mock.patch("shutil.which", return_value="/usr/bin/uv"), mock.patch(
            "pipenv.resolver.backends.uv._pipfile_context",
            return_value=({}, {"pinned": "private"}),
        ), mock.patch("subprocess.run", side_effect=fake_run):
            response = UvBackend().resolve(
                _request({"app": "app"}, category="dev-packages")
            )
        assert '"pinned",' in captured["pyproject"]
        assert '"pinned" = { index = "private" }' in captured["pyproject"]
        assert [r.name for r in response.result.locked] == ["app"]

    def test_foreign_pin_used_transitively_is_locked_with_its_index(self):
        stdout = (
            "app==1.0\n    # via your-pipfile (pyproject.toml)\n"
            "pinned==1.0\n    # via\n"
            "    #   your-pipfile (pyproject.toml)\n    #   app\n"
        )
        with mock.patch("shutil.which", return_value="/usr/bin/uv"), mock.patch(
            "pipenv.resolver.backends.uv._pipfile_context",
            return_value=({}, {"pinned": "private"}),
        ), mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=0, stderr="", stdout=stdout),
        ):
            response = UvBackend().resolve(
                _request({"app": "app"}, category="dev-packages")
            )
        locked = {r.name: r for r in response.result.locked}
        assert locked["pinned"].index == "private"
        assert locked["pinned"].version == "==1.0"

    def test_non_editable_path_output_line_has_no_name(self, tmp_path):
        pkg = tmp_path / "localpkg"
        pkg.mkdir()
        entries = {"localpkg": {"path": str(pkg)}}
        stdout = f"{pkg}\n    # via your-pipfile (pyproject.toml)\n"
        response, _ = _run_resolve(
            _request({"localpkg": str(pkg)}), stdout=stdout, pipfile=(entries, {})
        )
        locked = response.result.locked
        assert [r.name for r in locked] == ["localpkg"]
        assert locked[0].path == str(pkg)

    def test_exit_1_is_resolution_error(self):
        response, _ = _run_resolve(
            _request({"six": "six"}),
            returncode=1,
            stderr="  × No solution found when resolving dependencies",
        )
        assert isinstance(response.result, ResolutionError)
        assert "No solution found" in response.result.pip_message

    def test_other_exit_is_internal_error(self):
        response, _ = _run_resolve(
            _request({"six": "six"}), returncode=2, stderr="error: unexpected argument"
        )
        assert isinstance(response.result, InternalError)
        assert "unexpected argument" in response.result.message

    def test_missing_binary_is_internal_error(self):
        with mock.patch.object(uv_backend.shutil, "which", return_value=None):
            response = UvBackend().resolve(_request({"six": "six"}))
        assert isinstance(response.result, InternalError)
        assert "uv was not found" in response.result.message

    @pytest.mark.parametrize(
        "variable", ["UV_NO_SOURCES", "UV_NO_SOURCES_PACKAGE", "UV_TORCH_BACKEND"]
    )
    def test_source_overriding_variables_are_scrubbed(self, monkeypatch, variable):
        monkeypatch.setenv(variable, "1")
        assert variable not in _uv_environment("https://pypi.org/simple")

    def test_primary_index_is_uv_default_index(self, monkeypatch):
        monkeypatch.setenv("UV_INDEX_URL", "https://evil.example.com/simple")
        monkeypatch.setenv("UV_DEFAULT_INDEX", "https://evil.example.com/simple")
        monkeypatch.setenv("PIP_KEYRING_PROVIDER", "auto")
        monkeypatch.delenv("UV_KEYRING_PROVIDER", raising=False)
        _, run = _run_resolve(_request({"six": "six"}))
        env = run.call_args.kwargs["env"]
        assert "UV_INDEX_URL" not in env
        assert env["UV_DEFAULT_INDEX"] == _PYPI
        # Never on the command line, where credentials would be visible.
        assert _PYPI not in run.call_args.args[0]
        assert env["UV_KEYRING_PROVIDER"] == "subprocess"
