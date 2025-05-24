import os
from pathlib import Path

import pytest


@pytest.mark.install
@pytest.mark.needs_internet
@pytest.mark.skipif(
    os.name == "nt",
    reason="This test is not for Windows",
)
def test_install_path_with_nested_setup_module(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        # Create a simple package.
        package_dir = Path(p.path) / "simple_package"
        package_dir.mkdir()

        # Create a simple setup.py file
        with open(package_dir / "setup.py", "w") as f:
            f.write("""
from setuptools import setup, find_packages

setup(
    name="simple-package",
    version="0.1.0",
    packages=find_packages(),
)
""")
        module_dir = package_dir / "simple_package"
        module_dir.mkdir()

        (module_dir / "__init__.py").touch()

        # Create the package module
        with open(module_dir / "setup.py", "w") as f:
            f.write("""
def setup(name = ''):
    return f'Setup package {name}'

def configure():
    return setup(name='my_simple_package')
""")

        # Install the package using a path with spaces
        # Use both escaped spaces and quoted path to test both scenarios
        relative_package_dir = package_dir.relative_to(p.path)
        c = p.pipenv(f'install -e {relative_package_dir}')
        assert c.returncode == 0

        # Verify the package was installed correctly
        c = p.pipenv('run python -c "'
                     'from simple_package import setup; '
                     'print(setup.configure())"')
        assert c.returncode == 0
        assert "Setup package my_simple_package" in c.stdout

        # Ensure my_simple_package was not parsed from the setup.py module
        # inside the package.
        with open(Path(p.path) / "Pipfile") as f:
            assert "my_simple_package" not in f.read()
