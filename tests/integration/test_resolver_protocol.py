"""Integration test pinning the JSON wire-shape of the resolver subprocess
protocol (T_F.3 task C2).

Runs an actual ``pipenv lock`` against a tiny committed Pipfile, captures
the ``--request-file`` and ``--response-file`` tempfile contents that the
parent and subprocess produce, normalises non-deterministic fields, and
compares against committed golden JSON fixtures under
``tests/integration/fixtures/resolver_protocol/``.

Capture strategy
----------------
``pipenv lock`` is invoked via :func:`subprocess.run`, so we cannot
monkey-patch ``tempfile.NamedTemporaryFile`` in-process to redirect the
resolver's tempfiles.  Instead we set ``TMPDIR`` to a dedicated empty
directory and rely on the fact that the parent creates these tempfiles
with the distinctive prefixes ``pipenv-request-`` and
``pipenv-response-`` (see ``pipenv/utils/resolver.py
:: _run_resolver_subprocess``) and never deletes them.  After the lock
returns we glob for those files and parse them.

Fixture regeneration
--------------------
To regenerate the goldens after a deliberate schema change::

    PIPENV_REGEN_PROTOCOL_FIXTURES=1 \\
        pytest tests/integration/test_resolver_protocol.py -v

The test writes the captured (and normalised) JSON back to the golden
files and skips.  Review the resulting ``git diff`` on
``tests/integration/fixtures/resolver_protocol/`` before committing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "resolver_protocol"
GOLDEN_REQUEST = GOLDEN_DIR / "request.json"
GOLDEN_RESPONSE = GOLDEN_DIR / "response.json"

REGEN_ENV_VAR = "PIPENV_REGEN_PROTOCOL_FIXTURES"


# Pipfile used by the protocol smoke.  Two pure-Python pinned packages
# from public PyPI exercise the representative wire-shape surface
# without dragging in transitive deps that would inflate the golden
# response:
#
#   * ``pytz`` — plain release with a version pin (no transitive deps)
#   * ``six``  — second plain release; pins the multi-entry ordering
#                (``specs`` keys are sorted by ``to_json_dict``)
#
# ``[dev-packages]`` is intentionally empty so we lock the ``packages``
# category alone and the golden response stays minimal and stable.
# Versions are pinned to long-archived releases so the goldens do not
# drift when upstream cuts a new release.
_PIPFILE_TEMPLATE = """\
[[source]]
url = "{index_url}"
verify_ssl = true
name = "pypi"

[packages]
pytz = "==2024.1"
six = "==1.16.0"

[dev-packages]
"""


def _normalize_request(payload: dict) -> dict:
    """Strip non-deterministic fields from a captured request.

    Mutations:

    * ``metadata.parent_pid`` is the parent pipenv process pid; varies
      run-to-run.  Replaced with a sentinel.
    * ``metadata.pipenv_version`` may be empty (uninstalled dev tree) or
      a real version string; replaced with a sentinel so the test passes
      on both a packaged install and a working-tree checkout.
    * ``sources[*].url`` is the public-PyPI URL (``https://pypi.org/simple``),
      which is stable.  No URL normalisation required.
    """
    out = json.loads(json.dumps(payload))  # deep copy
    meta = out.get("metadata")
    if isinstance(meta, dict):
        if "parent_pid" in meta:
            meta["parent_pid"] = 0
        if "pipenv_version" in meta:
            meta["pipenv_version"] = "<redacted>"
    return out


def _normalize_response(payload: dict) -> dict:
    """Strip non-deterministic fields from a captured response.

    Mutations:

    * On a ``success`` result the resolver emits ``locked`` entries in
      pip's own resolution order, which is *not* deterministic
      run-to-run (it depends on the order packages were fetched / the
      resolver's internal queue).  Sort by name so the golden is stable.
    * ``ResolverResponse`` carries no parent_pid or timestamp fields, so
      no other normalisation is required today.  Future schema
      additions that introduce non-determinism (a trace id, a timing
      block) should add their normalisation rules here.
    """
    out = json.loads(json.dumps(payload))  # deep copy
    result = out.get("result")
    if isinstance(result, dict) and result.get("kind") == "success":
        locked = result.get("locked")
        if isinstance(locked, list):
            result["locked"] = sorted(
                locked, key=lambda entry: entry.get("name", "")
            )
    return out


def _find_unique(tmpdir: Path, prefix: str) -> Path:
    """Return the single file under ``tmpdir`` whose name starts with
    ``prefix``.  Raises if zero or multiple matches exist (the test
    cannot disambiguate)."""
    matches = sorted(tmpdir.glob(f"{prefix}*.json"))
    if not matches:
        raise AssertionError(
            f"No file matching {prefix}*.json found under {tmpdir}. "
            f"Contents: {sorted(p.name for p in tmpdir.iterdir())}"
        )
    if len(matches) > 1:
        # Pick the latest by mtime — the resolver may run multiple times
        # within one ``pipenv lock`` (once per category).  We pin the
        # ``[packages]``-only case so usually there is exactly one match;
        # take the most recent if multiple appear.
        matches.sort(key=lambda p: p.stat().st_mtime)
    return matches[-1]


@pytest.mark.lock
@pytest.mark.needs_internet
def test_resolver_protocol_lock_smoke(
    pipenv_instance_pypi, tmp_path, monkeypatch
):
    """Lock a small Pipfile and compare the captured request/response
    JSON against the committed goldens (or regenerate them under
    ``PIPENV_REGEN_PROTOCOL_FIXTURES=1``).
    """
    capture_dir = tmp_path / "resolver_protocol_capture"
    capture_dir.mkdir()
    # ``tempfile`` honours ``TMPDIR`` (POSIX) / ``TEMP`` / ``TMP``
    # (Windows).  Setting all three covers both worlds via env
    # inheritance through ``subprocess.run``.
    monkeypatch.setenv("TMPDIR", str(capture_dir))
    monkeypatch.setenv("TEMP", str(capture_dir))
    monkeypatch.setenv("TMP", str(capture_dir))

    with pipenv_instance_pypi() as p:
        p.pipfile_path.write_text(_PIPFILE_TEMPLATE.format(index_url=p.index_url))
        c = p.pipenv("lock")
        assert c.returncode == 0, (
            f"pipenv lock failed: stdout={c.stdout!r} stderr={c.stderr!r}"
        )

    request_path = _find_unique(capture_dir, "pipenv-request-")
    response_path = _find_unique(capture_dir, "pipenv-response-")

    actual_request = _normalize_request(json.loads(request_path.read_text()))
    actual_response = _normalize_response(json.loads(response_path.read_text()))

    if os.environ.get(REGEN_ENV_VAR):
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        GOLDEN_REQUEST.write_text(
            json.dumps(actual_request, indent=2, sort_keys=True) + "\n"
        )
        GOLDEN_RESPONSE.write_text(
            json.dumps(actual_response, indent=2, sort_keys=True) + "\n"
        )
        pytest.skip(
            f"Fixtures regenerated under {GOLDEN_DIR}; rerun without "
            f"{REGEN_ENV_VAR} set to assert against them."
        )

    expected_request = json.loads(GOLDEN_REQUEST.read_text())
    expected_response = json.loads(GOLDEN_RESPONSE.read_text())

    assert actual_request == expected_request, (
        "Resolver request JSON drift.  If this is an intentional schema "
        "change, regenerate the golden via "
        f"{REGEN_ENV_VAR}=1 pytest {Path(__file__).name} and review the "
        "diff before committing."
    )
    assert actual_response == expected_response, (
        "Resolver response JSON drift.  If this is an intentional schema "
        "change, regenerate the golden via "
        f"{REGEN_ENV_VAR}=1 pytest {Path(__file__).name} and review the "
        "diff before committing."
    )
