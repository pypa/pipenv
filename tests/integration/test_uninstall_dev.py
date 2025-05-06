import pytest


@pytest.mark.install
@pytest.mark.uninstall
def test_uninstall_dev_flag(pipenv_instance_private_pypi):
    """Ensure that running `pipenv uninstall --dev` properly removes packages from dev-packages"""
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "*"

[dev-packages]
pytest = "*"
            """.strip()
            f.write(contents)
        
        # Install both packages
        c = p.pipenv("install --dev")
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert "pytest" in p.pipfile["dev-packages"]
        assert "six" in p.lockfile["default"]
        assert "pytest" in p.lockfile["develop"]
        
        # Verify both packages are installed
        c = p.pipenv('run python -c "import six, pytest"')
        assert c.returncode == 0
        
        # Uninstall pytest with --dev flag
        c = p.pipenv("uninstall pytest --dev")
        assert c.returncode == 0
        
        # Verify pytest was removed from dev-packages
        assert "six" in p.pipfile["packages"]
        assert "pytest" not in p.pipfile["dev-packages"]
        assert "six" in p.lockfile["default"]
        assert "pytest" not in p.lockfile["develop"]
        
        # Verify pytest is no longer importable
        c = p.pipenv('run python -c "import pytest"')
        assert c.returncode != 0
        
        # Verify six is still importable
        c = p.pipenv('run python -c "import six"')
        assert c.returncode == 0


@pytest.mark.install
@pytest.mark.uninstall
def test_uninstall_dev_flag_with_categories(pipenv_instance_private_pypi):
    """Ensure that running `pipenv uninstall --dev` works the same as `--categories dev-packages`"""
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
six = "*"

[dev-packages]
pytest = "*"
            """.strip()
            f.write(contents)
        
        # Install both packages
        c = p.pipenv("install --dev")
        assert c.returncode == 0
        
        # Create a second project to test with categories
        with pipenv_instance_private_pypi() as p2:
            with open(p2.pipfile_path, "w") as f:
                contents = """
[packages]
six = "*"

[dev-packages]
pytest = "*"
                """.strip()
                f.write(contents)
            
            # Install both packages
            c = p2.pipenv("install --dev")
            assert c.returncode == 0
            
            # Uninstall pytest with --categories
            c = p2.pipenv("uninstall pytest --categories dev-packages")
            assert c.returncode == 0
            
            # Verify pytest was removed from dev-packages
            assert "six" in p2.pipfile["packages"]
            assert "pytest" not in p2.pipfile["dev-packages"]
            assert "six" in p2.lockfile["default"]
            assert "pytest" not in p2.lockfile["develop"]
            
            # Compare with first project
            c = p.pipenv("uninstall pytest --dev")
            assert c.returncode == 0
            
            # Verify both approaches have the same result
            assert p.pipfile["packages"] == p2.pipfile["packages"]
            assert p.pipfile["dev-packages"] == p2.pipfile["dev-packages"]
            assert p.lockfile["default"] == p2.lockfile["default"]
            assert p.lockfile["develop"] == p2.lockfile["develop"]
