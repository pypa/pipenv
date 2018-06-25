from pipenv.project import Project

import pytest


@pytest.mark.project
def test_virtualenv_name():
    project = Project()
    project._name = '-directory-with-dash'
    assert not project.virtualenv_name.startswith('-')
