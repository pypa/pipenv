from pathlib import Path

import pytest


@pytest.mark.install
@pytest.mark.needs_internet
def test_install_path_with_spaces(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        # Create a test directory with spaces in the name
        test_dir = Path(p.path) / "test dir with spaces"
        test_dir.mkdir()

        # Create a simple package in the directory with spaces
        package_dir = test_dir / "simple_package"
        package_dir.mkdir()

        # Create a simple setup.py file
        with open(package_dir / "setup.py", "w") as f:
            f.write("""
from setuptools import setup

setup(
    name="simple-package",
    version="0.1.0",
)
""")

        # Create the package module
        with open(package_dir / "simple_package.py", "w") as f:
            f.write("""
def hello():
    return "Hello from simple package!"
""")

        # Install the package using a path with spaces
        # Use both escaped spaces and quoted path to test both scenarios
        c = p.pipenv(f'install "{test_dir}/simple_package"')
        assert c.returncode == 0

        # Verify the package was installed correctly
        c = p.pipenv('run python -c "import simple_package; print(simple_package.hello())"')
        assert c.returncode == 0
        assert "Hello from simple package!" in c.stdout

        # Test with escaped spaces
        p.pipenv("uninstall simple-package")
        escaped_path = str(test_dir / "simple_package").replace(" ", "\\ ")
        c = p.pipenv(f'install {escaped_path}')
        assert c.returncode == 0

        # Verify the package was installed correctly
        c = p.pipenv('run python -c "import simple_package; print(simple_package.hello())"')
        assert c.returncode == 0
        assert "Hello from simple package!" in c.stdout
