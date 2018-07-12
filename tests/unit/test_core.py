import io

import pytest
import mock
from contextlib import redirect_stderr

from pipenv.core import warn_in_virtualenv


@mock.patch('pipenv.environments.PIPENV_VIRTUALENV', 'totallyrealenv')
@mock.patch('pipenv.environments.PIPENV_SUPPRESS_NESTED_WARNING', '1')
@pytest.mark.core
def test_suppress_nested_venv_warning():
    f = io.StringIO()
    # Capture the stderr of warn_in_virtualenv to test for the presence of the
    # courtesy notice.
    with redirect_stderr(f):
        warn_in_virtualenv()
    output = f.getvalue()
    assert 'Courtesy Notice' not in output
