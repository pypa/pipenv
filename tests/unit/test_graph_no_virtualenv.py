"""``pipenv graph`` reports a missing virtualenv and exits with 1."""

from unittest import mock

import pytest

from pipenv.routines.graph import do_graph


def test_graph_without_virtualenv_exits_with_error(capsys):
    project = mock.MagicMock()
    project.venv_locator.python.return_value = "/venv/bin/python"
    project.venv_locator.exists = False

    with pytest.raises(SystemExit) as excinfo:
        do_graph(project)

    assert excinfo.value.code == 1
    assert "No virtualenv has been created" in capsys.readouterr().err
