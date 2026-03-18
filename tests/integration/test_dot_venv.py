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


@pytest.mark.dotvenv
def test_rm_prefers_workon_home_venv_over_dot_venv_dir(pipenv_instance_pypi):
    """Regression test for https://github.com/pypa/pipenv/issues/6331.

    When a pipenv-managed virtualenv already exists in WORKON_HOME and the user
    independently creates a .venv directory (e.g. via `python -m venv .venv`),
    `pipenv --rm` must remove the pipenv-managed venv, not the user-created .venv.
    """
    with temp_environ(), pipenv_instance_pypi() as p, TemporaryDirectory(
        prefix="pipenv-", suffix="temp_workon_home"
    ) as workon_home:
        os.environ["WORKON_HOME"] = workon_home
        # Step 1: create the pipenv-managed virtualenv in WORKON_HOME.
        c = p.pipenv("install")
        assert c.returncode == 0
        c = p.pipenv("--venv")
        assert c.returncode == 0
        pipenv_venv = Path(c.stdout.strip())
        assert pipenv_venv.exists()
        assert str(pipenv_venv).startswith(workon_home)

        # Step 2: user independently creates a .venv dir in the project root.
        dot_venv = Path(p.path) / ".venv"
        dot_venv.mkdir()

        # Step 3: `--venv` should still report the pipenv-managed venv.
        c = p.pipenv("--venv")
        assert c.returncode == 0
        reported_venv = Path(c.stdout.strip())
        assert reported_venv == pipenv_venv, (
            f"Expected pipenv-managed venv {pipenv_venv}, got {reported_venv}"
        )

        # Step 4: `--rm` must remove the pipenv-managed venv, not .venv.
        c = p.pipenv("--rm")
        assert c.returncode == 0
        assert not pipenv_venv.exists(), "pipenv-managed venv should have been removed"
        assert dot_venv.exists(), "user-created .venv dir must NOT be removed"


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



@pytest.mark.dotvenv
def test_venv_in_project_via_pipfile_directive(pipenv_instance_pypi):
    """Test that [pipenv] venv_in_project = true in Pipfile creates venv in project."""
    with temp_environ():
        os.environ.pop("PIPENV_VENV_IN_PROJECT", None)
        with pipenv_instance_pypi() as p:
            with open(p.pipfile_path, "w") as f:
                f.write(
                    """
[pipenv]
venv_in_project = true

[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]

[dev-packages]
""".strip()
                )
            c = p.pipenv("install")
            assert c.returncode == 0
            c = p.pipenv("--venv")
            assert c.returncode == 0
            assert p.path in c.stdout


@pytest.mark.dotvenv
def test_venv_in_project_env_var_overrides_pipfile_directive(pipenv_instance_pypi):
    """Test that PIPENV_VENV_IN_PROJECT=0 overrides Pipfile venv_in_project=true."""
    with temp_environ():
        os.environ["PIPENV_VENV_IN_PROJECT"] = "0"
        with pipenv_instance_pypi() as p:
            with open(p.pipfile_path, "w") as f:
                f.write(
                    """
[pipenv]
venv_in_project = true

[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]

[dev-packages]
""".strip()
                )
            c = p.pipenv("install")
            assert c.returncode == 0
            c = p.pipenv("--venv")
            assert c.returncode == 0
            # venv should NOT be in the project directory
            assert p.path not in c.stdout
