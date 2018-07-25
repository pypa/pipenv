import pytest
import mock

from pipenv.core import warn_in_virtualenv


@mock.patch('pipenv.environments.PIPENV_VIRTUALENV', 'totallyrealenv')
@mock.patch('pipenv.environments.PIPENV_VERBOSITY', -1)
@pytest.mark.core
def test_suppress_nested_venv_warning(capsys):
    # Capture the stderr of warn_in_virtualenv to test for the presence of the
    # courtesy notice.
    warn_in_virtualenv()
    output, err = capsys.readouterr()
    assert 'Courtesy Notice' not in err
