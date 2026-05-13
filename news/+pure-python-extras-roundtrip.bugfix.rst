The pure-Python resolver backend (``[pipenv] resolver_backend =
"pure-python"``) now correctly threads extras
(``pkg[extra1,extra2]``) through the resolver pipeline so
marker-gated transitive dependencies appear in the lockfile.  For
example, ``psycopg[binary]`` now pulls ``psycopg-binary`` as a
locked transitive (it didn't before, because the wire-shape parser
dropped the extras section before the resolver ever saw it).

Five round-trip points were updated together so the bench fixture
keeps converging while T_PARITY_REAL hits 10/10 parity with pip:

* ``PurePythonBackend._spec_value_to_pipfile_entry`` parses the
  ``[extras]`` segment of a wire-shape pip-install line and
  surfaces it via the dict-form Pipfile-entry shape that
  ``Requirement.from_pipfile_entry`` already accepts.

* ``PurePythonProvider.find_matches`` clones the filtered candidate
  set with ``extras=identifier_extras`` so T7's
  ``get_dependencies`` sees the right ``parent_extras`` context
  when iterating ``Requires-Dist`` lines.

* ``PurePythonProvider.get_dependencies`` strips the
  ``extra == X`` clauses from a transitive's runtime marker via a
  new ``_strip_extra_clauses`` helper.  The extras-gating role was
  already consumed at emission time; carrying the clause onto
  ``Requirement.marker`` made every candidate fail the runtime
  marker re-evaluation.  ``introducing_marker`` keeps the original
  for the lockfile emitter.

* ``PurePythonProvider.get_dependencies`` also emits a synthetic
  base-version requirement when the parent candidate carries
  extras — pins the bare ``(name, frozenset())`` identifier to the
  exact version of the extras-flavoured candidate.  Mirrors pip's
  ``ExtrasCandidate.iter_dependencies`` shape and prevents the
  bare and extras identifier streams from diverging.

* ``PurePythonProvider`` now implements
  ``narrow_requirement_selection`` (mirroring pip's
  ``PipProvider.narrow_requirement_selection``) plus a promote-to-
  front polarity flip on ``get_preference``'s leading slot.  The
  wider transitive constraint graph that extras propagation
  surfaces (overlapping upper bounds on protobuf / grpcio /
  grpcio-status from the sentry-protos + google-cloud-* fleet)
  needed pip-style conflict tracking to converge — without it the
  sentry-base bench fixture thrashed indefinitely.  The bench now
  completes in ~40 s (down from ~2 min baseline) with
  byte-identical hash to the pip backend.

T_PARITY_REAL hits **10/10 byte-identical parity** with the pip
backend across the design's wheel-heavy combos
(``django+psycopg[binary]``, ``flask+gunicorn``,
``fastapi+uvicorn``, ``requests+httpx``, ``pandas+numpy``,
``pytest+pytest-cov``, ``sqlalchemy+alembic``,
``cryptography+pyopenssl``, ``boto3+botocore``, ``click+rich``).
