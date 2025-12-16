import os
from tempfile import TemporaryDirectory

import pytest

from pipenv.shells import _get_deactivate_wrapper_script
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
        assert "WARNING" in err.upper()


@pytest.mark.core
def test_load_dot_env_quiet_with_verbosity(monkeypatch, capsys, project):
    """Test that PIPENV_VERBOSITY=-1 suppresses the .env loading message."""
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
        # Set verbosity to -1 (quiet mode via environment variable)
        project.s.PIPENV_VERBOSITY = -1
        load_dot_env(project)
        output, err = capsys.readouterr()
        # The .env file should still be loaded
        assert os.environ[key] == val
        # But the "Loading .env" message should be suppressed
        assert "Loading .env" not in err


@pytest.mark.core
def test_load_dot_env_shows_message_without_quiet(monkeypatch, capsys, project):
    """Test that the .env loading message is shown when not in quiet mode."""
    with temp_environ(), monkeypatch.context() as m, TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
        if os.name == "nt":
            from pipenv.vendor import click

            is_console = False
            m.setattr(click._winconsole, "_is_console", lambda x: is_console)
        dotenv_path = os.path.join(tempdir, "test.env")
        key, val = "ANOTHER_KEY", "another_value"
        with open(dotenv_path, "w") as f:
            f.write(f"{key}={val}")

        project.s.PIPENV_DOTENV_LOCATION = str(dotenv_path)
        # Ensure verbosity is at default (0)
        project.s.PIPENV_VERBOSITY = 0
        # Ensure PIPENV_ACTIVE is not set
        os.environ.pop("PIPENV_ACTIVE", None)
        load_dot_env(project)
        output, err = capsys.readouterr()
        # The .env file should be loaded
        assert os.environ[key] == val
        # And the "Loading .env" message should be shown
        assert "Loading .env" in err


@pytest.mark.core
def test_load_dot_env_suppresses_message_when_pipenv_active(monkeypatch, capsys, project):
    """Test that the .env loading message is suppressed when PIPENV_ACTIVE is set.

    This handles nested pipenv invocations (e.g., `pipenv run` executing a script
    that itself runs pipenv commands). The .env should still be loaded, but the
    message should not be printed again.

    Fixes #6328
    """
    with temp_environ(), monkeypatch.context() as m, TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
        if os.name == "nt":
            from pipenv.vendor import click

            is_console = False
            m.setattr(click._winconsole, "_is_console", lambda x: is_console)
        dotenv_path = os.path.join(tempdir, "test.env")
        key, val = "NESTED_KEY", "nested_value"
        with open(dotenv_path, "w") as f:
            f.write(f"{key}={val}")

        project.s.PIPENV_DOTENV_LOCATION = str(dotenv_path)
        # Ensure verbosity is at default (0) - message would normally show
        project.s.PIPENV_VERBOSITY = 0
        # Set PIPENV_ACTIVE to simulate nested pipenv invocation
        os.environ["PIPENV_ACTIVE"] = "1"
        load_dot_env(project)
        output, err = capsys.readouterr()
        # The .env file should still be loaded
        assert os.environ[key] == val
        # But the "Loading .env" message should be suppressed
        assert "Loading .env" not in err


@pytest.mark.core
def test_deactivate_wrapper_script_includes_unset_pipenv_active():
    """Test that deactivate wrapper scripts include 'unset PIPENV_ACTIVE' or equivalent."""
    # Test bash - should use 'declare -f' to copy function and 'unset PIPENV_ACTIVE'
    bash_script = _get_deactivate_wrapper_script("bash")
    assert "unset PIPENV_ACTIVE" in bash_script
    assert "_pipenv_old_deactivate" in bash_script
    assert "declare -f" in bash_script

    # Test zsh - should use 'functions -c' to copy function (not 'declare -f' which fails in zsh)
    # See: https://github.com/pypa/pipenv/issues/6503
    zsh_script = _get_deactivate_wrapper_script("zsh")
    assert "unset PIPENV_ACTIVE" in zsh_script
    assert "_pipenv_old_deactivate" in zsh_script
    assert "functions -c" in zsh_script
    assert "declare -f" not in zsh_script  # zsh doesn't handle this in eval correctly

    # Test fish - should use 'set -e PIPENV_ACTIVE'
    fish_script = _get_deactivate_wrapper_script("fish")
    assert "set -e PIPENV_ACTIVE" in fish_script
    assert "_pipenv_old_deactivate" in fish_script

    # Test csh - should use 'unsetenv PIPENV_ACTIVE'
    csh_script = _get_deactivate_wrapper_script("csh")
    assert "unsetenv PIPENV_ACTIVE" in csh_script

    # Test plain sh - should have unset PIPENV_ACTIVE
    sh_script = _get_deactivate_wrapper_script("sh")
    assert "unset PIPENV_ACTIVE" in sh_script

    # Test powershell - should use Remove-Item Env:PIPENV_ACTIVE
    pwsh_script = _get_deactivate_wrapper_script("pwsh")
    assert "PIPENV_ACTIVE" in pwsh_script
    assert "Remove-Item" in pwsh_script

    # Test unknown shell - should return empty string
    unknown_script = _get_deactivate_wrapper_script("unknown_shell")
    assert unknown_script == ""

    # Test nushell - returns empty for now (different paradigm)
    nu_script = _get_deactivate_wrapper_script("nu")
    assert nu_script == ""
