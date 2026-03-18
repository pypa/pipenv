import os
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from pipenv.shells import _get_activate_script, _get_deactivate_wrapper_script
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


# ---------------------------------------------------------------------------
# Tests for _parse_pip_conf_indexes (pip.conf support – GH #5710)
# ---------------------------------------------------------------------------


def _make_configuration(flat_conf: dict, trusted_host_map: dict | None = None):
    """Build a minimal mock of pip's Configuration that satisfies
    _parse_pip_conf_indexes.

    :param flat_conf: dict mapping "section.key" → value, e.g.
        ``{"global.index-url": "https://example.com/simple"}``
    :param trusted_host_map: dict mapping "section.trusted-host" → string
        value (space-separated if multiple hosts), used by get_value.
    """
    from pipenv.patched.pip._internal.exceptions import ConfigurationError

    trusted_host_map = trusted_host_map or {}

    configuration = MagicMock()
    # _dictionary returns {filename: {section.key: value}}; wrap in one file
    configuration._dictionary = {"fake_pip.conf": flat_conf}

    def _get_value(key):
        if key in flat_conf:
            return flat_conf[key]
        if key in trusted_host_map:
            return trusted_host_map[key]
        raise ConfigurationError(f"No such key - {key}")

    configuration.get_value.side_effect = _get_value
    return configuration


class TestParsePipConfIndexes:
    """Unit tests for _parse_pip_conf_indexes."""

    def _call(self, flat_conf, trusted_host_map=None):
        from pipenv.project import _parse_pip_conf_indexes

        configuration = _make_configuration(flat_conf, trusted_host_map)
        return _parse_pip_conf_indexes(configuration)

    # ------------------------------------------------------------------
    # index-url
    # ------------------------------------------------------------------

    def test_index_url_https_verify_ssl_true(self):
        indexes, extras = self._call(
            {"global.index-url": "https://pypi.example.com/simple"}
        )
        assert len(indexes) == 1
        assert indexes[0]["url"] == "https://pypi.example.com/simple"
        assert indexes[0]["verify_ssl"] is True
        assert indexes[0]["name"] == "pip_conf_index_global"
        assert extras == []

    def test_index_url_http_verify_ssl_false(self):
        indexes, extras = self._call(
            {"global.index-url": "http://internal.repo/simple"}
        )
        assert len(indexes) == 1
        assert indexes[0]["verify_ssl"] is False

    def test_index_url_trusted_host_disables_verify_ssl(self):
        """When the host appears in trusted-host, verify_ssl must be False."""
        indexes, _ = self._call(
            {"global.index-url": "https://private.repo/simple"},
            trusted_host_map={"global.trusted-host": "private.repo"},
        )
        assert indexes[0]["verify_ssl"] is False

    def test_index_url_trusted_host_multiple_hosts_string(self):
        """trusted-host with space-separated hosts – only matching host disables SSL."""
        indexes, _ = self._call(
            {"global.index-url": "https://other.repo/simple"},
            trusted_host_map={
                "global.trusted-host": "private.repo other.repo yetanother.repo"
            },
        )
        assert indexes[0]["verify_ssl"] is False

    def test_index_url_trusted_host_newline_separated(self):
        """trusted-host with newline-separated hosts (pip multi-line config)."""
        indexes, _ = self._call(
            {"global.index-url": "https://other.repo/simple"},
            trusted_host_map={"global.trusted-host": "private.repo\nother.repo"},
        )
        assert indexes[0]["verify_ssl"] is False

    def test_index_url_non_matching_trusted_host_keeps_verify_ssl(self):
        """A trusted-host that does not match the index URL must not affect verify_ssl."""
        indexes, _ = self._call(
            {"global.index-url": "https://other.repo/simple"},
            trusted_host_map={"global.trusted-host": "unrelated.repo"},
        )
        assert indexes[0]["verify_ssl"] is True

    # ------------------------------------------------------------------
    # extra-index-url
    # ------------------------------------------------------------------

    def test_extra_index_url_single(self):
        """A single extra-index-url is returned in pip_conf_extra_indexes."""
        indexes, extras = self._call(
            {"global.extra-index-url": "https://extra.repo/simple"}
        )
        assert indexes == []
        assert len(extras) == 1
        assert extras[0]["url"] == "https://extra.repo/simple"
        assert extras[0]["verify_ssl"] is True
        assert extras[0]["name"] == "pip_conf_extra_index_global"

    def test_extra_index_url_multiple_space_separated(self):
        """Multiple whitespace-separated URLs in extra-index-url become separate entries."""
        _, extras = self._call(
            {
                "global.extra-index-url": (
                    "https://repo1.example.com/simple https://repo2.example.com/simple"
                )
            }
        )
        assert len(extras) == 2
        assert extras[0]["url"] == "https://repo1.example.com/simple"
        assert extras[0]["name"] == "pip_conf_extra_index_global_0"
        assert extras[1]["url"] == "https://repo2.example.com/simple"
        assert extras[1]["name"] == "pip_conf_extra_index_global_1"

    def test_extra_index_url_multiple_newline_separated(self):
        """Newline-separated URLs (pip multi-line) also expand to separate entries."""
        _, extras = self._call(
            {
                "global.extra-index-url": (
                    "https://repo1.example.com/simple\nhttps://repo2.example.com/simple"
                )
            }
        )
        assert len(extras) == 2

    def test_extra_index_url_trusted_host(self):
        """trusted-host applies to extra-index-url entries too."""
        _, extras = self._call(
            {"global.extra-index-url": "https://private.repo/simple"},
            trusted_host_map={"global.trusted-host": "private.repo"},
        )
        assert extras[0]["verify_ssl"] is False

    # ------------------------------------------------------------------
    # Combined index-url + extra-index-url
    # ------------------------------------------------------------------

    def test_index_url_and_extra_index_url_together(self):
        """Both index-url and extra-index-url can be present simultaneously."""
        indexes, extras = self._call(
            {
                "global.index-url": "https://pypi.example.com/simple",
                "global.extra-index-url": "https://extra.repo/simple",
            }
        )
        assert len(indexes) == 1
        assert len(extras) == 1
        assert indexes[0]["url"] == "https://pypi.example.com/simple"
        assert extras[0]["url"] == "https://extra.repo/simple"

    # ------------------------------------------------------------------
    # Empty / no relevant keys
    # ------------------------------------------------------------------

    def test_empty_config_returns_empty_lists(self):
        indexes, extras = self._call({})
        assert indexes == []
        assert extras == []

    def test_irrelevant_keys_are_ignored(self):
        indexes, extras = self._call(
            {"global.timeout": "60", "global.retries": "5"}
        )
        assert indexes == []
        assert extras == []


@pytest.mark.core
def test_get_activate_script_windows_full_path():
    """Test that _get_activate_script handles Windows full paths with .exe extension.

    On Windows, shellingham returns the full path to the shell executable, e.g.
    'C:\\Program Files\\PowerShell\\7\\pwsh.exe'. The function must correctly
    identify the shell from the path stem, not the endswith check.
    See: https://github.com/pypa/pipenv/issues/6532
    """
    venv = "/path/to/venv"

    # PowerShell 7 (pwsh) - Windows full path
    script = _get_activate_script(
        r"C:\Program Files\PowerShell\7\pwsh.exe", venv
    )
    assert ".ps1" in script

    # Windows PowerShell (powershell) - Windows full path
    script = _get_activate_script(
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", venv
    )
    assert ".ps1" in script

    # Bare shell names still work (POSIX-style)
    script = _get_activate_script("pwsh", venv)
    assert ".ps1" in script

    script = _get_activate_script("powershell", venv)
    assert ".ps1" in script


@pytest.mark.core
def test_get_deactivate_wrapper_script_windows_full_path():
    """Test that _get_deactivate_wrapper_script handles Windows full paths with .exe extension.

    See: https://github.com/pypa/pipenv/issues/6532
    """
    # PowerShell 7 (pwsh) - Windows full path
    script = _get_deactivate_wrapper_script(
        r"C:\Program Files\PowerShell\7\pwsh.exe"
    )
    assert "PIPENV_ACTIVE" in script
    assert "Remove-Item" in script

    # Windows PowerShell (powershell) - Windows full path
    script = _get_deactivate_wrapper_script(
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )
    assert "PIPENV_ACTIVE" in script
    assert "Remove-Item" in script
