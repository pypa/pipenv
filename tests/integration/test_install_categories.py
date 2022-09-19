import pytest


@pytest.mark.basic
@pytest.mark.install
def test_basic_category_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install six --categories prereq")
        assert c.returncode == 0
        assert "six" not in p.pipfile["packages"]
        assert "six" not in p.lockfile["default"]
        assert "six" in p.pipfile["prereq"]
        assert "six" in p.lockfile["prereq"]


@pytest.mark.basic
@pytest.mark.install
def test_multiple_category_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv('install six --categories="prereq other"')
        assert c.returncode == 0
        assert "six" not in p.pipfile["packages"]
        assert "six" not in p.lockfile["default"]
        assert "six" in p.pipfile["prereq"]
        assert "six" in p.lockfile["prereq"]
        assert "six" in p.lockfile["other"]
        assert "six" in p.lockfile["other"]
