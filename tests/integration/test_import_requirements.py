import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from pipenv.patched.pip._internal.operations.prepare import File
from pipenv.project import Project
from pipenv.utils.dependencies import import_requirements


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
@mock.patch(
    "pipenv.utils.unpack.unpack_url",
    mock.MagicMock(return_value=File("/some/path/to/project", content_type=None)),
)
@mock.patch("pipenv.utils.dependencies.find_package_name_from_directory")
def test_auth_with_pw_redacted(
    mock_find_package_name_from_directory, pipenv_instance_file_pypi
):
    mock_find_package_name_from_directory.return_value = "myproject"
    with pipenv_instance_file_pypi() as p:
        p.pipenv("shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write(
            """git+https://${AUTH_USER}:mypw1@github.com/user/myproject.git@main#egg=myproject"""
        )
        requirements_file.close()
        import_requirements(project, r=requirements_file.name)
        os.unlink(requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {'git': 'https://${AUTH_USER}:****@github.com/user/myproject.git', 'ref': 'main'}


@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
@mock.patch(
    "pipenv.utils.unpack.unpack_url",
    mock.MagicMock(return_value=File("/some/path/to/project", content_type=None)),
)
@mock.patch("pipenv.utils.dependencies.find_package_name_from_directory")
def test_auth_with_username_redacted(
    mock_find_package_name_from_directory, pipenv_instance_file_pypi
):
    mock_find_package_name_from_directory.return_value = "myproject"
    with pipenv_instance_file_pypi() as p:
        p.pipenv("shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write(
            """git+https://username@github.com/user/myproject.git@main#egg=myproject"""
        )
        requirements_file.close()
        import_requirements(project, r=requirements_file.name)
        os.unlink(requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {'git': 'https://****@github.com/user/myproject.git', 'ref': 'main'}



@pytest.mark.cli
@pytest.mark.deploy
@pytest.mark.system
@mock.patch(
    "pipenv.utils.unpack.unpack_url",
    mock.MagicMock(return_value=File("/some/path/to/project", content_type=None)),
)
@mock.patch("pipenv.utils.dependencies.find_package_name_from_directory")
def test_auth_with_pw_are_variables_passed_to_pipfile(
    mock_find_package_name_from_directory, pipenv_instance_file_pypi
):
    mock_find_package_name_from_directory.return_value = "myproject"
    with pipenv_instance_file_pypi() as p:
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
    "pipenv.utils.unpack.unpack_url",
    mock.MagicMock(return_value=File("/some/path/to/project", content_type=None)),
)
@mock.patch("pipenv.utils.dependencies.find_package_name_from_directory")
def test_auth_with_only_username_variable_passed_to_pipfile(
    mock_find_package_name_from_directory, pipenv_instance_file_pypi
):
    mock_find_package_name_from_directory.return_value = "myproject"
    with pipenv_instance_file_pypi() as p:
        p.pipenv("shell")
        project = Project()
        requirements_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        requirements_file.write(
            """git+https://${AUTH_USER}@github.com/user/myproject.git@main#egg=myproject"""
        )
        requirements_file.close()
        import_requirements(project, r=requirements_file.name)
        os.unlink(requirements_file.name)
        assert p.pipfile["packages"]["myproject"] == {'git': 'https://${AUTH_USER}@github.com/user/myproject.git', 'ref': 'main'}



@pytest.mark.integration
def test_import_requirements_with_path_object(pipenv_instance_file_pypi):
    """Test that import_requirements can handle Path objects correctly."""
    # Create a temporary requirements.txt file
    with pipenv_instance_file_pypi() as p:
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


@pytest.mark.integration
def test_import_requirements_preserves_existing_pypi_source(pipenv_instance_file_pypi):
    """Importing a requirements.txt with a `-i <url>` line into an
    ALREADY-EXISTING Pipfile must not delete that project's own,
    intentionally-configured sole pypi.org source.

    This is the call path used by `pipenv install -r requirements.txt`
    (``do_install_validations`` -> ``import_requirements`` with no
    ``replace_default_source`` override), which is structurally
    different from the one-time bare-Pipfile-conversion path
    (``ensure_pipfile`` -> ``project.create_pipfile()`` ->
    ``import_requirements(..., replace_default_source=True)``) where
    replacing an untouched default source is actually safe. Regression
    for a GitHub Copilot PR review finding on #6731.
    """
    with pipenv_instance_file_pypi() as p:
        # An existing project with a Pipfile whose sole source is its
        # own intentional pypi.org configuration (not an
        # auto-generated stand-in from a bare conversion).
        p.pipfile_path.write_text(
            '[[source]]\n'
            'url = "https://pypi.org/simple"\n'
            'name = "pypi"\n'
            'verify_ssl = true\n'
            '\n'
            '[packages]\n'
        )
        req_file_path = Path(p.path) / "requirements.txt"
        req_file_path.write_text("-i https://other-index.example/simple\nsix\n")

        project = Project()
        import_requirements(project, r=req_file_path)

        sources = project.pipfile.parsed.get("source")
        assert any(
            s.get("url") == "https://pypi.org/simple" for s in sources
        ), "the project's existing pypi.org source must be preserved, not replaced"


@pytest.mark.integration
def test_install_dash_r_with_file_url_requirementstxt(pipenv_instance_file_pypi):
    """`pipenv install -r file:///abs/path/requirements.txt` must resolve
    the file:// URL to a local filesystem path before do_install_validations()
    hands it to project.path_to() - which, given the literal
    "file:///abs/path/requirements.txt" string, treats it as a *relative*
    path (it doesn't start with "/") and joins it onto the project
    directory, producing a nonexistent path like
    "<project>/file:/abs/path/requirements.txt" and failing the import.
    Regression for a Copilot PR review finding on #6731.
    """
    with pipenv_instance_file_pypi() as p:
        req_file_path = Path(p.path) / "requirements.txt"
        req_file_path.write_text("six\n")

        c = p.pipenv(f"install -r {req_file_path.as_uri()}")

        assert c.returncode == 0, c.stderr
        assert "six" in p.pipfile["packages"]


@pytest.mark.integration
def test_import_requirements_preserves_markers(pipenv_instance_file_pypi):
    """Test that import_requirements preserves environment markers like sys_platform.

    Fixes: https://github.com/pypa/pipenv/issues/6101
    """
    with pipenv_instance_file_pypi() as p:
        req_file_path = Path(p.path) / "requirements.txt"
        # Create requirements with environment markers
        with open(req_file_path, "w") as f:
            f.write("six; sys_platform == 'win32'\n")

        try:
            # Create a Project instance
            project = Project()

            # Call import_requirements
            import_requirements(project, r=req_file_path)

            # Verify that the package was added with markers
            assert "six" in p.pipfile["packages"]
            pkg_entry = p.pipfile["packages"]["six"]
            # The entry should be a dict with markers
            assert isinstance(pkg_entry, dict)
            assert "markers" in pkg_entry
            assert "sys_platform" in pkg_entry["markers"]
            assert "win32" in pkg_entry["markers"]
        finally:
            # Clean up
            if os.path.exists(req_file_path):
                os.unlink(req_file_path)
            if os.path.exists("Pipfile"):
                os.unlink("Pipfile")
