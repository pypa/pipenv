Pipfile name recasing is now opt-in via ``[pipenv] package_name_case``.
Previously, every ``pipenv install`` walked ``packages`` /
``dev-packages`` and made one synchronous PyPI HTTP request per unknown
package name to learn its display capitalization, then rewrote the
Pipfile entry to match.  On a fresh ``install -r requirements.txt`` of
~100 packages this added roughly 3 seconds of sequential network
latency on top of the resolve, regardless of cache state.

The new ``package_name_case`` setting accepts:

* (unset) / ``"off"`` — default; package names you wrote into your
  Pipfile are preserved as-is.  PEP 503 normalization still governs
  resolution, so behavior is unchanged for matching purposes.
* ``"canonical"`` — apply PEP 503 normalization
  (``packaging.utils.canonicalize_name``) to every entry; fully offline.
* ``"pypi"`` — restore the prior behavior, fetching display
  capitalization from PyPI per name.

The toggle lives in the Pipfile rather than in an environment variable
so every contributor on the project gets the same behaviour and
``pipenv install`` does not bounce the Pipfile back and forth between
commits when teammates have different shell defaults.
