"""Tests for :func:`pipenv.utils.internet.create_mirror_source`."""

from pipenv.utils.internet import create_mirror_source


def test_create_mirror_source_https_is_secure():
    assert create_mirror_source("https://example.org/simple", "example")["verify_ssl"] is True


def test_create_mirror_source_http_is_insecure():
    assert create_mirror_source("http://example.org/simple", "example")["verify_ssl"] is False


def test_create_mirror_source_file_is_secure():
    """file:// has no TLS to verify, so there's nothing to flag as
    untrusted - marking it verify_ssl=False would make
    prepare_pip_source_args emit a nonsensical "--trusted-host None"
    (file:// URLs have no host for pip's --trusted-host flag)."""
    assert create_mirror_source("file:///tmp/index", "local")["verify_ssl"] is True


def test_create_mirror_source_ftp_is_insecure():
    """Regression for a Copilot PR review finding on #6731: an earlier
    fix for file:// mirrors used `not url.startswith("http://")` to
    decide insecurity, which silently flipped every non-http:// scheme
    (not just file://) to "secure" - losing the --trusted-host flag
    that prepare_pip_source_args supplies for genuinely insecure
    mirrors like ftp://.
    """
    assert create_mirror_source("ftp://example.org/simple", "example")["verify_ssl"] is False
