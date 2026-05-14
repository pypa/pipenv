"""Auth helpers for the pure-Python resolver path.

Three small helpers used by the PEP 691 simple-API client (Initiative G,
phase 1):

* :func:`extract_url_credentials` — split ``user:pass@`` userinfo out of an
  index URL.  Mirrors :func:`pipenv.utils.internet._strip_credentials_from_url`;
  duplicated here so the resolver path does not import from
  :mod:`pipenv.utils.internet`.
* :func:`lookup_netrc_auth` — read ``~/.netrc`` (or ``_netrc`` on Windows) and
  return ``(login, password)`` for a matching machine entry.
* :func:`client_cert_from_env` — read the ``PIP_CLIENT_CERT`` env var.

Keyring is intentionally out of scope for Phase 1.

This module MUST NOT import from pip's internal namespace.  The whole point
of Initiative G is to break the resolver's coupling to pip internals.  The
pre-commit gate added in T17 enforces this constraint via grep.
"""

from __future__ import annotations

import netrc
import os
from urllib.parse import unquote, urlparse, urlunsplit

__all__ = [
    "client_cert_from_env",
    "extract_url_credentials",
    "lookup_netrc_auth",
]


def extract_url_credentials(url: str) -> tuple[str, tuple[str, str] | None]:
    """Return ``(stripped_url, (username, password) or None)``.

    Mirrors :func:`pipenv.utils.internet._strip_credentials_from_url` exactly;
    duplicated here so the resolver path does not import from
    :mod:`pipenv.utils.internet`.

    When the URL has no embedded credentials, the second element is ``None``
    and the URL is returned unchanged.  Username and password are URL-decoded
    (``urllib.parse.unquote``) so callers can hand them straight to
    authentication backends (basic auth, netrc, ...).

    See GHSA-8xgg-v3jj-95m2: pipenv must not propagate credentials embedded
    in source URLs to subprocess argv where they are visible via ``ps`` and
    ``/proc/<pid>/cmdline``.
    """
    if not url:
        return url, None
    parsed = urlparse(url)
    if not parsed.username and not parsed.password:
        return url, None

    netloc = parsed.netloc.rsplit("@", 1)[-1]
    stripped = urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )
    username = unquote(parsed.username) if parsed.username else ""
    password = unquote(parsed.password) if parsed.password else ""
    return stripped, (username, password)


def _netrc_candidate_paths(netrc_path: str | None) -> list[str]:
    """Return netrc file paths to try, in priority order.

    Priority:
      1. Explicit ``netrc_path`` argument.
      2. ``$NETRC`` environment variable.
      3. ``~/.netrc`` on POSIX, ``~/_netrc`` on Windows (with ``~/.netrc``
         as a secondary fallback on Windows, matching the convention used
         by :mod:`netrc` and :mod:`requests`).
    """
    candidates: list[str] = []
    if netrc_path:
        candidates.append(netrc_path)
    env = os.environ.get("NETRC")
    if env:
        candidates.append(env)
    home = os.path.expanduser("~")
    if home and home != "~":
        if os.name == "nt":
            candidates.append(os.path.join(home, "_netrc"))
            candidates.append(os.path.join(home, ".netrc"))
        else:
            candidates.append(os.path.join(home, ".netrc"))
    return candidates


def lookup_netrc_auth(
    host: str, netrc_path: str | None = None
) -> tuple[str, str] | None:
    """Return ``(login, password)`` for ``host`` from netrc, or ``None``.

    Candidate paths are tried in this order: explicit ``netrc_path``, then
    ``$NETRC``, then ``~/.netrc`` (POSIX) / ``~/_netrc`` (Windows).  The
    first readable, parseable file that yields an authenticator for ``host``
    wins.

    Returns ``None`` if no candidate file exists, none parse cleanly, or no
    entry matches ``host``.  Never raises — netrc parse errors and OS errors
    (permission denied, etc.) are swallowed deliberately so a broken netrc
    cannot break the resolver path.
    """
    if not host:
        return None
    for path in _netrc_candidate_paths(netrc_path):
        if not path or not os.path.isfile(path):
            continue
        try:
            parsed = netrc.netrc(path)
        except (netrc.NetrcParseError, OSError):
            continue
        auth = parsed.authenticators(host)
        if auth is None:
            continue
        login, _account, password = auth
        # ``netrc.authenticators`` may return ``None`` for either field
        # when the entry omits it; treat that as "no usable credentials".
        # Python 3.10's parser also preserves surrounding quotes in tokens,
        # so ``login ""`` yields the literal ``""`` rather than the empty
        # string returned by 3.11+; strip outer quotes before the falsy
        # check so the behavior is consistent across Python versions.
        if not login or not login.strip('"') or password is None:
            continue
        return login, password
    return None


def client_cert_from_env() -> tuple[str, str] | None:
    """Return ``(cert_path, key_path)`` from ``$PIP_CLIENT_CERT``, or ``None``.

    Matches pip's existing convention: ``PIP_CLIENT_CERT`` is a single path
    that contains either the cert alone or a combined cert+key PEM bundle.
    We return ``(value, value)`` so callers that expect a ``(cert, key)``
    pair (e.g. urllib3's ``cert_file`` / ``key_file``) can pass both without
    branching on the single-vs-pair case.

    Returns ``None`` when the env var is unset or empty.
    """
    value = os.environ.get("PIP_CLIENT_CERT")
    if not value:
        return None
    return value, value
