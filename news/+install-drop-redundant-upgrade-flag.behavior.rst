``pip install`` invocations driven by ``pipenv sync`` no longer
pass ``--upgrade``.  The flag was hardcoded ``True`` historically as
a safety net to force a re-install when a package was already
present at a different version, but with ``--no-deps`` (always set
for sync) plus explicit ``pkg==X.Y.Z`` lines and the upstream
``Environment.is_satisfied`` filter that already runs before the
batch is handed to pip, ``--upgrade`` is redundant — it forces pip
to do a per-package metadata check that costs measurable wall time
when the lockfile has many entries.  ``pipenv install``
(Pipfile-driven, may need to downgrade) still passes ``--upgrade``.
