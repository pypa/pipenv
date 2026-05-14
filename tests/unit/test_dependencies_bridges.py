"""Pinning tests for Pipfile/lockfile bridge functions moved under T_E.2,
plus the four predicate/helper symbols moved under T_E.3.

T_E.2 moved seven symbols from :mod:`pipenv.utils.requirements` into
:mod:`pipenv.utils.dependencies` (per the T_E.1 design + sign-off).

T_E.3 moves four more symbols from :mod:`pipenv.utils.requirementslib`
into :mod:`pipenv.utils.dependencies` (its canonical home):
``is_vcs``, ``add_ssh_scheme_to_git_uri``, ``merge_items``, and
``get_pip_command``. The old import paths are intentionally NOT
preserved — per the T_C.3 §9 / T_E.1 sign-off there is no
backwards-compat shim.

Coverage focus:
- import-shape: each moved symbol is importable from the new location.
- ``add_index_to_pipfile_with_trust_check`` rename resolves at the new
  location (and the old name no longer exists at the source).
- ``BAD_PACKAGES`` is the same tuple at the new location.
- light behaviour pinning for the lockfile/Pipfile bridges that have
  pure-function code paths.
- light behaviour pinning for the four T_E.3 helpers.
"""

from unittest.mock import MagicMock


def test_import_requirements_importable_from_dependencies():
    from pipenv.utils.dependencies import import_requirements

    assert callable(import_requirements)


def test_add_index_to_pipfile_with_trust_check_importable_from_dependencies():
    from pipenv.utils.dependencies import add_index_to_pipfile_with_trust_check

    assert callable(add_index_to_pipfile_with_trust_check)


def test_requirement_from_lockfile_importable_from_dependencies():
    from pipenv.utils.dependencies import requirement_from_lockfile

    assert callable(requirement_from_lockfile)


def test_requirements_from_lockfile_importable_from_dependencies():
    from pipenv.utils.dependencies import requirements_from_lockfile

    assert callable(requirements_from_lockfile)


def test_requirement_from_pipfile_importable_from_dependencies():
    from pipenv.utils.dependencies import requirement_from_pipfile

    assert callable(requirement_from_pipfile)


def test_requirements_from_pipfile_importable_from_dependencies():
    from pipenv.utils.dependencies import requirements_from_pipfile

    assert callable(requirements_from_pipfile)


def test_bad_packages_importable_from_dependencies():
    from pipenv.utils.dependencies import BAD_PACKAGES

    assert isinstance(BAD_PACKAGES, tuple)
    # Pinned constant: this set is the canonical pip/setuptools exclusion list
    # used by graph/clean/uninstall routines.
    assert "pip" in BAD_PACKAGES
    assert "setuptools" in BAD_PACKAGES
    assert "wheel" in BAD_PACKAGES
    assert "pkg-resources" in BAD_PACKAGES
    assert "distribute" in BAD_PACKAGES


def test_old_add_index_to_pipfile_name_is_gone_from_source():
    """The module-level ``add_index_to_pipfile`` was renamed to
    ``add_index_to_pipfile_with_trust_check`` per T_E.1 §3 sign-off
    (disambiguates from ``Project.add_index_to_pipfile``)."""
    import pipenv.utils.dependencies as deps

    assert not hasattr(deps, "add_index_to_pipfile")
    assert hasattr(deps, "add_index_to_pipfile_with_trust_check")


def test_old_requirements_module_no_longer_exports_moved_symbols():
    """Per the T_C.3 §9 / T_E.1 sign-off, the old import paths fail
    immediately after T_E.2; no backwards-compat shim is shipped."""
    import pipenv.utils.requirements as old_mod

    for name in (
        "import_requirements",
        "add_index_to_pipfile",
        "add_index_to_pipfile_with_trust_check",
        "requirement_from_lockfile",
        "requirements_from_lockfile",
        "requirement_from_pipfile",
        "requirements_from_pipfile",
        "BAD_PACKAGES",
    ):
        assert not hasattr(old_mod, name), (
            f"{name} should no longer exist on pipenv.utils.requirements"
        )


def test_requirement_from_lockfile_string_spec_returns_pinned():
    """String specs become ``name==value`` for non-star versions.

    Pins the as-is behaviour: the string is unconditionally prefixed with
    ``==``. This includes the edge case where the caller passes a string
    already starting with ``==``, which yields a doubled operator. The
    move is behaviour-preserving; any cleanup of the doubled-operator
    edge case is a separate concern.
    """
    from pipenv.utils.dependencies import requirement_from_lockfile

    assert requirement_from_lockfile("requests", "2.31.0") == "requests==2.31.0"


def test_requirement_from_lockfile_star_returns_bare_name():
    from pipenv.utils.dependencies import requirement_from_lockfile

    assert requirement_from_lockfile("requests", "*") == "requests"


def test_requirement_from_lockfile_dict_with_version():
    from pipenv.utils.dependencies import requirement_from_lockfile

    line = requirement_from_lockfile(
        "requests",
        {"version": "==2.31.0"},
        include_hashes=False,
        include_markers=False,
    )
    assert line == "requests==2.31.0"


def test_requirement_from_lockfile_skips_star_version_in_dict():
    """Wildcard versions in dict form should not appear in the output."""
    from pipenv.utils.dependencies import requirement_from_lockfile

    line = requirement_from_lockfile(
        "requests",
        {"version": "*"},
        include_hashes=False,
        include_markers=False,
    )
    assert line == "requests"


def test_requirements_from_lockfile_returns_list():
    from pipenv.utils.dependencies import requirements_from_lockfile

    deps = {"requests": {"version": "==2.31.0"}}
    lines = requirements_from_lockfile(deps, include_hashes=False, include_markers=False)
    assert lines == ["requests==2.31.0"]


def test_requirement_from_pipfile_star_returns_bare_name():
    from pipenv.utils.dependencies import requirement_from_pipfile

    assert requirement_from_pipfile("requests", "*") == "requests"


def test_requirement_from_pipfile_string_spec_with_operator():
    from pipenv.utils.dependencies import requirement_from_pipfile

    assert requirement_from_pipfile("requests", ">=2.0") == "requests>=2.0"


def test_requirement_from_pipfile_string_spec_without_operator():
    """Bare version strings get an implicit ``==``."""
    from pipenv.utils.dependencies import requirement_from_pipfile

    assert requirement_from_pipfile("requests", "2.31.0") == "requests==2.31.0"


def test_requirement_from_pipfile_dict_version():
    from pipenv.utils.dependencies import requirement_from_pipfile

    line = requirement_from_pipfile(
        "requests", {"version": ">=2.0"}, include_markers=False
    )
    assert line == "requests>=2.0"


def test_requirements_from_pipfile_returns_list():
    from pipenv.utils.dependencies import requirements_from_pipfile

    deps = {"requests": "*", "flask": ">=2.0"}
    lines = requirements_from_pipfile(deps, include_markers=False)
    assert set(lines) == {"requests", "flask>=2.0"}


def test_add_index_to_pipfile_with_trust_check_marks_trusted_host_as_http_ok():
    """A host in the trusted-hosts list does NOT require HTTPS — pinned
    behaviour from the original module-level function. The downstream
    ``project.sources.add_index_to_pipfile`` is invoked with
    ``verify_ssl=False`` when the host is trusted."""
    from pipenv.utils.dependencies import add_index_to_pipfile_with_trust_check

    project = MagicMock()
    project.sources.add_index_to_pipfile.return_value = "my-index"

    name = add_index_to_pipfile_with_trust_check(
        project,
        "http://internal.example.com/simple",
        trusted_hosts=["internal.example.com"],
    )

    assert name == "my-index"
    project.sources.add_index_to_pipfile.assert_called_once_with(
        "http://internal.example.com/simple", verify_ssl=False
    )


def test_add_index_to_pipfile_with_trust_check_requires_https_for_untrusted():
    """A host NOT in the trusted-hosts list requires HTTPS verification."""
    from pipenv.utils.dependencies import add_index_to_pipfile_with_trust_check

    project = MagicMock()
    project.sources.add_index_to_pipfile.return_value = "pypi-mirror"

    name = add_index_to_pipfile_with_trust_check(
        project,
        "https://mirror.example.com/simple",
        trusted_hosts=["some-other-host.example.com"],
    )

    assert name == "pypi-mirror"
    project.sources.add_index_to_pipfile.assert_called_once_with(
        "https://mirror.example.com/simple", verify_ssl=True
    )


# ---------------------------------------------------------------------------
# T_E.3: predicate + helper symbols moved from requirementslib.py
# ---------------------------------------------------------------------------


def test_is_vcs_importable_from_dependencies():
    from pipenv.utils.dependencies import is_vcs

    assert callable(is_vcs)


def test_add_ssh_scheme_to_git_uri_importable_from_dependencies():
    from pipenv.utils.dependencies import add_ssh_scheme_to_git_uri

    assert callable(add_ssh_scheme_to_git_uri)


def test_merge_items_importable_from_dependencies():
    from pipenv.utils.dependencies import merge_items

    assert callable(merge_items)


def test_get_pip_command_importable_from_dependencies():
    from pipenv.utils.dependencies import get_pip_command

    assert callable(get_pip_command)


def test_old_requirementslib_module_no_longer_exports_moved_symbols():
    """Per the T_C.3 §9 / T_E.1 sign-off, the old import paths fail
    immediately after T_E.3; no backwards-compat shim is shipped.

    Under T_E.4 the whole ``pipenv.utils.requirementslib`` module was
    deleted (its last two symbols -- ``unpack_url``/``get_http_url`` --
    moved to :mod:`pipenv.utils.unpack`), so this test now pins the
    strictly stronger property that the module itself is gone. The
    T_E.3-era symbol-by-symbol check is implied by module non-existence.
    """
    import importlib

    try:
        importlib.import_module("pipenv.utils.requirementslib")
    except ModuleNotFoundError:
        return
    raise AssertionError(
        "pipenv.utils.requirementslib should be deleted after T_E.4"
    )


def test_is_vcs_detects_mapping_with_git_key():
    """A Pipfile entry dict carrying a ``git`` key is a VCS entry."""
    from pipenv.utils.dependencies import is_vcs

    assert is_vcs({"git": "https://github.com/pypa/pipenv.git"}) is True
    assert is_vcs({"hg": "https://example.com/repo"}) is True
    assert is_vcs({"version": "*"}) is False


def test_is_vcs_detects_git_plus_ssh_string():
    """String entries starting with ``git+`` are recognised even
    when they lack a scheme delimiter — they get the ssh scheme
    auto-added before urlsplit. Pins the round-trip with
    ``add_ssh_scheme_to_git_uri``.
    """
    from pipenv.utils.dependencies import is_vcs

    assert is_vcs("git+ssh://git@github.com/pypa/pipenv.git") is True
    # bare git+user@host style — exercises add_ssh_scheme_to_git_uri
    assert is_vcs("git+git@github.com:pypa/pipenv.git") is True
    # plain http URL is not VCS
    assert is_vcs("https://example.com/pkg.tar.gz") is False
    # non-string, non-mapping returns False
    assert is_vcs(42) is False


def test_add_ssh_scheme_to_git_uri_rewrites_bare_git_uri():
    """``git+user@host:path`` is rewritten to ``git+ssh://user@host/path``
    so that pip's URL parser can handle it."""
    from pipenv.utils.dependencies import add_ssh_scheme_to_git_uri

    out = add_ssh_scheme_to_git_uri("git+git@github.com:pypa/pipenv.git")
    assert out == "git+ssh://git@github.com/pypa/pipenv.git"

    # Already-schemed URIs pass through unchanged.
    schemed = "git+https://github.com/pypa/pipenv.git"
    assert add_ssh_scheme_to_git_uri(schemed) == schemed

    # Non-string input passes through unchanged.
    assert add_ssh_scheme_to_git_uri(None) is None


def test_merge_items_recursive_last_write_wins():
    """``merge_items`` recursively merges dicts with last-write-wins
    semantics. Pins the contract used by ``locking.get_deps``."""
    from pipenv.utils.dependencies import merge_items

    a = {"pkg-a": {"version": "==1.0"}, "shared": {"version": "==1.0"}}
    b = {"pkg-b": {"version": "==2.0"}, "shared": {"version": "==2.0"}}
    result = merge_items([a, b])
    assert result == {
        "pkg-a": {"version": "==1.0"},
        "pkg-b": {"version": "==2.0"},
        "shared": {"version": "==2.0"},
    }

    # Empty list returns None (the boltons-era contract).
    assert merge_items([]) is None


def test_get_pip_command_returns_install_command():
    """``get_pip_command`` returns a pip ``InstallCommand`` with a
    parser ready to consume general options."""
    from pipenv.patched.pip._internal.commands.install import InstallCommand

    from pipenv.utils.dependencies import get_pip_command

    cmd = get_pip_command()
    assert isinstance(cmd, InstallCommand)
    # Parser is the real pip parser; parse_args with no extra args succeeds.
    options, _ = cmd.parser.parse_args([])
    # Sanity: pip's install options expose ``index_url`` on the namespace.
    assert hasattr(options, "index_url")
