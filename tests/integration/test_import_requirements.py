import os
from pathlib import Path
import tempfile

import pytest

from pipenv.core import import_requirements
from pipenv.project import Project


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
def test_auth_with_pw_redacted(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p.pipenv("run shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write("""git+https://${AUTH_USER}:mypw1@github.com/user/myproject.git#egg=myproject""")
        requirements_file.close()
        print(requirements_file.name)
        import_requirements(project, r=requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {'git': 'https://${AUTH_USER}:****@github.com/user/myproject.git'}


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
def test_auth_with_username_redacted(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p.pipenv("run shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write("""git+https://username@github.com/user/myproject.git#egg=myproject""")
        requirements_file.close()
        print(requirements_file.name)
        import_requirements(project, r=requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {'git': 'https://****@github.com/user/myproject.git'}


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
def test_auth_with_pw_are_variables_passed_to_pipfile(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p.pipenv("run shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write("""git+https://${AUTH_USER}:${AUTH_PW}@github.com/user/myproject.git#egg=myproject""")
        requirements_file.close()
        print(requirements_file.name)
        import_requirements(project, r=requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {'git': 'https://${AUTH_USER}:${AUTH_PW}@github.com/user/myproject.git'}

@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
def test_auth_with_only_username_variable_passed_to_pipfile(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        p.pipenv("run shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write("""git+https://${AUTH_USER}@github.com/user/myproject.git#egg=myproject""")
        requirements_file.close()
        print(requirements_file.name)
        import_requirements(project, r=requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {'git': 'https://${AUTH_USER}@github.com/user/myproject.git'}
