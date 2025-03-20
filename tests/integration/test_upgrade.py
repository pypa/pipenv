import json
import os

import pytest
from pipenv.utils.dependencies import get_lockfile_section_using_pipfile_category


@pytest.mark.upgrade
def test_category_sorted_alphabetically_with_directive(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[pipenv]
sort_pipfile = true

[packages]
zipp = "*"
six = 1.11
colorama = "*"
atomicwrites = "*"
            """.strip()
            f.write(contents)

        package_name = "six"
        c = p.pipenv(f"upgrade {package_name}")
        assert c.returncode == 0
        assert list(p.pipfile["packages"].keys()) == [
            "atomicwrites",
            "colorama",
            "six",
            "zipp",
        ]


@pytest.mark.upgrade
def test_category_not_sorted_without_directive(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
zipp = "*"
six = 1.11
colorama = "*"
atomicwrites = "*"
            """.strip()
            f.write(contents)

        package_name = "six"
        c = p.pipenv(f"upgrade {package_name}")
        assert c.returncode == 0
        assert list(p.pipfile["packages"].keys()) == [
            "zipp",
            "colorama",
            "atomicwrites",
            "six",
        ]


@pytest.mark.cli
def test_pipenv_dependency_incompatibility_resolution(pipenv_instance_pypi):
    from pipenv.cli import cli
    from pipenv.vendor.click.testing import CliRunner

    with pipenv_instance_pypi() as p:
        # Step 1: Install initial dependency version
        c = p.pipenv("install google-api-core==2.18.0")
        assert c.returncode == 0, f"Failed to install google-api-core: {c.stderr}"

        # Ensure initial state
        lockfile_path = os.path.join(p.path, "Pipfile.lock")
        with open(lockfile_path) as lockfile:
            lock_data = json.load(lockfile)
        assert "google-api-core" in lock_data["default"]
        assert lock_data["default"]["google-api-core"]["version"] == "==2.18.0"

        # Step 2: Update Pipfile to allow any version of google-api-core
        pipfile_path = os.path.join(p.path, "Pipfile")
        with open(pipfile_path) as pipfile:
            pipfile_content = pipfile.read()

        updated_pipfile_content = pipfile_content.replace("google-api-core = \"==2.18.0\"", "google-api-core = \"*\"")
        with open(pipfile_path, "w") as pipfile:
            pipfile.write(updated_pipfile_content)

        # Step 3: Update protobuf to an incompatible version
        cli_runner = CliRunner(mix_stderr=False)
        c = cli_runner.invoke(cli, "update protobuf==5.27.5")
        assert c.exit_code == 0, f"Failed to update protobuf: {c.stderr}"

        # Step 4: Check the lockfile for incompatible dependencies
        with open(lockfile_path) as lockfile:
            lock_data = json.load(lockfile)

        # Check if google-api-core is still at the old version
        google_api_core_version = lock_data["default"].get("google-api-core", {}).get("version", "")
        protobuf_version = lock_data["default"].get("protobuf", {}).get("version", "")

        assert google_api_core_version != "==2.18.0", (
            "google-api-core was not updated to a compatible version despite the protobuf update"
        )
        assert protobuf_version == "==5.27.5", "protobuf was not updated correctly"

        # Step 5: Run pipenv lock to check for dependency resolution errors
        c = cli_runner.invoke(cli, "lock")
        assert c.exit_code == 0, f"Failed to run pipenv lock: {c.stderr}"


@pytest.mark.upgrade
def test_upgrade_updates_package_in_all_categories(pipenv_instance_private_pypi):
    """Test that upgrading a package updates it in all categories where it appears."""
    with pipenv_instance_private_pypi() as p:
        # Create a Pipfile with a package in multiple categories
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "==1.11.0"

[dev-packages]
six = "==1.11.0"

[custom-category]
six = "==1.11.0"
            """.strip()
            f.write(contents)
        
        # Lock the dependencies
        c = p.pipenv("lock")
        assert c.returncode == 0, f"Failed to lock dependencies: {c.stderr}"
        
        # Verify initial state
        lockfile_path = os.path.join(p.path, "Pipfile.lock")
        with open(lockfile_path) as lockfile:
            lock_data = json.load(lockfile)
        
        # Check initial versions in all categories
        assert lock_data["default"]["six"]["version"] == "==1.11.0"
        assert lock_data["develop"]["six"]["version"] == "==1.11.0"
        
        # Get the lockfile section for the custom category
        custom_section = get_lockfile_section_using_pipfile_category("custom-category")
        assert lock_data[custom_section]["six"]["version"] == "==1.11.0"
        
        # Upgrade the package
        target_version = "1.16.0"
        c = p.pipenv(f"upgrade six=={target_version}")
        assert c.returncode == 0, f"Failed to upgrade six: {c.stderr}"
        
        # Verify the package was updated in all categories
        with open(lockfile_path) as lockfile:
            updated_lock_data = json.load(lockfile)
        
        # Check updated versions in all categories
        assert updated_lock_data["default"]["six"]["version"] == f"=={target_version}"
        assert updated_lock_data["develop"]["six"]["version"] == f"=={target_version}"
        assert updated_lock_data[custom_section]["six"]["version"] == f"=={target_version}"
