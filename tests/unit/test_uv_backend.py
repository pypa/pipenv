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
from unittest import mock

import pytest

from pipenv.resolver.backends import get_backend, list_backends
from pipenv.resolver.backends import uv as uv_backend
from pipenv.resolver.backends.uv import (
    UvBackend,
    _fold_markers,
    _parse_compile_output,
    _parse_spec,
    _render_pyproject,
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

    def test_cycles_terminate(self):
        parents = {"a": {"", "b"}, "b": {"a"}}
        folded = _fold_markers(parents, self._deps(a="os_name == 'nt'"))
        assert folded["b"] == "os_name == 'nt'"


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
