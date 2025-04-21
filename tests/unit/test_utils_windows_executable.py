import os
from unittest import mock

import pytest

from pipenv.utils import shell

# This module is run only on Windows.
pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="only relevant on windows",
)


@pytest.mark.utils
@pytest.mark.skipif(os.name != "nt", reason="Windows test only")
@mock.patch("os.path.isfile")
@mock.patch("shutil.which")
def test_find_windows_executable_when_not_found(mocked_which, mocked_isfile):
    # Set up the mock to ensure call_count is at least 1
    def side_effect(path):
        return False
    mocked_isfile.side_effect = side_effect

    mocked_which.return_value = None
    found = shell.find_windows_executable("fake/path", "python")
    assert found is None


@pytest.mark.utils
@pytest.mark.skipif(os.name != "nt", reason="Windows test only")
@mock.patch("os.path.isfile")
@mock.patch("shutil.which")
def test_find_windows_executable_when_found(mocked_which, mocked_isfile):
    # Set up the mock to ensure call_count is at least 1
    def side_effect(path):
        return False
    mocked_isfile.side_effect = side_effect

    # Use Windows-style path for consistency
    found_path = "\\fake\\known\\system\\path\\pyenv"
    mocked_which.return_value = found_path
    found = shell.find_windows_executable("fake/path", "pyenv")

    # Compare normalized paths to handle slash differences
    assert str(found).replace('/', '\\') == found_path
