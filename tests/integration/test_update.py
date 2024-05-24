import pytest


@pytest.mark.parametrize("cmd_option", ["", "--dev"])
@pytest.mark.basic
@pytest.mark.update
@pytest.mark.skipif(
    "os.name == 'nt' and sys.version_info[:2] == (3, 8)",
    reason="Seems to work on 3.8 but not via the CI"
)
def test_update_outdated_with_outdated_package(pipenv_instance_private_pypi, cmd_option):
    with pipenv_instance_private_pypi() as p:
        package_name = "six"
        p.pipenv(f"install {cmd_option} {package_name}==1.11")
        c = p.pipenv(f"update {package_name} {cmd_option} --outdated")
        assert f"Package '{package_name}' out-of-date:" in c.stdout
