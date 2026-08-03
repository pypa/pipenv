Add a pure-Python PEP 691 / PEP 503 simple-API client + parsed-manifest
cache + parallel fetcher under ``pipenv/resolver/``.  Initiative G
phase 1 ships the standalone surface; no integration yet.  Phase 2
(cache-prime bridge) and Phase 3 (full backend) will wire it in.
``pipenv lock --clear`` and ``pipenv install --clear`` now invalidate
this parsed-manifest cache in addition to pip's HTTP cache.
