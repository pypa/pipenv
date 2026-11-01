"""``pipenv requirements`` emits ``--trusted-host`` for sources with ``verify_ssl = false``."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SOURCES = [
    {"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True},
    {"url": "https://user:${TOKEN}@private.example:8443/simple", "name": "private", "verify_ssl": False},
    {"url": "https://other.example/simple", "name": "other", "verify_ssl": False},
    {"url": "https://${PRIVATE_HOST}/simple", "name": "env-host", "verify_ssl": False},
]


@pytest.mark.parametrize("no_lock", [False, True])
def test_requirements_trusted_host(tmp_path, no_lock):
    source = Path(__file__).resolve().parents[2]
    pipfile = (
        "\n".join(
            f'[[source]]\nurl = "{s["url"]}"\nname = "{s["name"]}"\nverify_ssl = {str(s["verify_ssl"]).lower()}\n'
            for s in SOURCES
        )
        + '\n[packages]\nexample = "==1.2.3"\n'
    )
    lock = json.dumps(
        {
            "_meta": {"sources": SOURCES, "hash": {"sha256": "0" * 64}, "pipfile-spec": 6},
            "default": {"example": {"version": "==1.2.3"}},
            "develop": {},
        }
    )
    (tmp_path / "Pipfile").write_text(pipfile)
    (tmp_path / "Pipfile.lock").write_text(lock)
    env = os.environ.copy()
    env.update(PYTHONPATH=str(source), PIPENV_PIPFILE=str(tmp_path / "Pipfile"), PIPENV_IGNORE_VIRTUALENVS="1", PIPENV_DONT_LOAD_ENV="1")
    args = [sys.executable, "-m", "pipenv", "requirements"]
    if no_lock:
        args.append("--no-lock")
    result = subprocess.run(args, cwd=tmp_path, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "-i https://pypi.org/simple",
        "--extra-index-url https://user:${TOKEN}@private.example:8443/simple",
        "--trusted-host private.example:8443",
        "--extra-index-url https://other.example/simple",
        "--trusted-host other.example",
        "--extra-index-url https://${PRIVATE_HOST}/simple",
        "--trusted-host ${PRIVATE_HOST}",
        "example==1.2.3",
    ]


@pytest.mark.parametrize(
    ("url", "verify_ssl", "expected"),
    [
        ("https://Example.com:8443/simple", False, "example.com:8443"),
        ("https://${PRIVATE_HOST}/simple", False, "${PRIVATE_HOST}"),
        ("https://user:pw@${PRIVATE_HOST}:8443/simple", False, "${PRIVATE_HOST}:8443"),
        ("https://example.com/simple", True, None),
        ("file:///tmp/simple", False, None),
    ],
)
def test_get_insecure_source_host(url, verify_ssl, expected):
    from pipenv.utils.indexes import get_insecure_source_host

    assert get_insecure_source_host(url, verify_ssl) == expected


@pytest.mark.parametrize(
    ("url", "verify_ssl", "expected"),
    [
        ("https://user:password@private.example:8443/simple", False, "private.example:8443"),
        ("https://user:p%40ss%3Aword@private.example/simple", False, "private.example"),
        ("https://token-only@private.example/simple", False, "private.example"),
        ("https://${USER}:${TOKEN}@private.example/simple", False, "private.example"),
        ("https://user:password@$PRIVATE_HOST:8443/simple", False, "${PRIVATE_HOST}:8443"),
        ("https://user:password@[2001:db8::1]:8443/simple", False, "[2001:db8::1]:8443"),
        ("https://private.example/simple?token=query-token#fragment-token", False, "private.example"),
        ("https://user:password@private.example/simple", True, None),
        ("file:///tmp/simple", False, None),
        ("https://user:password@private.example:invalid/simple", False, None),
    ],
)
def test_print_trusted_host_excludes_credentials(url, verify_ssl, expected, capsys, monkeypatch):
    from pipenv.routines.requirements import _print_trusted_host

    monkeypatch.setenv("USER", "expanded-user")
    monkeypatch.setenv("TOKEN", "expanded-token")
    monkeypatch.setenv("PRIVATE_HOST", "expanded-host.example")

    _print_trusted_host({"url": url, "verify_ssl": verify_ssl})

    captured = capsys.readouterr()
    assert captured.out == (f"--trusted-host {expected}\n" if expected else "")
    assert captured.err == ""
