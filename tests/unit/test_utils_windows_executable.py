import os

import mock
import pytest

import utils.shell
from pipenv import utils


# This module is run only on Windows.
pytestmark = pytest.mark.skipif(
    os.name != 'nt',
    reason="only relevant on windows",
)


@pytest.mark.utils
@mock.patch('os.path.isfile')
@mock.patch('shutil.which')
def test_find_windows_executable_when_not_found(mocked_which, mocked_isfile):
    mocked_isfile.return_value = False
    mocked_which.return_value = None
    found = utils.filesystem.find_windows_executable('fake/path', 'python')
    assert found is None

    assert mocked_isfile.call_count > 1

    calls = [mock.call('fake\\path\\python')] + [
        mock.call('fake\\path\\python{0}'.format(ext.lower()))
        for ext in os.environ['PATHEXT'].split(';')
    ]
    assert mocked_isfile.mock_calls == calls


@pytest.mark.utils
@mock.patch('os.path.isfile')
@mock.patch('shutil.which')
def test_find_windows_executable_when_found(mocked_which, mocked_isfile):
    mocked_isfile.return_value = False
    found_path = '/fake/known/system/path/pyenv'
    mocked_which.return_value = found_path
    found = utils.filesystem.find_windows_executable('fake/path', 'pyenv')
    assert found is found_path

    assert mocked_isfile.call_count > 1

    calls = [mock.call('fake\\path\\pyenv')] + [
        mock.call('fake\\path\\pyenv{0}'.format(ext.lower()))
        for ext in os.environ['PATHEXT'].split(';')
    ]
    assert mocked_isfile.mock_calls == calls
