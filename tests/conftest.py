import pytest


@pytest.fixture()
def project():
    from pipenv.project import Project

    return Project()
