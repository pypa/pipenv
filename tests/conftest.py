import pytest
import os

def pytest_sessionstart(session):
    # CI=1 is necessary as a workaround for https://github.com/pypa/pipenv/issues/4909
    os.environ['CI'] = '1'


@pytest.fixture()
def project():
    from pipenv.project import Project
    return Project()
