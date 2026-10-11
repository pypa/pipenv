The pure-Python resolver backend no longer crashes with ``'frozenset' object
has no attribute 'get'`` when it has to build an sdist for metadata.  The
SHA-256 check on the downloaded sdist now reads the candidate's hashes in
the shape the simple-API parsers produce, so the check actually runs.
