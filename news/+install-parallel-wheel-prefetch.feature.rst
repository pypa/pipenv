``pipenv install`` and ``pipenv sync`` now pre-fetch wheels in
parallel from the configured indexes BEFORE invoking ``pip install``,
populating a ``--find-links`` directory pip then reads from.  Pip's
own install step is sequential, so on a cold pip cache the network
download phase dominates wall time — the sentry-base benchmark's
151 wheels spent ~12 s of pure-network time in pip's subprocess
before this change.  Pre-fetching uses the resolver's existing
PEP 691 client + ``ParallelFetcher`` (urllib3 connection-pool capped
at 16 workers, mirroring the established resolver concurrency
contract) and verifies every downloaded body's SHA-256 against the
lockfile's pinned hashes before exposing it to pip.

The pre-fetch is best-effort: any per-package failure (missing
target-platform wheel, hash mismatch, network hiccup) falls through
silently and pip downloads that package via the index as usual.
The shortcut only fires when the install is driven from a
hash-pinned lockfile (i.e. ``pipenv sync`` or ``pipenv install``
without ``--skip-lock``); unpinned installs keep the legacy
behaviour.

Bench impact on the sentry-base fixture (Python 3.11 venv,
151 wheels, cold pip cache):

* Cold install:  ~34 s  →  ~23 s  (~32 % faster, locally)
* Warm install:  ~19 s  →  ~16 s  (-3 s — pip's ``--find-links``
  read path is cheaper than its HTTP-cache lookup, so warm-cache
  installs benefit too).
