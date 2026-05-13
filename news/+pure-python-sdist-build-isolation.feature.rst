The pure-Python resolver backend (``[pipenv] resolver_backend =
"pure-python"``) now builds sdists inside a PEP 517 isolated env via
the (newly-vendored) PyPA :pypi:`build` library.  Previously the
sdist METADATA hook ran in pipenv's own interpreter, which crashed
on import for any package whose declared
``[build-system].build-backend`` (e.g. ``poetry-core``,
``hatchling``, ``flit-core``) wasn't already installed.  The
resolver now spins up a throwaway venv per build, installs the
project's ``[build-system].requires`` plus any
``get_requires_for_build("wheel")`` extras, then invokes the
backend's ``prepare_metadata_for_build_wheel`` hook against that
env.  :pypi:`build` lives at ``pipenv/vendor/build`` so the
resolver subprocess can import it from the project venv's Python
without an extra runtime dep.
