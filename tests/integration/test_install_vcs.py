import pytest


@pytest.mark.basic
@pytest.mark.install
def test_install_github_vcs(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install git+https://github.com/reagento/adaptix.git@2.16")
        assert not c.returncode
        assert "dataclass-factory" in p.pipfile["packages"]
