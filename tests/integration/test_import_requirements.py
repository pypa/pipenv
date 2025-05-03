import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from pipenv.patched.pip._internal.operations.prepare import File
from pipenv.project import Project
from pipenv.utils.requirements import import_requirements


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
@mock.patch(
    "pipenv.utils.dependencies.unpack_url",
    mock.MagicMock(return_value=File("/some/path/to/project", content_type=None)),
)
@mock.patch("pipenv.utils.dependencies.find_package_name_from_directory")
def test_auth_with_pw_redacted(
    mock_find_package_name_from_directory, pipenv_instance_pypi
):
    mock_find_package_name_from_directory.return_value = "myproject"
    with pipenv_instance_pypi() as p:
        p.pipenv("shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write(
            """git+https://${AUTH_USER}:mypw1@github.com/user/myproject.git@main#egg=myproject"""
        )
        requirements_file.close()
        import_requirements(project, r=requirements_file.name)
        os.unlink(requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {
            'git': 'https://${AUTH_USER}:****@github.com/user/myproject.git',
            'ref': 'main'
        }


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
@mock.patch(
    "pipenv.utils.dependencies.unpack_url",
    mock.MagicMock(return_value=File("/some/path/to/project", content_type=None)),
)
@mock.patch("pipenv.utils.dependencies.find_package_name_from_directory")
def test_auth_with_username_redacted(
    mock_find_package_name_from_directory, pipenv_instance_pypi
):
    mock_find_package_name_from_directory.return_value = "myproject"
    with pipenv_instance_pypi() as p:
        p.pipenv("shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write(
            """git+https://username@github.com/user/myproject.git@main#egg=myproject"""
        )
        requirements_file.close()
        import_requirements(project, r=requirements_file.name)
        os.unlink(requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {
            'git': 'https://****@github.com/user/myproject.git',
            'ref': 'main'
        }



@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
@mock.patch(
    "pipenv.utils.dependencies.unpack_url",
    mock.MagicMock(return_value=File("/some/path/to/project", content_type=None)),
)
@mock.patch("pipenv.utils.dependencies.find_package_name_from_directory")
def test_auth_with_pw_are_variables_passed_to_pipfile(
    mock_find_package_name_from_directory, pipenv_instance_pypi
):
    mock_find_package_name_from_directory.return_value = "myproject"
    with pipenv_instance_pypi() as p:
        p.pipenv("shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write(
            """git+https://${AUTH_USER}:${AUTH_PW}@github.com/user/myproject.git@main#egg=myproject"""
        )
        requirements_file.close()
        import_requirements(project, r=requirements_file.name)
        os.unlink(requirements_file.name)
        expected = {'git': 'https://${AUTH_USER}:${AUTH_PW}@github.com/user/myproject.git', 'ref': 'main'}
        assert p.pipfile["packages"]["myproject"] == expected


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
@mock.patch(
    "pipenv.utils.dependencies.unpack_url",
    mock.MagicMock(return_value=File("/some/path/to/project", content_type=None)),
)
@mock.patch("pipenv.utils.dependencies.find_package_name_from_directory")
def test_auth_with_only_username_variable_passed_to_pipfile(
    mock_find_package_name_from_directory, pipenv_instance_pypi
):
    mock_find_package_name_from_directory.return_value = "myproject"
    with pipenv_instance_pypi() as p:
        p.pipenv("shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write(
            """git+https://${AUTH_USER}@github.com/user/myproject.git@main#egg=myproject"""
        )
        requirements_file.close()
        import_requirements(project, r=requirements_file.name)
        os.unlink(requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {
            'git': 'https://${AUTH_USER}@github.com/user/myproject.git',
            'ref': 'main'
        }



@pytest.mark.integration
def test_import_requirements_with_path_object(pipenv_instance_pypi):
    """Test that import_requirements can handle Path objects correctly."""
    # Create a temporary requirements.txt file
    with pipenv_instance_pypi() as p:
        req_file_path = Path(p.path) / "requirements.txt"
        with open(req_file_path, "w") as f:
            f.write("requests\n")

        try:
            # Create a Project instance
            project = Project()

            # Call import_requirements with a Path object
            import_requirements(project, r=req_file_path)

            # Verify that the package was added to the Pipfile
            with open("Pipfile") as f:
                pipfile_content = f.read()
                assert "requests" in pipfile_content
        finally:
            # Clean up
            if os.path.exists(req_file_path):
                os.unlink(req_file_path)
            if os.path.exists("Pipfile"):
                os.unlink("Pipfile")
