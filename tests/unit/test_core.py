import os
from tempfile import TemporaryDirectory

import pytest

from pipenv.utils.environment import load_dot_env
from pipenv.utils.shell import temp_environ
from pipenv.utils.virtualenv import warn_in_virtualenv


@pytest.mark.core
def test_suppress_nested_venv_warning(capsys, project):
    # Capture the stderr of warn_in_virtualenv to test for the presence of the
    # courtesy notice.
    project.s.PIPENV_VIRTUALENV = "totallyrealenv"
    project.s.PIPENV_VERBOSITY = -1
    warn_in_virtualenv(project)
    output, err = capsys.readouterr()
    assert "Courtesy Notice" not in err


@pytest.mark.core
def test_load_dot_env_from_environment_variable_location(monkeypatch, capsys, project):
    with temp_environ(), monkeypatch.context() as m, TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
        if os.name == "nt":
            from pipenv.vendor import click

            is_console = False
            m.setattr(click._winconsole, "_is_console", lambda x: is_console)
        dotenv_path = os.path.join(tempdir, "test.env")
        key, val = "SOME_KEY", "some_value"
        with open(dotenv_path, "w") as f:
            f.write(f"{key}={val}")

        project.s.PIPENV_DOTENV_LOCATION = str(dotenv_path)
        load_dot_env(project)
        assert os.environ[key] == val


@pytest.mark.core
def test_doesnt_load_dot_env_if_disabled(monkeypatch, capsys, project):
    with temp_environ(), monkeypatch.context() as m, TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
        if os.name == "nt":
            from pipenv.vendor import click

            is_console = False
            m.setattr(click._winconsole, "_is_console", lambda x: is_console)
        dotenv_path = os.path.join(tempdir, "test.env")
        key, val = "SOME_KEY", "some_value"
        with open(dotenv_path, "w") as f:
            f.write(f"{key}={val}")

        project.s.PIPENV_DOTENV_LOCATION = str(dotenv_path)
        project.s.PIPENV_DONT_LOAD_ENV = True
        load_dot_env(project)
        assert key not in os.environ
        project.s.PIPENV_DONT_LOAD_ENV = False
        load_dot_env(project)
        assert key in os.environ


@pytest.mark.core
def test_load_dot_env_warns_if_file_doesnt_exist(monkeypatch, capsys, project):
    with temp_environ(), monkeypatch.context() as m, TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
        if os.name == "nt":
            from pipenv.vendor import click

            is_console = False
            m.setattr(click._winconsole, "_is_console", lambda x: is_console)
        dotenv_path = os.path.join(tempdir, "does-not-exist.env")
        project.s.PIPENV_DOTENV_LOCATION = str(dotenv_path)
        load_dot_env(project)
        output, err = capsys.readouterr()
        assert "Warning" in err
