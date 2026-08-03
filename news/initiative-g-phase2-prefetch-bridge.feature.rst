Add ``[pipenv] prefetch_index_manifests`` opt-in setting (also
``PIPENV_PREFETCH_INDEX_MANIFESTS=1``) that pre-fetches simple-API
index pages for top-level Pipfile packages in parallel before the
resolver runs.  Most beneficial on cold caches or slow networks;
off-by-default because warm-cache dev machines see neutral-to-
slightly-slower behaviour.  Initiative G phase 2.
