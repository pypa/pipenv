import pytest

from pipenv.project import Project
from pipenv.routines.update import get_modified_pipfile_entries


@pytest.mark.parametrize("cmd_option", ["", "--dev"])
@pytest.mark.basic
@pytest.mark.update
@pytest.mark.skipif(
    "os.name == 'nt' and sys.version_info[:2] == (3, 8)",
    reason="Seems to work on 3.8 but not via the CI",
)
def test_update_outdated_with_outdated_package(pipenv_instance_private_pypi, cmd_option):
    with pipenv_instance_private_pypi() as p:
        package_name = "six"
        p.pipenv(f"install {cmd_option} {package_name}==1.11")
        c = p.pipenv(f"update {package_name} {cmd_option} --outdated")
        assert f"Package '{package_name}' out-of-date:" in c.stdout


def test_get_modified_pipfile_entries_new_package(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        # Add package to Pipfile
        p.pipenv("install requests==2.31.0")

        # Add new package to Pipfile
        pipfile = p.pipfile_path
        content = pipfile.read_text()
        content = content.replace(
            '[packages]',
            '[packages]\nurllib3 = "==2.0.0"'
        )
        pipfile.write_text(content)
        project = Project()
        modified = get_modified_pipfile_entries(project, ["packages"])
        assert "urllib3" in modified["default"]


def test_get_modified_pipfile_entries_changed_version(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        # Install and lock initial version
        p.pipenv("install requests==2.31.0")

        # Update version in Pipfile
        pipfile = p.pipfile_path
        content = pipfile.read_text()
        content = content.replace(
            'requests = "==2.31.0"',
            'requests = "==2.32.0"'
        )
        pipfile.write_text(content)
        project = Project()
        modified = get_modified_pipfile_entries(project, ["packages"])
        assert "requests" in modified["default"]


def test_get_modified_pipfile_entries_vcs_changes(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        # Install VCS package
        p.pipenv("install git+https://github.com/requests/requests.git@main#egg=requests")

        # Change ref
        pipfile = p.pipfile_path
        content = pipfile.read_text()
        content = content.replace(
            'ref = "main"',
            'ref = "master"'
        )
        pipfile.write_text(content)
        project = Project()
        modified = get_modified_pipfile_entries(project, ["packages"])
        assert "requests" in modified["default"]


def test_update_without_lockfile(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        # Install without creating lockfile
        p.pipenv("install --skip-lock requests==2.31.0")

        # Update should work without existing lockfile
        c = p.pipenv("update requests")
        assert c.returncode == 0


@pytest.mark.parametrize(
    "initial_content,modified_content,expected_updates",
    [
        # Test no changes case
        (
            '[packages]\nrequests = "==2.31.0"',
            '[packages]\nrequests = "==2.31.0"',
            set()
        ),
        # Test version change
        (
            '[packages]\nrequests = "==2.31.0"',
            '[packages]\nrequests = "==2.32.0"',
            {"requests"}
        ),
        # Test multiple package changes
        (
            '[packages]\nrequests = "==2.31.0"',
            '[packages]\nrequests = "==2.32.0"\nurllib3 = "==2.0.0"',
            {"requests", "urllib3"}
        ),
        # Test dev packages
        (
            '[packages]\nrequests = "==2.31.0"\n[dev-packages]',
            '[packages]\nrequests = "==2.31.0"\n[dev-packages]\npytest = "==7.4.0"',
            {"pytest"}
        ),
        # Test VCS package
        (
            '[packages]\nrequests = {git = "https://github.com/requests/requests.git", ref = "main"}',
            '[packages]\nrequests = {git = "https://github.com/requests/requests.git", ref = "v2.31.0"}',
            {"requests"}
        ),
        # Test extras change
        (
            '[packages]\nrequests = {version = "==2.31.0", extras = ["security"]}',
            '[packages]\nrequests = {version = "==2.31.0", extras = ["security", "socks"]}',
            {"requests"}
        )
    ]
)
def test_update_modified_packages(pipenv_instance_pypi, initial_content, modified_content, expected_updates):
    with pipenv_instance_pypi() as p:
        # Write initial Pipfile
        p.pipfile_path.write_text(initial_content)
        p.pipenv("lock")  # Generate initial lockfile

        # Modify Pipfile
        p.pipfile_path.write_text(modified_content)

        project = Project()
        # Verify correct packages identified for update
        modified = get_modified_pipfile_entries(project, ["packages", "dev-packages"])
        all_modified = set()
        for category in modified.values():
            all_modified.update(entry if isinstance(entry, str) else entry.get("name", "") for entry in category)

        assert all_modified == expected_updates
