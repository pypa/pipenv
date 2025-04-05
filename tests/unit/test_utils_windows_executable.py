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
    mocked_isfile.return_value = False
    mocked_which.return_value = None
    found = shell.find_windows_executable("fake/path", "python")
    assert found is None

    # Check that isfile was called at least once
    assert mocked_isfile.call_count >= 1


@pytest.mark.utils
@pytest.mark.skipif(os.name != "nt", reason="Windows test only")
@mock.patch("os.path.isfile")
@mock.patch("shutil.which")
def test_find_windows_executable_when_found(mocked_which, mocked_isfile):
    mocked_isfile.return_value = False
    found_path = "/fake/known/system/path/pyenv"
    mocked_which.return_value = found_path
    found = shell.find_windows_executable("fake/path", "pyenv")
    assert str(found) == found_path  # Compare string representations

    assert mocked_isfile.call_count > 1

    calls = [mock.call("fake\\path\\pyenv")] + [
        mock.call(f"fake\\path\\pyenv{ext.lower()}")
        for ext in os.environ["PATHEXT"].split(";")
    ]
    assert mocked_isfile.mock_calls == calls
