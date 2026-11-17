from pathlib import Path

import pytest

from pipenv.utils.fileutils import open_file, path_to_url, url_to_path


@pytest.mark.parametrize(
    "name",
    [
        "requirements%20dev.txt",
        "requirements%2Fdev.txt",
        "requirements%25dev.txt",
        "requirements%2520dev.txt",
        "requirements%FFdev.txt",
        "requirements dev.txt",
        "requirements+dev.txt",
        "requirements-café.txt",
    ],
)
def test_file_url_round_trip(tmp_path, name):
    path = tmp_path / name
    assert url_to_path(path_to_url(path)) == path
    assert url_to_path(path.as_uri()) == path


@pytest.mark.parametrize("as_url", [False, True])
@pytest.mark.parametrize(
    "name", ["requirements%20dev.txt", "requirements%2Fdev.txt", "requirements%25dev.txt"]
)
def test_open_file_literal_percent_path(tmp_path, name, as_url):
    path = tmp_path / name
    content = b"requests==2.32.5\n"
    path.write_bytes(content)
    link = path.as_uri() if as_url else str(path)
    with open_file(link) as stream:
        assert stream.read() == content
    assert stream.closed


def test_url_to_path_returns_path():
    assert isinstance(url_to_path("file:///tmp/requirements.txt"), Path)
