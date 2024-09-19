import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from pipenv.utils.constants import FALSE_VALUES, TRUE_VALUES
from pipenv.utils.shell import temp_environ


@pytest.mark.dotvenv
@pytest.mark.parametrize("true_value", TRUE_VALUES)
def test_venv_in_project(true_value, pipenv_instance_pypi):
    with temp_environ():
        os.environ["PIPENV_VENV_IN_PROJECT"] = true_value
        with pipenv_instance_pypi() as p:
            c = p.pipenv("install dataclasses-json")
            assert c.returncode == 0
            assert p.path in p.pipenv("--venv").stdout


@pytest.mark.dotvenv
@pytest.mark.parametrize("false_value", FALSE_VALUES)
def test_venv_in_project_disabled_ignores_venv(false_value, pipenv_instance_pypi):
    venv_name = "my_project"
    with temp_environ():
        os.environ["PIPENV_VENV_IN_PROJECT"] = false_value
        with pipenv_instance_pypi() as p:
            file_path = os.path.join(p.path, ".venv")
            with open(file_path, "w") as f:
                f.write(venv_name)

            with temp_environ(), TemporaryDirectory(
                prefix="pipenv-", suffix="temp_workon_home"
            ) as workon_home:
                os.environ["WORKON_HOME"] = workon_home
                c = p.pipenv("install dataclasses-json")
                assert c.returncode == 0
                c = p.pipenv("--venv")
                assert c.returncode == 0
                venv_loc = Path(c.stdout.strip()).resolve()
                assert venv_loc.exists()
                assert venv_loc.joinpath(".project").exists()
                venv_path = Path(venv_loc).resolve()
                venv_expected_path = Path(workon_home).joinpath(venv_name).resolve()
                assert os.path.samefile(venv_path, venv_expected_path)


@pytest.mark.dotvenv
@pytest.mark.parametrize("true_value", TRUE_VALUES)
def test_venv_at_project_root(true_value, pipenv_instance_pypi):
    with temp_environ(), pipenv_instance_pypi() as p:
        os.environ["PIPENV_VENV_IN_PROJECT"] = true_value
        c = p.pipenv("install")
        assert c.returncode == 0
        assert p.path in p.pipenv("--venv").stdout
        del os.environ["PIPENV_VENV_IN_PROJECT"]
        os.mkdir("subdir")
        os.chdir("subdir")
        # should still detect installed
        assert p.path in p.pipenv("--venv").stdout


@pytest.mark.dotvenv
@pytest.mark.parametrize("false_value", FALSE_VALUES)
def test_venv_in_project_disabled_with_existing_venv_dir(
    false_value, pipenv_instance_pypi
):
    venv_name = "my_project"
    with temp_environ(), pipenv_instance_pypi() as p, TemporaryDirectory(
        prefix="pipenv-", suffix="temp_workon_home"
    ) as workon_home:
        os.environ["PIPENV_VENV_IN_PROJECT"] = false_value
        os.environ["PIPENV_CUSTOM_VENV_NAME"] = venv_name
        os.environ["WORKON_HOME"] = workon_home
        os.mkdir(".venv")
        c = p.pipenv("install")
        assert c.returncode == 0
        c = p.pipenv("--venv")
        assert c.returncode == 0
        venv_loc = Path(c.stdout.strip()).resolve()
        assert venv_loc.exists()
        assert venv_loc.joinpath(".project").exists()
        venv_path = Path(venv_loc).resolve()
        venv_expected_path = Path(workon_home).joinpath(venv_name).resolve()
        assert os.path.samefile(venv_path, venv_expected_path)


@pytest.mark.dotvenv
def test_reuse_previous_venv(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        os.mkdir(".venv")
        c = p.pipenv("install dataclasses-json")
        assert c.returncode == 0
        assert p.path in p.pipenv("--venv").stdout


@pytest.mark.dotvenv
@pytest.mark.parametrize("venv_name", ("test-venv", os.path.join("foo", "test-venv")))
def test_venv_file(venv_name, pipenv_instance_pypi):
    """Tests virtualenv creation when a .venv file exists at the project root
    and contains a venv name.
    """
    with pipenv_instance_pypi() as p:
        file_path = os.path.join(p.path, ".venv")
        with open(file_path, "w") as f:
            f.write(venv_name)

        with temp_environ(), TemporaryDirectory(
            prefix="pipenv-", suffix="temp_workon_home"
        ) as workon_home:
            os.environ["WORKON_HOME"] = workon_home

            c = p.pipenv("install")
            assert c.returncode == 0

            c = p.pipenv("--venv")
            assert c.returncode == 0
            venv_loc = Path(c.stdout.strip()).resolve()
            assert venv_loc.exists()
            assert venv_loc.joinpath(".project").exists()
            venv_path = Path(venv_loc).resolve()
            if os.path.sep in venv_name:
                venv_expected_path = Path(p.path).joinpath(venv_name)
            else:
                venv_expected_path = Path(workon_home).joinpath(venv_name)
            assert venv_path == venv_expected_path.resolve()


@pytest.mark.dotvenv
def test_empty_venv_file(pipenv_instance_pypi):
    """Tests virtualenv creation when an empty .venv file exists at the project root"""
    with pipenv_instance_pypi() as p:
        file_path = os.path.join(p.path, ".venv")
        with open(file_path, "w"):
            pass

        with temp_environ(), TemporaryDirectory(
            prefix="pipenv-", suffix="temp_workon_home"
        ) as workon_home:
            os.environ["WORKON_HOME"] = workon_home

            c = p.pipenv("install")
            assert c.returncode == 0

            c = p.pipenv("--venv")
            assert c.returncode == 0
            venv_loc = Path(c.stdout.strip()).absolute()
            assert venv_loc.exists()
            assert venv_loc.joinpath(".project").exists()
            venv_path = Path(venv_loc)
            venv_path_parent = Path(venv_path.parent)
            assert venv_path_parent == Path(workon_home)


@pytest.mark.dotvenv
def test_venv_in_project_default_when_venv_exists(pipenv_instance_pypi):
    """Tests virtualenv creation when a .venv file exists at the project root."""
    with temp_environ(), pipenv_instance_pypi() as p, TemporaryDirectory(
        prefix="pipenv-", suffix="-test_venv"
    ) as venv_path:
        file_path = os.path.join(p.path, ".venv")
        with open(file_path, "w") as f:
            f.write(venv_path)

        c = p.pipenv("install")
        assert c.returncode == 0
        c = p.pipenv("--venv")
        assert c.returncode == 0
        venv_loc = Path(c.stdout.strip())

        assert venv_loc.joinpath(".project").exists()
        assert venv_loc == Path(venv_path)


@pytest.mark.dotenv
def test_venv_name_accepts_custom_name_environment_variable(pipenv_instance_pypi):
    """Tests that virtualenv reads PIPENV_CUSTOM_VENV_NAME and accepts it as a name"""
    with pipenv_instance_pypi() as p:
        test_name = "sensible_custom_venv_name"
        with temp_environ():
            os.environ["PIPENV_CUSTOM_VENV_NAME"] = test_name
            c = p.pipenv("install")
            assert c.returncode == 0
            c = p.pipenv("--venv")
            assert c.returncode == 0
            venv_path = c.stdout.strip()
            assert test_name == Path(venv_path).parts[-1]
