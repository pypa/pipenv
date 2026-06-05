"""Tests for the credential-handling helpers introduced for
GHSA-8xgg-v3jj-95m2.

Pipenv must not pass credentials embedded in package-index URLs as
command-line arguments to ``pip`` — argv is visible to other local users
via ``ps`` and ``/proc/<pid>/cmdline``.  Credentials are instead injected
out-of-band via a temporary netrc file referenced by the ``NETRC``
environment variable.
"""

import os
import re
import stat

import pytest

from pipenv.utils import pip as pip_utils
from pipenv.utils.internet import (
    _strip_credentials_from_url,
    write_credentials_netrc,
)


@pytest.mark.utils
@pytest.mark.parametrize(
    "url, expected_url, expected_creds",
    [
        ("https://host/simple", "https://host/simple", None),
        (
            "https://user:pass@host/simple",
            "https://host/simple",
            ("user", "pass"),
        ),
        (
            "https://user:pass@host:8443/simple/",
            "https://host:8443/simple/",
            ("user", "pass"),
        ),
        (
            # Userinfo with URL-encoded special characters must come back
            # decoded so callers can hand them to a netrc parser.
            "https://u%40s:p%40ss%21@host/simple",
            "https://host/simple",
            ("u@s", "p@ss!"),
        ),
        (
            # Username only (no colon, no password) is still credentials.
            "https://justuser@host/simple",
            "https://host/simple",
            ("justuser", ""),
        ),
        ("", "", None),
        (None, None, None),
    ],
)
def test_strip_credentials_from_url(url, expected_url, expected_creds):
    stripped, creds = _strip_credentials_from_url(url)
    assert stripped == expected_url
    assert creds == expected_creds


@pytest.mark.utils
def test_write_credentials_netrc_returns_none_when_no_creds(tmp_path):
    sources = [
        {"url": "https://pypi.org/simple"},
        {"url": "https://mirror.example.com/simple"},
    ]
    assert write_credentials_netrc(sources, tmp_path) is None
    assert not (tmp_path / "pipenv-netrc").exists()


@pytest.mark.utils
def test_write_credentials_netrc_emits_machine_block(tmp_path):
    sources = [
        {"url": "https://pypi.org/simple", "name": "pypi"},
        {
            "url": "https://__token__:abc123@private.example.com/simple",
            "name": "private",
        },
    ]
    netrc_path = write_credentials_netrc(sources, tmp_path)
    assert netrc_path is not None
    assert os.path.isfile(netrc_path)

    with open(netrc_path, encoding="utf-8") as f:
        contents = f.read()
    assert "machine private.example.com" in contents
    assert "login __token__" in contents
    assert "password abc123" in contents
    # Hosts without credentials must not appear.
    assert "pypi.org" not in contents


@pytest.mark.utils
@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
def test_write_credentials_netrc_is_owner_readable_only(tmp_path):
    sources = [{"url": "https://u:p@host.example.com/simple"}]
    netrc_path = write_credentials_netrc(sources, tmp_path)
    mode = stat.S_IMODE(os.stat(netrc_path).st_mode)
    # netrc parsers refuse files that are group/world readable.
    assert mode == 0o600


@pytest.mark.utils
def test_write_credentials_netrc_dedupes_hosts(tmp_path):
    sources = [
        {"url": "https://u1:p1@same.example.com/a/"},
        {"url": "https://u2:p2@same.example.com/b/"},
    ]
    netrc_path = write_credentials_netrc(sources, tmp_path)
    with open(netrc_path, encoding="utf-8") as f:
        contents = f.read()
    # Only the first occurrence is kept — pipenv resolves auth by host so
    # repeats would just collide anyway.
    assert contents.count("machine same.example.com") == 1
    assert "login u1" in contents
    assert "login u2" not in contents


@pytest.mark.utils
def test_write_credentials_netrc_decodes_url_encoded_password(tmp_path):
    """A password URL-encoded in the source URL must be decoded before being
    written to netrc, otherwise pip would send the encoded form to the
    server."""
    sources = [{"url": "https://user:p%40ss%21@host.example.com/simple"}]
    netrc_path = write_credentials_netrc(sources, tmp_path)
    with open(netrc_path, encoding="utf-8") as f:
        contents = f.read()
    assert "password p@ss!" in contents


@pytest.mark.utils
def test_write_credentials_netrc_pipfile_wins_over_existing_system_netrc(
    tmp_path, monkeypatch
):
    """Pipfile-derived creds must beat a duplicate entry from the user's
    pre-existing system netrc.

    Regression test for gh-6670: after GHSA-8xgg-v3jj-95m2 moved auth from
    URL-embedded argv onto a merged netrc, a stale ``machine`` block in
    ``~/.netrc`` (or ``$NETRC``) for the same host silently overrode the
    Pipfile's credentials because ``netrc.authenticators()`` returns the
    LAST matching entry. Our blocks must come AFTER the appended existing
    content so they win that tie-break.
    """
    import netrc

    system_netrc = tmp_path / "system.netrc"
    system_netrc.write_text(
        "machine private.example.com\n  login STALE\n  password STALE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NETRC", str(system_netrc))

    sources = [{"url": "https://fresh:freshpass@private.example.com/simple"}]
    netrc_path = write_credentials_netrc(sources, tmp_path)
    assert netrc_path is not None

    login, _account, password = netrc.netrc(netrc_path).authenticators(
        "private.example.com"
    )
    assert (login, password) == ("fresh", "freshpass"), (
        "Pipfile-supplied creds must override the user's existing netrc"
    )


@pytest.mark.utils
def test_write_credentials_netrc_from_env_var_expanded_url(tmp_path, monkeypatch):
    """The expand_url_credentials → write_credentials_netrc round-trip must
    produce a netrc with the expanded (real) credentials, not the literal
    ``${VAR}`` placeholders.

    Regression test for gh-6670: ensures that env-var-bearing source URLs
    flow through ``pipfile_sources()`` (which calls
    ``expand_url_credentials``) and yield a netrc with the actual user/pass,
    matching the hardcoded-credentials behavior the GHSA fix preserved.
    """
    import netrc

    from pipenv.utils.shell import expand_url_credentials

    monkeypatch.setenv("NEXUS_USERNAME", "real-user")
    monkeypatch.setenv("NEXUS_PASSWORD", "real-pass!@#")

    raw_url = (
        "https://${NEXUS_USERNAME}:${NEXUS_PASSWORD}"
        "@nexus.example.com/repository/pypi/simple"
    )
    expanded = expand_url_credentials(raw_url)
    netrc_path = write_credentials_netrc([{"url": expanded}], tmp_path)
    assert netrc_path is not None

    login, _account, password = netrc.netrc(netrc_path).authenticators(
        "nexus.example.com"
    )
    assert (login, password) == ("real-user", "real-pass!@#")


@pytest.mark.utils
def test_set_resolver_netrc_includes_pypi_mirror_credentials(tmp_path, monkeypatch):
    """``_set_resolver_netrc`` must write the credentials embedded in
    ``PIPENV_PYPI_MIRROR`` to the resolver netrc.

    Regression test for gh-6677: the resolver subprocess prepends a mirror
    source built from ``PIPENV_PYPI_MIRROR`` (which carries the user's
    credentials), but the parent wrote the netrc from the un-mirrored
    ``pipfile_sources()``.  After GHSA-8xgg-v3jj-95m2 moved auth from pip
    argv onto netrc, the mirror's credentials were dropped and private-index
    resolution failed with 401 / ``ResolutionFailure``.
    """
    import netrc

    from pipenv.utils.resolver import _set_resolver_netrc

    monkeypatch.setenv("PIPENV_PYPI_MIRROR", "https://user:secret@pypi.mirror")
    # Register NETRC with monkeypatch so the direct ``os.environ`` write done
    # inside ``_set_resolver_netrc`` is reverted on teardown.
    monkeypatch.setenv("NETRC", "")

    class _Project:
        # Mirrors the issue's Pipfile: a custom-host source named "pypi"
        # with no embedded credentials.
        def pipfile_sources(self):
            return [{"url": "https://pypi.mirror", "verify_ssl": True, "name": "pypi"}]

    _set_resolver_netrc(_Project(), str(tmp_path))

    netrc_path = os.environ.get("NETRC")
    assert netrc_path is not None
    login, _account, password = netrc.netrc(netrc_path).authenticators("pypi.mirror")
    assert (login, password) == ("user", "secret")


# --- pip_install_deps integration -------------------------------------------


class _FakeSettings:
    PIP_EXISTS_ACTION = None
    PIPENV_KEYRING_PROVIDER = None
    PIPENV_BREAK_SYSTEM_PACKAGES = None

    def __init__(self, cache_dir):
        self.PIPENV_CACHE_DIR = cache_dir

    def is_verbose(self):
        return False


class _FakeProject:
    def __init__(self, cache_dir, src_dir):
        self.s = _FakeSettings(cache_dir)
        self.settings = {}
        self.virtualenv_src_location = src_dir


@pytest.mark.utils
def test_pip_install_deps_strips_credentials_from_argv(monkeypatch, tmp_path):
    """End-to-end check that ``pip_install_deps`` does not leak credentials
    into the pip subprocess argv.  See GHSA-8xgg-v3jj-95m2.
    """
    captured = {}

    def fake_subprocess_run(args, **kwargs):
        captured.setdefault("args_calls", []).append(list(args))
        captured["env"] = dict(kwargs.get("env") or {})

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""
            args = []

            def communicate(self):
                return ("", "")

        return _Proc()

    monkeypatch.setattr(pip_utils, "project_python", lambda project, system=False: "python")
    monkeypatch.setattr(pip_utils, "get_runnable_pip", lambda: "pip")
    monkeypatch.setattr(pip_utils, "subprocess_run", fake_subprocess_run)

    project = _FakeProject(str(tmp_path / "cache"), str(tmp_path / "src"))
    sources = [
        {
            "url": "https://user:SuperSecret123@10.255.255.1/simple",
            "verify_ssl": True,
            "name": "private",
        }
    ]

    pip_utils.pip_install_deps(
        project=project,
        deps=["requests==2.32.0"],
        sources=sources,
        allow_global=False,
        ignore_hashes=True,
        no_deps=True,
        requirements_dir=str(tmp_path),
        use_pep517=True,
        extra_pip_args=None,
    )

    assert captured["args_calls"], "subprocess_run should have been called"
    flat_argv = " ".join(
        token for call in captured["args_calls"] for token in call
    )
    # The literal credentials must not appear anywhere in argv.
    assert "SuperSecret123" not in flat_argv
    assert re.search(r"://[^\s/@]+:[^\s/@]+@", flat_argv) is None
    # The credential-stripped URL is still present (so pip knows the index).
    assert "https://10.255.255.1/simple" in flat_argv

    env = captured["env"]
    # Env vars carry the stripped URL too — credentials are delivered via netrc.
    assert env.get("PIP_INDEX_URL") == "https://10.255.255.1/simple"
    assert "SuperSecret123" not in env.get("PIP_INDEX_URL", "")
    netrc_path = env.get("NETRC")
    assert netrc_path and os.path.isfile(netrc_path)
    with open(netrc_path, encoding="utf-8") as f:
        netrc_contents = f.read()
    assert "SuperSecret123" in netrc_contents
    assert "machine 10.255.255.1" in netrc_contents


@pytest.mark.utils
def test_pip_install_deps_no_netrc_when_no_credentials(monkeypatch, tmp_path):
    captured = {}

    def fake_subprocess_run(args, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""
            args = []

            def communicate(self):
                return ("", "")

        return _Proc()

    monkeypatch.setattr(pip_utils, "project_python", lambda project, system=False: "python")
    monkeypatch.setattr(pip_utils, "get_runnable_pip", lambda: "pip")
    monkeypatch.setattr(pip_utils, "subprocess_run", fake_subprocess_run)

    project = _FakeProject(str(tmp_path / "cache"), str(tmp_path / "src"))
    pip_utils.pip_install_deps(
        project=project,
        deps=["requests==2.32.0"],
        sources=[{"url": "https://pypi.org/simple"}],
        allow_global=False,
        ignore_hashes=True,
        no_deps=True,
        requirements_dir=str(tmp_path),
        use_pep517=True,
        extra_pip_args=None,
    )

    # Without credentialed sources, NETRC should not be set so the user's
    # existing netrc / keyring continues to take effect normally.
    assert "NETRC" not in captured["env"]
