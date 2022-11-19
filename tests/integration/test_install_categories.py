import os
import tempfile

import pytest


@pytest.mark.categories
@pytest.mark.install
def test_basic_category_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install six --categories prereq")
        assert c.returncode == 0
        assert "six" not in p.pipfile["packages"]
        assert "six" not in p.lockfile["default"]
        assert "six" in p.pipfile["prereq"]
        assert "six" in p.lockfile["prereq"]


@pytest.mark.categories
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


@pytest.mark.extras
@pytest.mark.install
@pytest.mark.local
def test_multiple_category_install_proceeds_in_order_specified(pipenv_instance_private_pypi):
    """Ensure -e .[extras] installs.
    """
    with pipenv_instance_private_pypi(chdir=True) as p:
        #os.mkdir(os.path.join(p.path, "testpipenv"))
        setup_py = os.path.join(p.path, "setup.py")
        with open(setup_py, "w") as fh:
            contents = """
import six
from setuptools import setup
setup(
    name='testpipenv',
    version='0.1',
    description='Pipenv Test Package',
    author='Pipenv Test',
    author_email='test@pipenv.package',
    license='MIT',
    packages=[],
    install_requires=['six'],
    zip_safe=False
)
            """.strip()
            fh.write(contents)
        with open(os.path.join(p.path, 'Pipfile'), 'w') as fh:
            fh.write("""
[packages]
testpipenv = {path = ".", editable = true}

[prereq]
six = "*"
            """.strip())
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "testpipenv" in p.lockfile["default"]
        assert "testpipenv" not in p.lockfile["prereq"]
        assert "six" in p.lockfile["prereq"]
        c = p.pipenv('sync --categories="prereq packages" --extra-pip-args="--no-build-isolation" -v')
        assert c.returncode == 0
