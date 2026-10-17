import json

from pipenv.utils.pylock import PylockFile, _files_for_lockfile_hashes

WHEEL_HASH = "a" * 64
SDIST_HASH = "b" * 64


def test_from_lockfile_uses_real_simple_api_files(tmp_path, monkeypatch):
    class Response:
        content = json.dumps(
            {
                "files": [
                    {
                        "filename": "six-1.17.0-py2.py3-none-any.whl",
                        "url": "https://files.pythonhosted.org/six-1.17.0-py2.py3-none-any.whl",
                        "hashes": {"sha256": WHEEL_HASH},
                    },
                    {
                        "filename": "six-1.17.0.tar.gz",
                        "url": "https://files.pythonhosted.org/six-1.17.0.tar.gz",
                        "hashes": {"sha256": SDIST_HASH},
                    },
                ]
            }
        ).encode()
        headers = {"Content-Type": "application/vnd.pypi.simple.v1+json"}
        encoding = "utf-8"
        url = "https://pypi.org/simple/six/"

        def raise_for_status(self):
            pass

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            assert url == "https://pypi.org/simple/six/"
            return Response()

    monkeypatch.setattr(
        "pipenv.utils.internet.get_requests_session", lambda **kwargs: Session()
    )
    lockfile = tmp_path / "Pipfile.lock"
    lockfile.write_text(
        json.dumps(
            {
                "_meta": {"sources": [{"name": "pypi", "url": "https://pypi.org/simple"}]},
                "default": {
                    "six": {
                        "version": "==1.17.0",
                        "hashes": [f"sha256:{WHEEL_HASH}", f"sha256:{SDIST_HASH}"],
                    }
                },
                "develop": {},
            }
        )
    )

    pylock = PylockFile.from_lockfile(lockfile)
    package = pylock.packages[0]
    assert package["wheels"] == [
        {
            "name": "six-1.17.0-py2.py3-none-any.whl",
            "url": "https://files.pythonhosted.org/six-1.17.0-py2.py3-none-any.whl",
            "hashes": {"sha256": WHEEL_HASH},
        }
    ]
    assert package["sdist"]["name"] == "six-1.17.0.tar.gz"
    assert package["sdist"]["hashes"] == {"sha256": SDIST_HASH}
    assert "tool" not in package

    pylock.write()
    converted = PylockFile.from_path(pylock.path).convert_to_pipenv_lockfile()
    assert set(converted["default"]["six"]["hashes"]) == {
        f"sha256:{WHEEL_HASH}", f"sha256:{SDIST_HASH}"
    }


def test_unknown_hash_does_not_create_a_fake_wheel(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "pipenv.utils.pylock._files_for_lockfile_hashes", lambda *args: []
    )
    lockfile = tmp_path / "Pipfile.lock"
    lockfile.write_text(
        json.dumps(
            {
                "_meta": {"sources": [{"name": "pypi", "url": "https://pypi.org/simple"}]},
                "default": {"six": {"version": "==1.17.0", "hashes": [f"sha256:{SDIST_HASH}"]}},
                "develop": {},
            }
        )
    )

    pylock = PylockFile.from_lockfile(lockfile)
    package = pylock.packages[0]
    assert "wheels" not in package
    assert "sdist" not in package
    assert package["tool"]["pipenv"]["hashes"] == [f"sha256:{SDIST_HASH}"]

    pylock.write()
    converted = PylockFile.from_path(pylock.path).convert_to_pipenv_lockfile()
    assert converted["default"]["six"]["hashes"] == [f"sha256:{SDIST_HASH}"]


def test_html_simple_index_matches_hash_and_strips_url_credentials(monkeypatch):
    class Response:
        content = (
            f'<a href="https://user:secret@files.example/six-1.17.0.tar.gz'
            f'#sha256={SDIST_HASH}">six</a>'
        ).encode()
        headers = {"Content-Type": "text/html"}
        encoding = "utf-8"
        url = "https://index.example/simple/six/"

        def raise_for_status(self):
            pass

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            assert url == "https://index.example/simple/six/"
            return Response()

    monkeypatch.setattr(
        "pipenv.utils.internet.get_requests_session", lambda **kwargs: Session()
    )
    files = _files_for_lockfile_hashes(
        "six", "https://index.example/simple", [f"sha256:{SDIST_HASH}"]
    )
    assert files == [
        {
            "name": "six-1.17.0.tar.gz",
            "url": "https://files.example/six-1.17.0.tar.gz",
            "hashes": {"sha256": SDIST_HASH},
        }
    ]
