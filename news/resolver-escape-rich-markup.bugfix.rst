Escape Rich markup in pip's stdout/stderr when printing ``Locking Failed!`` and ``pipenv graph`` errors, so bracketed text such as ``requests[security]`` is no longer swallowed or misparsed.
