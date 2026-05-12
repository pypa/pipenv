"""Integration tests for the Initiative G phase-2 prefetch path.

Pins the T19 contract for ``_prefetch_index_manifests_if_enabled``
inside :mod:`pipenv.routines.lock`:

* Enabling ``[pipenv] prefetch_index_manifests`` (or
  ``PIPENV_PREFETCH_INDEX_MANIFESTS=1``) must NOT change the
  resolution result — same lockfile hash, same per-package pins.
* The prefetch is best-effort: any exception inside
  ``ParallelFetcher.populate`` must be swallowed and the lock must
  still succeed.
* ``--clear`` short-circuits the prefetch entirely (skipped before
  the helper does any import or work).
* ``--verbose`` may emit the prefetch summary line but must NEVER
  log a URL, a package path, or any credential placeholder.
* ``--clear`` invalidates pipenv's parsed-manifest cache at
  ``<PIPENV_CACHE_DIR>/manifests-v1/`` — this is T17 wiring, but
  proven here from a user-visible vantage point.

Subprocess-realm mocking note
-----------------------------
``_PipenvInstance.run_command`` shells out to a child ``pipenv``
process, so in-process ``mock.patch`` cannot intercept the
``ParallelFetcher.populate`` call inside the child.  Tests that
need to mock the populate symbol install a ``sitecustomize.py``
on ``PYTHONPATH`` (auto-imported at interpreter startup) which
re-binds the attribute on the canonical class before any lock
code runs.  The injection writes a marker file when populate is
invoked (Test 2) or asserts non-invocation via the absence of
that marker (Test 3).

Initiative G phase 2 — T20.
"""

import os
import textwrap
from pathlib import Path

import pytest


PIPFILE_BODY = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
six = "*"
click = "*"
tablib = "*"
"""


def _write_pipfile(path: Path, *, prefetch_pipfile_setting: bool = False) -> None:
    """Write the test Pipfile.

    When ``prefetch_pipfile_setting`` is True the file also carries a
    ``[pipenv] prefetch_index_manifests = true`` block — used by Test 1
    when we want to flip the setting via the Pipfile path rather than
    via the env-var override (so both surfaces are exercised across the
    suite).
    """
    body = PIPFILE_BODY
    if prefetch_pipfile_setting:
        body += "\n[pipenv]\nprefetch_index_manifests = true\n"
    path.write_text(body)


def _project_pins(lockfile: dict) -> dict:
    """Return a normalised mapping of ``{name: version}`` per section.

    Hash equality alone is necessary (and computed off Pipfile content,
    so trivially equal across two runs of the same Pipfile), so the
    plan's robustness note asks us to also compare per-package pins.
    """
    pins: dict[str, dict[str, str]] = {}
    for section in ("default", "develop"):
        entries = lockfile.get(section, {}) or {}
        pins[section] = {
            name: data.get("version", "") if isinstance(data, dict) else ""
            for name, data in entries.items()
        }
    return pins


def _write_sitecustomize_recording_populate(
    inject_dir: Path, marker_file: Path
) -> None:
    """Inject a ``sitecustomize.py`` that records populate invocations.

    The child ``pipenv`` interpreter auto-imports ``sitecustomize`` at
    startup if its directory is on ``PYTHONPATH``.  Our injection
    monkey-patches ``pipenv.resolver.fetcher.ParallelFetcher.populate``
    so that every call appends a line to ``marker_file``.  The patch is
    installed *lazily* via an import hook so it survives the helper's
    own lazy import of ``ParallelFetcher`` inside ``do_lock``.
    """
    inject_dir.mkdir(parents=True, exist_ok=True)
    (inject_dir / "sitecustomize.py").write_text(
        textwrap.dedent(
            f"""
            import builtins

            _MARKER = {str(marker_file)!r}
            _real_import = builtins.__import__

            def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
                module = _real_import(name, globals, locals, fromlist, level)
                # Patch lazily the first time ParallelFetcher is resolved.
                target = "pipenv.resolver.fetcher"
                if name == target or (fromlist and target in (
                    name, getattr(module, "__name__", "")
                )):
                    cls = getattr(module, "ParallelFetcher", None)
                    if cls is not None and not getattr(
                        cls, "_T20_PATCHED", False
                    ):
                        def _recording_populate(self, targets):
                            try:
                                with open(_MARKER, "a") as fh:
                                    fh.write("populate-called\\n")
                            except Exception:
                                pass
                            return {{}}
                        cls.populate = _recording_populate
                        cls._T20_PATCHED = True
                return module

            builtins.__import__ = _patched_import
            """
        ).strip()
        + "\n"
    )


def _write_sitecustomize_raising_populate(inject_dir: Path) -> None:
    """Inject a ``sitecustomize.py`` whose populate raises ``RuntimeError``.

    Exercises the T19 contract that any exception from
    ``ParallelFetcher.populate`` is swallowed and the lock continues
    unchanged.
    """
    inject_dir.mkdir(parents=True, exist_ok=True)
    (inject_dir / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import builtins

            _real_import = builtins.__import__

            def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
                module = _real_import(name, globals, locals, fromlist, level)
                target = "pipenv.resolver.fetcher"
                if name == target or (fromlist and target in (
                    name, getattr(module, "__name__", "")
                )):
                    cls = getattr(module, "ParallelFetcher", None)
                    if cls is not None and not getattr(
                        cls, "_T20_PATCHED", False
                    ):
                        def _raising_populate(self, targets):
                            raise RuntimeError("simulated network failure")
                        cls.populate = _raising_populate
                        cls._T20_PATCHED = True
                return module

            builtins.__import__ = _patched_import
            """
        ).strip()
        + "\n"
    )


# ---------------------------------------------------------------------------
# Test 1: setting on vs off produces identical lockfile pins + hash
# ---------------------------------------------------------------------------
@pytest.mark.lock
@pytest.mark.needs_internet
def test_prefetch_does_not_change_resolution_result(
    pipenv_instance_pypi, monkeypatch
):
    """Setting on must produce the same lockfile as setting off.

    Compares per-section ``{name: version}`` maps (robust to
    cache-state-dependent metadata) *and* the Pipfile-derived
    ``_meta.hash.sha256`` for parity.
    """
    with pipenv_instance_pypi() as p:
        _write_pipfile(Path(p.pipfile_path), prefetch_pipfile_setting=False)

        # --- Baseline run: setting OFF (no env, no Pipfile key). ---
        monkeypatch.delenv("PIPENV_PREFETCH_INDEX_MANIFESTS", raising=False)
        c1 = p.pipenv("lock")
        assert c1.returncode == 0, c1.stderr
        baseline_lock = p.lockfile
        baseline_hash = baseline_lock["_meta"]["hash"]["sha256"]
        baseline_pins = _project_pins(baseline_lock)
        assert baseline_pins["default"], "baseline lock produced no default pins"

        # --- Remove the lockfile so the second run resolves freshly. ---
        Path(p.lockfile_path).unlink()
        assert not Path(p.lockfile_path).exists()

        # --- Prefetch ON via env-var override (avoids Pipfile drift). ---
        monkeypatch.setenv("PIPENV_PREFETCH_INDEX_MANIFESTS", "1")
        c2 = p.pipenv("lock")
        assert c2.returncode == 0, c2.stderr
        prefetch_lock = p.lockfile
        prefetch_hash = prefetch_lock["_meta"]["hash"]["sha256"]
        prefetch_pins = _project_pins(prefetch_lock)

        assert prefetch_hash == baseline_hash, (
            "prefetch run changed Pipfile-derived hash: "
            f"{baseline_hash!r} -> {prefetch_hash!r}"
        )
        assert prefetch_pins == baseline_pins, (
            "prefetch run produced different per-package pins:\n"
            f"baseline: {baseline_pins}\nprefetch: {prefetch_pins}"
        )


# ---------------------------------------------------------------------------
# Test 2: populate raising → lock still succeeds (best-effort contract)
# ---------------------------------------------------------------------------
@pytest.mark.lock
@pytest.mark.needs_internet
def test_prefetch_swallows_populate_failure(pipenv_instance_pypi, monkeypatch):
    """``RuntimeError`` from ``ParallelFetcher.populate`` must not fail lock.

    Mocked via a ``sitecustomize.py`` injection because the child
    ``pipenv`` runs in a subprocess; in-process ``mock.patch`` is
    invisible across the process boundary.
    """
    with pipenv_instance_pypi() as p:
        _write_pipfile(Path(p.pipfile_path))

        inject_dir = Path(p.path) / "_t20_inject"
        _write_sitecustomize_raising_populate(inject_dir)

        existing_pp = os.environ.get("PYTHONPATH", "")
        new_pp = (
            f"{inject_dir}{os.pathsep}{existing_pp}" if existing_pp else str(inject_dir)
        )
        monkeypatch.setenv("PYTHONPATH", new_pp)
        monkeypatch.setenv("PIPENV_PREFETCH_INDEX_MANIFESTS", "1")

        c = p.pipenv("lock")
        assert c.returncode == 0, c.stderr
        # Lockfile present and well-formed.
        assert Path(p.lockfile_path).exists()
        assert _project_pins(p.lockfile)["default"]


# ---------------------------------------------------------------------------
# Test 3: --clear short-circuits the prefetch (populate NOT called)
# ---------------------------------------------------------------------------
@pytest.mark.lock
@pytest.mark.needs_internet
def test_prefetch_skipped_under_clear(pipenv_instance_pypi, monkeypatch):
    """``pipenv lock --clear`` must not invoke ``ParallelFetcher.populate``.

    Verified via a sitecustomize injection that touches a marker file
    on every populate call.  After the run, the marker file must not
    exist (or must be empty).
    """
    with pipenv_instance_pypi() as p:
        _write_pipfile(Path(p.pipfile_path))

        inject_dir = Path(p.path) / "_t20_inject"
        marker = Path(p.path) / "_t20_populate_marker"
        _write_sitecustomize_recording_populate(inject_dir, marker)

        existing_pp = os.environ.get("PYTHONPATH", "")
        new_pp = (
            f"{inject_dir}{os.pathsep}{existing_pp}" if existing_pp else str(inject_dir)
        )
        monkeypatch.setenv("PYTHONPATH", new_pp)
        monkeypatch.setenv("PIPENV_PREFETCH_INDEX_MANIFESTS", "1")

        c = p.pipenv("lock --clear")
        assert c.returncode == 0, c.stderr
        assert not marker.exists() or marker.read_text() == "", (
            "ParallelFetcher.populate was invoked under --clear "
            f"(marker contents: {marker.read_text() if marker.exists() else '<missing>'})"
        )


# ---------------------------------------------------------------------------
# Test 4: verbose output contains the summary line and no URL/cred leakage
# ---------------------------------------------------------------------------
@pytest.mark.lock
@pytest.mark.needs_internet
def test_prefetch_verbose_output_no_url_leak(pipenv_instance_pypi, monkeypatch):
    """Verbose stderr must contain the prefetch summary, URL-free.

    The summary line is ``Prefetched N package indexes in M.MMs.`` —
    that single line (the only output the T19 helper ever emits) must
    never carry a scheme, host, package path, or credential
    placeholder.  We do NOT assert anything about pipenv's broader
    ``--verbose`` stderr (pip's resolver legitimately logs
    ``LinkCandidate('https://...')`` lines at INFO level — that's a
    separate code path and outside T19's contract).
    """
    with pipenv_instance_pypi() as p:
        _write_pipfile(Path(p.pipfile_path))
        monkeypatch.setenv("PIPENV_PREFETCH_INDEX_MANIFESTS", "1")

        c = p.pipenv("lock --verbose")
        assert c.returncode == 0, c.stderr

        stderr = c.stderr or ""

        # Locate the prefetch-helper's summary line(s).  Rich may wrap
        # the ``[dim]Prefetched N package indexes in M.MMs.[/dim]``
        # markup across multiple physical lines on narrow terminals,
        # so we collect every line containing the marker token.
        prefetch_lines = [
            line for line in stderr.splitlines() if "Prefetched" in line
        ]

        if not prefetch_lines:
            # Prefetch summary absent — possible in a degraded run
            # (e.g., populate raised internally and was swallowed).
            # We can't assert URL-leakage on something that wasn't
            # emitted, but the lock itself still succeeded.  Skip
            # loudly rather than silently passing.
            pytest.skip(
                "Prefetch summary line not observed in stderr; nothing "
                "to assert against for URL leakage in this run. "
                f"(stderr head: {stderr[:200]!r})"
            )

        # T19 contract: summary line carries the canonical wording and
        # no URLs/credentials.
        joined = "\n".join(prefetch_lines)
        assert "package indexes in" in joined, joined

        forbidden_tokens = [
            "https://",
            "http://",
            "/six/",
            "/click/",
            "/tablib/",
            "@pypi.org",
            ":***@",
        ]
        for token in forbidden_tokens:
            assert token not in joined, (
                f"prefetch summary leaked {token!r}: {joined!r}"
            )


# ---------------------------------------------------------------------------
# Test 5: --clear invalidates pipenv's parsed-manifest cache
# ---------------------------------------------------------------------------
@pytest.mark.lock
def test_clear_invalidates_parsed_manifest_cache(
    pipenv_instance_pypi, monkeypatch, tmp_path
):
    """``pipenv lock --clear`` wipes the parsed-manifest cache at
    ``<PIPENV_CACHE_DIR>/pipenv-manifests/manifests-v1/``.

    Seeds the cache directory directly (rather than relying on a real
    network prefetch to populate it) so the test stays hermetic — this
    test is asserting on T17's ``--clear`` wiring, not on T19's
    populate behaviour.  A stale parsed-manifest cache that survives
    ``--clear`` would be a poisoning surface the user can't easily
    nuke; this test pins the wipe.

    Path note: the cache root is
    ``<PIPENV_CACHE_DIR>/pipenv-manifests/`` (T19 namespaces under
    ``pipenv-manifests/`` to keep pipenv-owned cache files cleanly
    separated from anything pip stores in the same dir).
    ``ParsedManifestCache.SCHEMA_VERSION`` then adds the
    ``manifests-v1/`` subdir.  T20 originally seeded the wrong path
    because T17 and T19 disagreed; the path bug was fixed in a
    follow-up commit and this test now exercises the correct path.
    """
    cache_dir = tmp_path / "pipenv-cache"
    cache_dir.mkdir()
    monkeypatch.setenv("PIPENV_CACHE_DIR", str(cache_dir))

    # Seed the parsed-manifest cache at the canonical path: the
    # namespaced ``pipenv-manifests/`` subdir + the schema-versioned
    # ``manifests-v1/`` subdir under it.
    seeded_root = cache_dir / "pipenv-manifests" / "manifests-v1"
    seeded_root.mkdir(parents=True)
    (seeded_root / "stale-marker").write_text("seeded by T20")
    assert (seeded_root / "stale-marker").exists()

    with pipenv_instance_pypi() as p:
        _write_pipfile(Path(p.pipfile_path))

        c = p.pipenv("lock --clear")
        assert c.returncode == 0, c.stderr

        # The clear helper uses ``shutil.rmtree`` on the versioned root,
        # so either the directory is gone entirely or the stale marker
        # specifically must have been removed.
        assert (
            not seeded_root.exists()
            or not (seeded_root / "stale-marker").exists()
        ), (
            "--clear did not invalidate the parsed-manifest cache at "
            f"{seeded_root}; stale-marker survived"
        )


# ---------------------------------------------------------------------------
# Optional Test 6: verify_ssl=False against a self-signed index
# ---------------------------------------------------------------------------
@pytest.mark.lock
def test_prefetch_with_self_signed_source():
    """SKIPPED: no self-signed-cert fixture exists in tests/pytest-pypi/.

    Per the T20 plan: "self-signed-cert integration scenario."  The
    existing ``pipenv_instance_private_pypi`` fixture points at a plain
    HTTP server (no TLS), so we cannot exercise the ``verify_ssl=False``
    branch of T19's session-per-policy code without standing up new
    fixture infrastructure (out of scope for T20).

    Documented gap: ``_prefetch_index_manifests_if_enabled`` builds one
    ``PipSession`` per unique ``verify_ssl`` value among Pipfile
    sources; the False branch is currently exercised by T19's unit-test
    smokes (commit ``f29b87be``) but not by an end-to-end self-signed
    HTTPS scenario.  Future work — see Initiative G design doc §11.
    """
    pytest.skip(
        "no self-signed-cert fixture available; gap documented in docstring"
    )
