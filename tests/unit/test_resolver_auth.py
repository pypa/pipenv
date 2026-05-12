"""Unit tests for :mod:`pipenv.resolver.auth` (Initiative G phase 1, T16).

Covers the three helpers that T6 implemented (commit ``47ae206e``):

* :func:`pipenv.resolver.auth.extract_url_credentials`
* :func:`pipenv.resolver.auth.lookup_netrc_auth`
* :func:`pipenv.resolver.auth.client_cert_from_env`

This test module owns the full test surface for ``pipenv/resolver/auth.py``.
Per the Initiative G phase-1 plan it MUST achieve >=95% line coverage of that
module.  Tests deliberately use only ``tmp_path`` + ``monkeypatch`` and never
read the user's real ``~/.netrc``.

Module-level function tests (no class wrapper) for consistency with the
``tests/unit/test_candidate.py`` smoke convention (where a class is used) was
considered, but Initiative G phase 1's T16 spec explicitly asks for the
flatter module-level style, so that is what we use here.
"""
from __future__ import annotations

import netrc
import os

import pytest

from pipenv.resolver.auth import (
    client_cert_from_env,
    extract_url_credentials,
    lookup_netrc_auth,
)


# ---------------------------------------------------------------------------
# extract_url_credentials
# ---------------------------------------------------------------------------


def test_extract_url_credentials_no_creds_returns_url_unchanged():
    url = "https://host/path"
    stripped, creds = extract_url_credentials(url)
    assert stripped == "https://host/path"
    assert creds is None


def test_extract_url_credentials_plain_user_password():
    stripped, creds = extract_url_credentials("https://user:pass@host/path")
    assert stripped == "https://host/path"
    assert creds == ("user", "pass")


def test_extract_url_credentials_url_encoded_decoded():
    # ``%40`` -> ``@``, ``%23`` -> ``#``: callers receive decoded creds.
    stripped, creds = extract_url_credentials(
        "https://u%40e:p%23ass@host/path"
    )
    assert stripped == "https://host/path"
    assert creds == ("u@e", "p#ass")


def test_extract_url_credentials_empty_url_does_not_crash():
    stripped, creds = extract_url_credentials("")
    assert stripped == ""
    assert creds is None


def test_extract_url_credentials_http_scheme_preserved():
    stripped, creds = extract_url_credentials("http://user:pass@host/path")
    assert stripped == "http://host/path"
    assert creds == ("user", "pass")


def test_extract_url_credentials_ftp_scheme_preserved():
    stripped, creds = extract_url_credentials("ftp://user:pass@host/path")
    assert stripped == "ftp://host/path"
    assert creds == ("user", "pass")


def test_extract_url_credentials_query_and_fragment_preserved():
    stripped, creds = extract_url_credentials(
        "https://u:p@h/x?q=1#frag"
    )
    assert stripped == "https://h/x?q=1#frag"
    assert creds == ("u", "p")


def test_extract_url_credentials_port_preserved():
    stripped, creds = extract_url_credentials(
        "https://u:p@host:8443/"
    )
    assert stripped == "https://host:8443/"
    assert creds == ("u", "p")


def test_extract_url_credentials_username_only_no_colon():
    # ``user@host`` — username but no password.  ``urlparse`` exposes
    # ``username='user'``, ``password=None``.  The branch in the helper
    # is ``unquote(parsed.password) if parsed.password else ""``, so
    # password should round-trip as an empty string.
    stripped, creds = extract_url_credentials("https://user@host/path")
    assert stripped == "https://host/path"
    assert creds == ("user", "")


# ---------------------------------------------------------------------------
# lookup_netrc_auth
# ---------------------------------------------------------------------------


def _write_netrc(path, body):
    path.write_text(body, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        # On Windows chmod is best-effort; netrc.netrc() tolerates either way.
        pass
    return str(path)


def test_lookup_netrc_auth_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("NETRC", str(tmp_path / "does_not_exist"))
    # Also redirect $HOME so the real ~/.netrc cannot leak in.
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert lookup_netrc_auth("example.com") is None


def test_lookup_netrc_auth_empty_file_returns_none(tmp_path, monkeypatch):
    nrc = tmp_path / ".netrc"
    _write_netrc(nrc, "")
    monkeypatch.setenv("NETRC", str(nrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert lookup_netrc_auth("example.com") is None


def test_lookup_netrc_auth_matching_host_returns_credentials(
    tmp_path, monkeypatch
):
    nrc = tmp_path / ".netrc"
    _write_netrc(
        nrc,
        "machine example.com\n"
        "  login alice\n"
        "  password s3cret\n",
    )
    monkeypatch.setenv("NETRC", str(nrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert lookup_netrc_auth("example.com") == ("alice", "s3cret")


def test_lookup_netrc_auth_non_matching_host_returns_none(
    tmp_path, monkeypatch
):
    nrc = tmp_path / ".netrc"
    _write_netrc(
        nrc,
        "machine other.example.com\n"
        "  login alice\n"
        "  password s3cret\n",
    )
    monkeypatch.setenv("NETRC", str(nrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert lookup_netrc_auth("example.com") is None


def test_lookup_netrc_auth_malformed_does_not_raise(tmp_path, monkeypatch):
    nrc = tmp_path / ".netrc"
    # Deliberately broken: a ``machine`` keyword without a follow-up token,
    # which historically triggers ``netrc.NetrcParseError``.  The helper
    # swallows that exception and returns ``None``.
    _write_netrc(nrc, "machine\n  login alice\n  password s3cret\n")
    monkeypatch.setenv("NETRC", str(nrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # Must NOT raise; must return ``None``.
    assert lookup_netrc_auth("example.com") is None


def test_lookup_netrc_auth_os_error_swallowed(tmp_path, monkeypatch):
    """OSError raised by ``netrc.netrc(...)`` is swallowed.

    The helper docstring promises ``OSError`` is never propagated (so a
    half-broken netrc cannot break the resolver path).  We verify by
    monkeypatching ``netrc.netrc`` to raise.
    """
    nrc = tmp_path / ".netrc"
    _write_netrc(
        nrc,
        "machine example.com\n  login alice\n  password s3cret\n",
    )
    monkeypatch.setenv("NETRC", str(nrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def _boom(path):
        raise OSError("permission denied")

    monkeypatch.setattr(netrc, "netrc", _boom)
    assert lookup_netrc_auth("example.com") is None


def test_lookup_netrc_auth_empty_login_returns_none(tmp_path, monkeypatch):
    """An entry with empty login is treated as no usable creds.

    The helper's contract: ``if not login or password is None: continue``.
    netrc.authenticators returns the literal strings parsed from the file,
    so an entry whose login is the empty string (``login ""``) yields a
    falsy ``login`` and the helper skips it.
    """
    nrc = tmp_path / ".netrc"
    _write_netrc(
        nrc,
        'machine example.com\n  login ""\n  password s3cret\n',
    )
    monkeypatch.setenv("NETRC", str(nrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert lookup_netrc_auth("example.com") is None


def test_lookup_netrc_auth_missing_password_returns_none(
    tmp_path, monkeypatch
):
    """An entry whose password is ``None`` is treated as no creds.

    We exercise this via ``monkeypatch`` on ``netrc.netrc`` to inject a
    fake parsed object whose ``authenticators`` returns
    ``("alice", None, None)`` — that is the documented sentinel for an
    entry that omits the password.
    """
    nrc = tmp_path / ".netrc"
    _write_netrc(
        nrc,
        "machine example.com\n  login alice\n  password s3cret\n",
    )
    monkeypatch.setenv("NETRC", str(nrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

    class _FakeNetrc:
        def __init__(self, path):
            self.path = path

        def authenticators(self, host):
            return ("alice", None, None)

    monkeypatch.setattr(netrc, "netrc", _FakeNetrc)
    assert lookup_netrc_auth("example.com") is None


def test_lookup_netrc_auth_env_var_overrides_home(tmp_path, monkeypatch):
    """``$NETRC`` takes precedence over ``~/.netrc``.

    Implementation order: explicit-arg, then ``$NETRC``, then ``~/.netrc``.
    Both files contain entries for ``example.com`` with distinct creds; the
    one named by ``$NETRC`` must win.
    """
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    env_dir = tmp_path / "envdir"
    env_dir.mkdir()

    home_netrc = home_dir / ".netrc"
    _write_netrc(
        home_netrc,
        "machine example.com\n  login home_user\n  password home_pw\n",
    )
    env_netrc = env_dir / "envfile"
    _write_netrc(
        env_netrc,
        "machine example.com\n  login env_user\n  password env_pw\n",
    )

    monkeypatch.setenv("NETRC", str(env_netrc))
    monkeypatch.setenv("HOME", str(home_dir))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(home_dir))

    assert lookup_netrc_auth("example.com") == ("env_user", "env_pw")


def test_lookup_netrc_auth_explicit_arg_overrides_env(tmp_path, monkeypatch):
    """Explicit ``netrc_path`` beats ``$NETRC`` and ``~/.netrc``."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    env_dir = tmp_path / "envdir"
    env_dir.mkdir()
    explicit_dir = tmp_path / "explicit"
    explicit_dir.mkdir()

    _write_netrc(
        home_dir / ".netrc",
        "machine example.com\n  login home_user\n  password home_pw\n",
    )
    env_netrc = env_dir / "envfile"
    _write_netrc(
        env_netrc,
        "machine example.com\n  login env_user\n  password env_pw\n",
    )
    explicit_netrc = explicit_dir / "explicitfile"
    _write_netrc(
        explicit_netrc,
        "machine example.com\n  login explicit_user\n  password explicit_pw\n",
    )

    monkeypatch.setenv("NETRC", str(env_netrc))
    monkeypatch.setenv("HOME", str(home_dir))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(home_dir))

    got = lookup_netrc_auth("example.com", netrc_path=str(explicit_netrc))
    assert got == ("explicit_user", "explicit_pw")


def test_lookup_netrc_auth_empty_host_returns_none(tmp_path, monkeypatch):
    """``host=""`` short-circuits to ``None`` without touching the disk."""
    nrc = tmp_path / ".netrc"
    _write_netrc(
        nrc,
        "machine example.com\n  login alice\n  password s3cret\n",
    )
    monkeypatch.setenv("NETRC", str(nrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert lookup_netrc_auth("") is None


def test_lookup_netrc_auth_falls_back_to_home_when_no_env(
    tmp_path, monkeypatch
):
    """No ``$NETRC``, no explicit arg → ``~/.netrc`` is consulted."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_netrc(
        home_dir / ".netrc",
        "machine example.com\n  login alice\n  password s3cret\n",
    )
    monkeypatch.delenv("NETRC", raising=False)
    monkeypatch.setenv("HOME", str(home_dir))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(home_dir))
    assert lookup_netrc_auth("example.com") == ("alice", "s3cret")


def test_lookup_netrc_auth_skips_missing_explicit_then_uses_env(
    tmp_path, monkeypatch
):
    """A non-existent explicit path is skipped; the next candidate wins."""
    env_dir = tmp_path / "envdir"
    env_dir.mkdir()
    env_netrc = env_dir / "envfile"
    _write_netrc(
        env_netrc,
        "machine example.com\n  login env_user\n  password env_pw\n",
    )
    monkeypatch.setenv("NETRC", str(env_netrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
    got = lookup_netrc_auth(
        "example.com", netrc_path=str(tmp_path / "does_not_exist")
    )
    assert got == ("env_user", "env_pw")


def test_lookup_netrc_auth_no_home_returns_none(tmp_path, monkeypatch):
    """When ``expanduser('~')`` returns ``~`` (no home), the home branch
    is skipped.  With no ``$NETRC`` and no explicit arg, the helper has
    nothing to look at and returns ``None``."""
    monkeypatch.delenv("NETRC", raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p)
    assert lookup_netrc_auth("example.com") is None


@pytest.mark.skipif(os.name != "nt", reason="Windows _netrc filename only")
def test_lookup_netrc_auth_windows_underscore_filename(
    tmp_path, monkeypatch
):
    """On Windows the helper also looks for ``~/_netrc``."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_netrc(
        home_dir / "_netrc",
        "machine example.com\n  login alice\n  password s3cret\n",
    )
    monkeypatch.delenv("NETRC", raising=False)
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    monkeypatch.setenv("HOME", str(home_dir))
    assert lookup_netrc_auth("example.com") == ("alice", "s3cret")


# ---------------------------------------------------------------------------
# client_cert_from_env
# ---------------------------------------------------------------------------


def test_client_cert_from_env_unset_returns_none(monkeypatch):
    monkeypatch.delenv("PIP_CLIENT_CERT", raising=False)
    assert client_cert_from_env() is None


def test_client_cert_from_env_empty_returns_none(monkeypatch):
    monkeypatch.setenv("PIP_CLIENT_CERT", "")
    assert client_cert_from_env() is None


def test_client_cert_from_env_single_path_duplicated(monkeypatch):
    monkeypatch.setenv("PIP_CLIENT_CERT", "/tmp/cert.pem")
    assert client_cert_from_env() == ("/tmp/cert.pem", "/tmp/cert.pem")


def test_client_cert_from_env_whitespace_is_returned_verbatim(monkeypatch):
    """Pinned contract: T6's implementation does NOT strip whitespace.

    ``client_cert_from_env`` returns ``None`` only when the env var is unset
    OR the empty string (the literal ``if not value`` test in T6 evaluates
    falsy only on ``""`` / unset).  A whitespace-only value is therefore
    returned verbatim as ``("  ", "  ")``.  Test asserts that contract so
    a future "strip" change doesn't drift silently.
    """
    monkeypatch.setenv("PIP_CLIENT_CERT", "  ")
    assert client_cert_from_env() == ("  ", "  ")
