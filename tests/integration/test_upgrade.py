import json
import os

import pytest


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
def test_upgrade_updates_lockfile_in_all_categories(pipenv_instance_private_pypi):
    """Test that upgrading a package updates it in all categories of the lockfile."""
    with pipenv_instance_private_pypi() as p:
        # Create a Pipfile with a package in default and a dev package that depends on it
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
requests = "==2.25.0"

[dev-packages]
pytest = "*"
            """.strip()
            f.write(contents)

        # Lock the dependencies
        c = p.pipenv("lock")
        assert c.returncode == 0, f"Failed to lock dependencies: {c.stderr}"

        # Verify initial state
        lockfile_path = os.path.join(p.path, "Pipfile.lock")
        with open(lockfile_path) as lockfile:
            lock_data = json.load(lockfile)

        # Check initial version in default section
        assert lock_data["default"]["requests"]["version"] == "==2.25.0"

        # Check if requests is in develop section (as a dependency of pytest)
        develop_has_requests = "requests" in lock_data["develop"]

        # Upgrade the package
        target_version = "2.28.0"
        c = p.pipenv(f"upgrade requests=={target_version}")
        assert c.returncode == 0, f"Failed to upgrade requests: {c.stderr}"

        # Verify the package was updated in the lockfile
        with open(lockfile_path) as lockfile:
            updated_lock_data = json.load(lockfile)

        # Check updated version in default section
        assert updated_lock_data["default"]["requests"]["version"] == f"=={target_version}"

        # If requests was in develop section, check it was updated there too
        if develop_has_requests:
            assert updated_lock_data["develop"]["requests"]["version"] == f"=={target_version}"


@pytest.mark.upgrade
def test_upgrade_only_adds_to_explicit_categories(pipenv_instance_private_pypi):
    """Test that upgrading a package only adds it to the Pipfile for explicitly requested categories."""
    with pipenv_instance_private_pypi() as p:
        # Create a Pipfile with a package in default but not in dev-packages
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
requests = "==2.25.0"

[dev-packages]
pytest = "*"
            """.strip()
            f.write(contents)

        # Lock the dependencies
        c = p.pipenv("lock")
        assert c.returncode == 0, f"Failed to lock dependencies: {c.stderr}"

        # Verify initial state
        with open(p.pipfile_path) as pipfile:
            initial_pipfile_content = pipfile.read()

        # Make sure requests is not in dev-packages initially
        assert "requests" not in initial_pipfile_content.split("[dev-packages]")[1].split("[")[0]

        # Upgrade the package
        target_version = "2.28.0"
        c = p.pipenv(f"upgrade requests=={target_version}")
        assert c.returncode == 0, f"Failed to upgrade requests: {c.stderr}"

        # Verify the Pipfile was updated correctly
        with open(p.pipfile_path) as pipfile:
            updated_pipfile_content = pipfile.read()

        # Check that requests was updated in packages section
        packages_section = updated_pipfile_content.split("[packages]")[1].split("[")[0]
        assert f'requests = "=={target_version}"' in packages_section

        # Check that requests was NOT added to dev-packages section
        if "[dev-packages]" in updated_pipfile_content:
            dev_packages_section = updated_pipfile_content.split("[dev-packages]")[1].split("[")[0]
        else:
            dev_packages_section = ""
        assert "requests" not in dev_packages_section

        # Verify the lockfile was updated in both sections
        lockfile_path = os.path.join(p.path, "Pipfile.lock")
        with open(lockfile_path) as lockfile:
            updated_lock_data = json.load(lockfile)

        # Check that requests was updated in default section
        assert updated_lock_data["default"]["requests"]["version"] == f"=={target_version}"

        # Check if requests is in develop section (it might be there as a dependency of pytest)
        if "requests" in updated_lock_data["develop"]:
            # If it's there, it should be updated
            assert updated_lock_data["develop"]["requests"]["version"] == f"=={target_version}"
