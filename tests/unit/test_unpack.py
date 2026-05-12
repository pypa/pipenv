"""Tests for :mod:`pipenv.utils.unpack` (T_E.4).

These tests pin the public shape of the pip-internal-fork pair
(:func:`unpack_url`, :func:`get_http_url`) at its new home, and the
load-bearing behavioural divergence from upstream pip that motivated
keeping the forks in-tree.

Provenance: the two functions were moved verbatim out of
``pipenv/utils/requirementslib.py`` under T_E.4 (see
``docs/dev/initiative-e-design.md`` §T_E.4).

Behavioural divergence from upstream pip that these tests pin:

* :func:`unpack_url` returns ``File(location, content_type=None)`` for
  VCS links (pip's version returns ``None``). The sole caller
  (:func:`pipenv.utils.dependencies.determine_package_name`) relies on
  this to do ``local_file.path`` access without an ``AttributeError``.
* :func:`get_http_url` constructs its ``TempDirectory`` with
  ``globally_managed=False`` (pip uses ``True``). The caller already
  owns the temp-dir lifetime via its own ``with TemporaryDirectory()``
  block, so the global registry is the wrong lifetime here.
"""

from unittest.mock import MagicMock, patch

from pipenv.patched.pip._internal.operations.prepare import File


# ---------------------------------------------------------------------------
# Import-shape pins -- the move is the test for relocations.
# ---------------------------------------------------------------------------


def test_unpack_url_importable_from_new_location():
    """``unpack_url`` lives at ``pipenv.utils.unpack`` after T_E.4."""
    from pipenv.utils.unpack import unpack_url

    assert callable(unpack_url)


def test_get_http_url_importable_from_new_location():
    """``get_http_url`` lives at ``pipenv.utils.unpack`` after T_E.4."""
    from pipenv.utils.unpack import get_http_url

    assert callable(get_http_url)


def test_vcs_schemes_set_present_on_unpack_module():
    """The local ``VCS_SCHEMES`` set travels with the unpack pair (the
    fork's VCS-link detection uses it directly -- see ``unpack_url``).
    It is a set (not a list, unlike the cross-module ``VCS_SCHEMES``
    list in ``pipenv.utils.constants``) and contains the bare ``git``
    scheme, which is the load-bearing divergence from the constants
    list.
    """
    from pipenv.utils.unpack import VCS_SCHEMES

    assert isinstance(VCS_SCHEMES, set)
    # Bare-scheme entries (no ``+transport``) are in this set but NOT in
    # ``pipenv.utils.constants.VCS_SCHEMES`` -- this distinction is what
    # makes the set local to ``unpack_url``.
    assert "git" in VCS_SCHEMES
    assert "hg" in VCS_SCHEMES
    assert "svn" in VCS_SCHEMES
    assert "bzr" in VCS_SCHEMES
    # Spot-check the ``+transport`` variants too.
    assert "git+https" in VCS_SCHEMES
    assert "hg+ssh" in VCS_SCHEMES


def test_legacy_requirementslib_module_is_gone():
    """``pipenv.utils.requirementslib`` no longer exists after T_E.4.
    All symbols moved to either ``pipenv.utils.dependencies`` (T_E.3) or
    ``pipenv.utils.unpack`` (T_E.4).
    """
    import importlib

    try:
        importlib.import_module("pipenv.utils.requirementslib")
    except ModuleNotFoundError:
        return
    raise AssertionError(
        "pipenv.utils.requirementslib should be deleted after T_E.4"
    )


def test_dependencies_imports_unpack_url_from_new_location():
    """The sole caller of ``unpack_url`` — ``determine_package_name`` in
    ``pipenv.utils.dependencies`` — must source the symbol from the
    new module after T_E.4.

    As of the phase-5 startup-perf work, ``unpack_url`` is imported
    *inside* ``determine_package_name`` rather than at module top
    (``pipenv.utils.unpack`` transitively pulls in pip's network
    machinery; the eager import was ~26 ms cumulative on every
    ``pipenv`` invocation).  We verify the wiring by inspecting the
    function source for the import path, plus a behavioural smoke
    that the symbol is callable at the documented location.
    """
    import inspect

    from pipenv.utils import dependencies, unpack

    src = inspect.getsource(dependencies.determine_package_name)
    assert "from pipenv.utils.unpack import unpack_url" in src
    assert callable(unpack.unpack_url)


# ---------------------------------------------------------------------------
# Behavioural smoke -- VCS-link divergence in ``unpack_url``.
# ---------------------------------------------------------------------------


def test_unpack_url_vcs_link_returns_file_not_none():
    """Load-bearing divergence: for VCS links, our fork returns
    ``File(location, content_type=None)`` -- pip's version returns
    ``None``. The caller (`determine_package_name`) does an unguarded
    ``local_file.path`` access, so ``None`` would ``AttributeError``.
    """
    from pipenv.utils.unpack import unpack_url

    # Build a minimal mock Link whose scheme is in VCS_SCHEMES.
    link = MagicMock()
    link.scheme = "git+https"

    with patch("pipenv.utils.unpack.unpack_vcs_link") as mock_unpack_vcs:
        result = unpack_url(
            link=link,
            location="/tmp/pipenv-test-unpack-loc",
            download=MagicMock(),
            verbosity=0,
        )

    mock_unpack_vcs.assert_called_once_with(
        link, "/tmp/pipenv-test-unpack-loc", verbosity=0
    )
    assert isinstance(result, File)
    assert result.path == "/tmp/pipenv-test-unpack-loc"
    assert result.content_type is None


def test_unpack_url_bare_git_scheme_treated_as_vcs():
    """The local ``VCS_SCHEMES`` set includes bare ``git`` (no
    ``+transport``); pip's ``is_vcs`` property would also classify
    this, but the test pins our explicit-set behaviour so future
    refactors that swap to ``link.is_vcs`` don't silently regress.
    """
    from pipenv.utils.unpack import unpack_url

    link = MagicMock()
    link.scheme = "git"

    with patch("pipenv.utils.unpack.unpack_vcs_link") as mock_unpack_vcs:
        result = unpack_url(
            link=link,
            location="/tmp/pipenv-test-bare-git",
            download=MagicMock(),
            verbosity=2,
        )

    mock_unpack_vcs.assert_called_once()
    assert isinstance(result, File)
    assert result.content_type is None


# ---------------------------------------------------------------------------
# Behavioural smoke -- ``globally_managed=False`` divergence.
# ---------------------------------------------------------------------------


def test_get_http_url_constructs_tempdir_with_globally_managed_false():
    """Load-bearing divergence: ``get_http_url`` builds its
    ``TempDirectory`` with ``globally_managed=False`` because the caller
    (``determine_package_name``) already owns the temp-dir lifetime via
    its own ``with TemporaryDirectory()`` block. Pip's upstream copy
    uses ``True``.
    """
    from pipenv.utils.unpack import get_http_url

    link = MagicMock()
    download = MagicMock(return_value=("/tmp/downloaded-file", "application/zip"))

    with patch("pipenv.utils.unpack.TempDirectory") as mock_temp_dir_cls:
        mock_temp_dir_cls.return_value.path = "/tmp/pipenv-temp-unpack-xyz"
        result = get_http_url(link=link, download=download)

    # The constructor call records the divergence we care about.
    mock_temp_dir_cls.assert_called_once_with(
        kind="unpack", globally_managed=False
    )
    # And the result is a ``File`` built from the downloaded path.
    assert isinstance(result, File)
    assert result.path == "/tmp/downloaded-file"
    assert result.content_type == "application/zip"
