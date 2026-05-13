"""Parallel wheel pre-fetch for ``pipenv install`` / ``pipenv sync``.

Pip's ``install`` step downloads wheels sequentially from the index —
on a clean cache that dominates cold-install wall time (12 s of pure
network for the sentry-base bench's 151 wheels, vs ~10 s for the
sequential install phase itself).  This module pre-populates a local
``--find-links`` directory by downloading wheels concurrently
(``urllib3`` connection-pool + ``ThreadPoolExecutor``, capped at 16
workers to match the pool ceiling that the pure-Python resolver
already standardised on) BEFORE pipenv invokes ``pip install``.  Pip
then sees the wheels in the find-links dir and skips its own
network round-trips for the matching files.

Design constraints
------------------

* **Best-effort, never raises**: any per-package failure (network
  hiccup, missing wheel for the target platform, hash mismatch)
  falls through silently and the regular pip-install path handles
  that package via the index.  pipenv MUST NOT degrade because the
  pre-fetch shortcut had a problem.

* **Hash-pinned**: every download body is SHA-256-verified against
  the lockfile entry's ``hashes`` list before writing to the
  find-links dir.  A hash mismatch is treated as a fetch failure —
  the wheel is dropped and pip downloads from the index instead.

* **Platform-aware**: the lockfile carries hashes for ALL wheel
  variants of a release (cp311-linux + cp310-macosx + ...).  We
  download only the wheel whose tags match the *target* Python's
  ``packaging.tags.sys_tags()`` — invoking ``<venv-python> -c "..."``
  once per pre-fetch to ask the target interpreter directly.  This
  avoids the host/target tag drift trap that bites every "guess the
  wheel from the running interpreter" implementation.

* **Cache-side-effect free for pip**: pre-fetched wheels go into a
  caller-managed temp dir, not pip's HTTP cache.  Pip is told about
  them via ``--find-links <dir>`` (kept alongside ``--index-url`` so
  any missing files still resolve from the index).  No mutation of
  the user's pip cache.

* **Existing resolver infrastructure reused**: the simple-API
  metadata fetch goes through
  :class:`pipenv.resolver.pep691.PEP691Client` +
  :class:`pipenv.resolver.fetcher.ParallelFetcher`, so auth /
  netrc / cert handling stays in one place (the same module already
  vetted for credential leaks under GHSA-8xgg-v3jj-95m2).

Entry point: :func:`prefetch_wheels`.  Called from
:func:`pipenv.routines.install.batch_install` once the dependency
list and source list are finalised; returns the ``--find-links`` dir
or ``None`` if nothing was fetched.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

_LOGGER = logging.getLogger(__name__)
_MAX_WORKERS = 16
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 60.0


def prefetch_wheels(
    project: Any,
    deps: Sequence[Any],
    lockfile_section: dict,
    sources: Sequence[dict],
    *,
    allow_global: bool = False,
    max_workers: int = _MAX_WORKERS,
) -> str | None:
    """Pre-fetch wheels matching the lockfile entries to a temp dir.

    Returns the temp dir path (use as ``--find-links``) on at least one
    success, or ``None`` when nothing was fetched.  Every error path is
    swallowed; the regular pip-install flow takes over for any package
    not in the returned dir.

    Parameters
    ----------
    project:
        Pipenv :class:`Project` — used for the venv's Python interpreter
        (target wheel tags) and the cache layout.
    deps:
        Iterable of ``(InstallRequirement, pip_line)`` tuples (the
        same shape :func:`pipenv.routines.install.batch_install` walks).
    lockfile_section:
        The ``[default]`` / ``[develop]`` section of the lockfile —
        looked up by canonical name to get ``version`` + ``hashes``.
    sources:
        The post-mirror-substitution source list (dicts with ``name``,
        ``url``, ``verify_ssl``).  We try each index in order; first
        successful match wins.
    allow_global:
        Forwarded to :func:`project_python` so ``--system`` installs
        target the global interpreter's tags.
    max_workers:
        Hard cap at 16 — matches urllib3's pool ceiling per the
        existing :class:`ParallelFetcher` contract.
    """
    # Local imports keep the cold-import cost of pipenv unaffected
    # for callers that never hit install/sync.
    try:
        from pipenv.patched.pip._vendor import urllib3
        from pipenv.resolver.fetcher import ParallelFetcher
        from pipenv.resolver.manifest_cache import ParsedManifestCache
        from pipenv.resolver.pep691 import PEP691Client
        from pipenv.utils.shell import project_python
        from pipenv.vendor.packaging.utils import canonicalize_name
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("prefetch_wheels: import failed (%s); skipping", exc)
        return None

    max_workers = min(max_workers, _MAX_WORKERS)
    if max_workers < 1:
        return None

    # Step 1: build the (name, version, expected_hashes) target list
    # from the lockfile.  Skip anything we can't pin by SHA-256 — the
    # hash is the authoritative match key downstream.
    targets: list[tuple[str, str, set[str]]] = []
    for dep, _pip_line in deps:
        raw_name = getattr(dep, "name", None)
        if not raw_name:
            continue
        canonical = canonicalize_name(raw_name)
        entry = lockfile_section.get(raw_name) or lockfile_section.get(canonical)
        if not isinstance(entry, dict):
            continue
        version = (entry.get("version") or "").lstrip("=").strip()
        raw_hashes = entry.get("hashes") or []
        sha256s = {
            h for h in raw_hashes
            if isinstance(h, str) and h.startswith("sha256:")
        }
        if not version or not sha256s:
            continue
        targets.append((canonical, version, sha256s))

    if not targets:
        return None

    index_urls = tuple(s.get("url", "") for s in sources if s.get("url"))
    if not index_urls:
        return None

    # Step 2: get the TARGET Python's wheel tags.  Host and target may
    # disagree (host 3.13 + venv 3.11 is common); the lockfile carries
    # hashes for every platform's wheel so we must filter to "the wheel
    # the target Python would actually install."
    try:
        target_python = project_python(project, system=allow_global)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("prefetch_wheels: project_python lookup failed (%s)", exc)
        return None
    target_tags = _query_target_tags(target_python)
    if target_tags is None:
        # Tag query failed — bail rather than guess and waste downloads.
        return None

    # Step 3: use a requests-compatible session for PEP 691 metadata
    # fetches, because PEP691Client passes per-request verify/cert
    # kwargs that bare urllib3.PoolManager.request() does not accept.
    # Keep urllib3 for wheel downloads so the existing download path
    # remains unchanged.
    cache_dir_holder = tempfile.mkdtemp(prefix="pipenv-prefetch-cache-")
    download_dir = Path(tempfile.mkdtemp(prefix="pipenv-prefetch-"))
    try:
        import requests

        manifest_session = requests.Session()
        manifest_adapter = requests.adapters.HTTPAdapter(
            pool_connections=max_workers,
            pool_maxsize=max_workers,
        )
        manifest_session.mount("http://", manifest_adapter)
        manifest_session.mount("https://", manifest_adapter)

        download_session = urllib3.PoolManager(
            num_pools=max_workers,
            maxsize=max_workers,
        )
        try:
            cache = ParsedManifestCache(Path(cache_dir_holder))
            client = PEP691Client(manifest_session)
            fetcher = ParallelFetcher(client, cache, max_workers=max_workers)

            fetch_targets = [
                (idx, name) for idx in index_urls for name, _, _ in targets
            ]
            fetcher.populate(fetch_targets)

            # Step 4: pick the right wheel per target.  Filter by target
            # tags FIRST (skip incompatible wheels), then match hash
            # against the lockfile.
            download_plan: list[tuple[str, str, str]] = []
            for name, version, expected_hashes in targets:
                picked = _pick_wheel(
                    name, version, expected_hashes, cache, index_urls, target_tags
                )
                if picked is not None:
                    download_plan.append(picked)

            if not download_plan:
                shutil.rmtree(download_dir, ignore_errors=True)
                return None

            # Step 5: parallel download + hash verify.
            successes = 0
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as ex:
                futs = [
                    ex.submit(_download_and_verify, download_session, item, download_dir)
                    for item in download_plan
                ]
                for fut in concurrent.futures.as_completed(futs):
                    ok = _safe_future_result(fut)
                    if ok:
                        successes += 1

            if successes == 0:
                shutil.rmtree(download_dir, ignore_errors=True)
                return None

            _LOGGER.info(
                "Pre-fetched %d/%d wheels in parallel to %s",
                successes,
                len(download_plan),
                download_dir,
            )
            return str(download_dir)
        finally:
            manifest_session.close()
            download_session.clear()
    finally:
        # The manifest cache temp dir is throwaway scratch; the
        # download_dir survives (consumed by pip via --find-links) or
        # has already been cleaned in the no-success branch.
        shutil.rmtree(cache_dir_holder, ignore_errors=True)


def _query_target_tags(target_python: str) -> frozenset[tuple[str, str, str]] | None:
    """Ask the target Python for its compatible wheel tags.

    Returns a frozenset of ``(interpreter, abi, platform)`` tuples on
    success, ``None`` if the subprocess invocation fails for any
    reason (timeout, non-zero exit, parse error).  Tuple form
    sidesteps importing :class:`packaging.tags.Tag` on the host (the
    target Python may not even have packaging installed).
    """
    snippet = (
        "import sys\n"
        "try:\n"
        "    from packaging.tags import sys_tags\n"
        "except ImportError:\n"
        "    try:\n"
        "        from pip._vendor.packaging.tags import sys_tags\n"
        "    except ImportError:\n"
        "        sys.exit(2)\n"
        "for t in sys_tags():\n"
        "    print(f'{t.interpreter}\\t{t.abi}\\t{t.platform}')\n"
    )
    try:
        proc = subprocess.run(
            [target_python, "-c", snippet],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _LOGGER.debug("target-tag subprocess failed: %s", exc)
        return None
    if proc.returncode != 0:
        _LOGGER.debug(
            "target-tag subprocess rc=%d stderr=%s",
            proc.returncode,
            proc.stderr[:200],
        )
        return None
    tags: set[tuple[str, str, str]] = set()
    for line in proc.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 3:
            tags.add(tuple(parts))  # type: ignore[arg-type]
    return frozenset(tags) if tags else None


def _pick_wheel(
    name: str,
    version: str,
    expected_hashes: set[str],
    cache: Any,
    index_urls: Sequence[str],
    target_tags: frozenset[tuple[str, str, str]],
) -> tuple[str, str, str] | None:
    """Choose the wheel to download for ``(name, version)``.

    Returns ``(url, filename, expected_hash)`` on a match, ``None``
    otherwise.  Walks every configured index's cached manifest and
    picks the first wheel that:

    * has ``cand.version == version``,
    * is_wheel and not yanked,
    * has at least one platform-tag in :func:`packaging.tags.sys_tags`
      of the target Python (so pip will accept it as compatible),
    * declares a SHA-256 hash present in the lockfile's hash set.
    """
    for index_url in index_urls:
        manifest = cache.get(index_url, name)
        if manifest is None:
            continue
        for cand in getattr(manifest, "candidates", ()) or ():
            if getattr(cand, "version", None) != version:
                continue
            if not getattr(cand, "is_wheel", False):
                continue
            if getattr(cand, "yanked", False):
                continue
            cand_tags = getattr(cand, "wheel_tags", None) or frozenset()
            cand_tag_triples = {
                (str(t.interpreter), str(t.abi), str(t.platform))
                for t in cand_tags
            }
            if not (cand_tag_triples & target_tags):
                continue
            for h in getattr(cand, "hashes", ()) or ():
                algo = getattr(h, "algo", None)
                value = getattr(h, "value", None)
                if algo != "sha256" or not value:
                    continue
                hash_str = f"{algo}:{value}"
                if hash_str in expected_hashes:
                    return (
                        getattr(cand, "url", ""),
                        getattr(cand, "filename", ""),
                        hash_str,
                    )
    return None


def _safe_future_result(fut: concurrent.futures.Future) -> bool:
    """Read a worker's result without letting the loop crash on raises.

    Worker callables already swallow their own exceptions and return
    ``bool``; this is a final safety net for ``fut.result()`` itself
    raising (cancellation, executor shutdown).
    """
    try:
        return bool(fut.result())
    except Exception as exc:  # noqa: BLE001 — defensive
        _LOGGER.debug("prefetch worker raised: %s", exc)
        return False


def _download_and_verify(
    session: Any,
    item: tuple[str, str, str],
    target_dir: Path,
) -> bool:
    """Download ``item`` and write it to ``target_dir`` on hash match.

    ``item`` is ``(url, filename, expected_hash)``.  Returns ``True`` on
    successful download + hash match + file write, ``False`` on any
    failure path.  All exceptions are caught and logged at DEBUG.
    """
    url, filename, expected_hash = item
    if not url or not filename:
        return False
    try:
        try:
            from pipenv.patched.pip._vendor.urllib3 import Timeout as Urllib3Timeout
            _timeout = Urllib3Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT)
        except ImportError:
            _timeout = (_CONNECT_TIMEOUT, _READ_TIMEOUT)
        response = session.request(
            "GET",
            url,
            timeout=_timeout,
            preload_content=True,
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("prefetch GET %s failed: %s", url, exc)
        return False
    try:
        status = getattr(response, "status", None) or getattr(
            response, "status_code", 0
        )
        if int(status) != 200:
            _LOGGER.debug("prefetch GET %s returned HTTP %s", url, status)
            return False
        data = getattr(response, "data", None)
        if data is None:
            data = getattr(response, "content", None)
        if data is None:
            return False
        body = bytes(data)
        actual_hash = f"sha256:{hashlib.sha256(body).hexdigest()}"
        if actual_hash != expected_hash:
            _LOGGER.debug(
                "prefetch hash mismatch for %s: got %s, expected %s",
                filename,
                actual_hash,
                expected_hash,
            )
            return False
        # Sanitise filename — defensive against an index returning a
        # filename containing path separators.
        safe_name = Path(filename).name
        if not safe_name or safe_name in (".", ".."):
            return False
        (target_dir / safe_name).write_bytes(body)
        return True
    finally:
        release = getattr(response, "release_conn", None)
        if callable(release):
            try:
                release()
            except Exception:  # noqa: BLE001
                pass
