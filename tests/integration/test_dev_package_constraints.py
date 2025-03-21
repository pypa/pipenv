import os
import pytest

from pipenv.utils.shell import temp_environ


@pytest.mark.lock
@pytest.mark.dev
def test_dev_packages_respect_default_package_constraints(pipenv_instance_private_pypi):
    """
    Test that dev packages respect constraints from default packages.
    
    This test verifies the fix for the issue where pipenv may ignore install_requires
    from setup.py and lock incompatible versions. The specific case is when httpx is
    pinned in default packages and respx is in dev packages, respx should be locked
    to a version compatible with the httpx version.
    """
    with pipenv_instance_private_pypi() as p:
        # First test: explicit version constraint in Pipfile
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
httpx = "==0.24.1"

[dev-packages]
respx = "*"

[requires]
python_version = "3.9"
            """.strip()
            f.write(contents)

        c = p.pipenv("lock")
        assert c.returncode == 0
        
        # Verify httpx is locked to 0.24.1
        assert "httpx" in p.lockfile["default"]
        assert p.lockfile["default"]["httpx"]["version"] == "==0.24.1"
        
        # Verify respx is locked to a compatible version (0.21.1 is the last compatible version)
        assert "respx" in p.lockfile["develop"]
        assert p.lockfile["develop"]["respx"]["version"] == "==0.21.1"
        
        # Second test: implicit version constraint through another dependency
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
httpx = "*"
xrpl-py = ">=1.8.0"
websockets = ">=9.0.1,<11.0"

[dev-packages]
respx = "*"

[requires]
python_version = "3.9"
            """.strip()
            f.write(contents)
            
        c = p.pipenv("lock")
        assert c.returncode == 0
        
        # Verify httpx is still locked to 0.24.1 (due to constraints from other packages)
        assert "httpx" in p.lockfile["default"]
        assert p.lockfile["default"]["httpx"]["version"] == "==0.24.1"
        
        # Verify respx is still locked to a compatible version
        assert "respx" in p.lockfile["develop"]
        assert p.lockfile["develop"]["respx"]["version"] == "==0.21.1"
