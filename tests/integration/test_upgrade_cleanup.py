
import pytest


@pytest.mark.upgrade
@pytest.mark.cleanup
def test_upgrade_removes_unused_dependencies(pipenv_instance_pypi):
    """Test that `pipenv upgrade` removes dependencies that are no longer needed."""
    with pipenv_instance_pypi() as p:
        # Create a Pipfile with Django 3.2.10 (which depends on pytz)
        with open(p.pipfile_path, "w") as f:
            f.write("""
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
django = "==3.2.10"

[dev-packages]

[requires]
python_version = "3.11"
""")

        # Install dependencies
        c = p.pipenv("install")
        assert c.returncode == 0

        # Verify pytz is in the lockfile
        assert "pytz" in p.lockfile["default"]

        # Upgrade Django to 4.2.7 (which doesn't depend on pytz)
        c = p.pipenv("upgrade django==4.2.7")
        assert c.returncode == 0

        # Verify pytz is no longer in the lockfile
        assert "pytz" not in p.lockfile["default"]
