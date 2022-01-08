import pytest
import os

# Note that we have to do this *before* `pipenv.environments` gets imported,
# which is why we're doing it here as a side effect of importing this module.
# CI=1 is necessary as a workaround for https://github.com/pypa/pipenv/issues/4909
os.environ['CI'] = '1'

def pytest_sessionstart(session):
    import pipenv.environments
    assert pipenv.environments.PIPENV_IS_CI


@pytest.fixture()
def project():
    from pipenv.project import Project
    return Project()
