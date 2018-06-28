import os

import mock
import pytest

from pipenv import utils


# This module is run only on Windows.
pytestmark = pytest.mark.skipif(
    os.name != 'nt',
    reason="only relevant on windows",
)


@mock.patch('os.path.isfile')
@mock.patch('pipenv.utils.find_executable')
def test_find_windows_executable(mocked_find_executable, mocked_isfile):
    mocked_isfile.return_value = False
    mocked_find_executable.return_value = None
    found = utils.find_windows_executable('fake/path', 'python')
    assert found is None

    assert mocked_isfile.call_count > 1

    calls = [mock.call('fake\\path\\python')] + [
        mock.call('fake\\path\\python{0}'.format(ext.lower()))
        for ext in os.environ['PATHEXT'].split(';')
    ]
    assert mocked_isfile.mock_calls == calls
