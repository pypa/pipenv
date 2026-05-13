The pure-Python resolver backend (``[pipenv] resolver_backend =
"pure-python"``) now builds sdists inside a PEP 517 isolated env via
the PyPA :pypi:`build` library.  Previously the sdist METADATA hook
ran in pipenv's own interpreter, which crashed on import for any
package whose declared ``[build-system].build-backend`` (e.g.
``poetry-core``, ``hatchling``, ``flit-core``) wasn't already
installed.  ``build`` is now a runtime dependency so the resolver can
spin up a throwaway venv, install the project's
``[build-system].requires`` plus any ``get_requires_for_build_wheel``
extras, then invoke the backend's
``prepare_metadata_for_build_wheel`` hook against that env.  Vendoring
:pypi:`build` is the longer-term plan; the runtime dep is the
shortest path to making the pure-Python backend actually usable on
real-world Pipfiles.
