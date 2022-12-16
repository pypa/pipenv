import pytest

@pytest.mark.parametrize("cmd_option", ["", "--dev"])
@pytest.mark.basic
@pytest.mark.update
def test_update_outdated_with_outdated_package(pipenv_instance_private_pypi, cmd_option):
    with pipenv_instance_private_pypi() as p:
        package_name = "six"
        p.pipenv(f"install {cmd_option} {package_name}==1.11")
        c = p.pipenv("update --outdated")
        assert isinstance(c.exception, SystemExit)
        assert c.stdout_bytes.decode("utf-8").startswith(f"Package '{package_name}' out-of-date:")
