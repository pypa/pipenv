The CI package-manager benchmark now runs once per resolver backend
(``pip`` and ``pure-python``).  ``benchmarks/benchmark.py`` accepts
``--backend``, which selects the backend through ``[pipenv]
resolver_backend`` in the benchmark Pipfile.
