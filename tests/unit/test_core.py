import os
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from pipenv.project import NON_CATEGORY_SECTIONS
from pipenv.shells import _get_activate_script, _get_deactivate_wrapper_script
from pipenv.utils.environment import load_dot_env
from pipenv.utils.shell import temp_environ
from pipenv.utils.virtualenv import warn_in_virtualenv
from pipenv.vendor import shellingham


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
    with temp_environ(), monkeypatch.context(), TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
        dotenv_path = os.path.join(tempdir, "test.env")
        key, val = "SOME_KEY", "some_value"
        with open(dotenv_path, "w") as f:
            f.write(f"{key}={val}")

        project.s.PIPENV_DOTENV_LOCATION = str(dotenv_path)
        load_dot_env(project)
        assert os.environ[key] == val


@pytest.mark.core
def test_doesnt_load_dot_env_if_disabled(monkeypatch, capsys, project):
    with temp_environ(), monkeypatch.context(), TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
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
    with temp_environ(), monkeypatch.context(), TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
        dotenv_path = os.path.join(tempdir, "does-not-exist.env")
        project.s.PIPENV_DOTENV_LOCATION = str(dotenv_path)
        load_dot_env(project)
        output, err = capsys.readouterr()
        assert "WARNING" in err.upper()


@pytest.mark.core
def test_load_dot_env_quiet_with_verbosity(monkeypatch, capsys, project):
    """Test that PIPENV_VERBOSITY=-1 suppresses the .env loading message."""
    with temp_environ(), monkeypatch.context(), TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
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
    with temp_environ(), monkeypatch.context(), TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
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
    with temp_environ(), monkeypatch.context(), TemporaryDirectory(
        prefix="pipenv-", suffix=""
    ) as tempdir:
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
@pytest.mark.skipif(os.name == "nt", reason="PTY/pexpect not available on Windows")
def test_fork_compat_sentinel_restores_echo():
    """Regression test for GH-6572 and GH-3615.

    GH-6572: fork_compat must re-enable PTY echo.  In Docker / pty-over-pty
    environments the shell's own readline initialisation can race with our
    setecho(True) call, leaving echo permanently disabled.

    GH-3615: fork_compat must wait for the shell to finish its startup
    (including any interactive prompts like oh-my-zsh's update dialogue)
    before sending the activate script.

    The fix sends a startup sentinel ``echo __PIPENV_STARTUP_READY__`` and
    blocks on ``c.expect(sentinel)`` *before* activating, then sends a
    second sentinel ``echo __PIPENV_SHELL_READY__`` *after* all setup
    commands and blocks again before re-enabling echo.

    This test verifies both sentinels are performed and that setecho is
    called in the correct order (False → startup sentinel → activate →
    ready sentinel → True) using a mock pexpect child.
    """
    from pipenv.shells import Shell

    shell = Shell("/bin/bash")

    # Build a mock pexpect child that simulates the sentinel handshake.
    mock_child = MagicMock()
    mock_child.setecho.return_value = None
    mock_child.expect.return_value = 0  # sentinel found
    mock_child.interact.return_value = None
    mock_child.exitstatus = 0

    call_order = []

    def _setecho(state):
        call_order.append(("setecho", state))

    def _sendline(line):
        call_order.append(("sendline", line))

    def _expect(pattern, timeout=30):
        call_order.append(("expect", pattern))
        return 0

    mock_child.setecho.side_effect = _setecho
    mock_child.sendline.side_effect = _sendline
    mock_child.expect.side_effect = _expect

    with patch("pipenv.vendor.pexpect.spawn", return_value=mock_child), \
         patch("pipenv.shells._get_activate_script", return_value="source /venv/bin/activate"), \
         patch("pipenv.shells._get_deactivate_wrapper_script", return_value=""), \
         patch("pipenv.shells.get_terminal_size") as mock_size, \
         patch("pipenv.shells.temp_environ"), \
         patch("pipenv.shells.signal.signal"), \
         patch("sys.exit"):
        mock_size.return_value = MagicMock(lines=24, columns=80)

        shell.fork_compat("/path/to/venv", "/project", [])

    # Verify setecho(False) was called before any sendline.
    setecho_false_idx = next(
        i for i, item in enumerate(call_order) if item == ("setecho", False)
    )
    first_sendline_idx = next(
        i for i, item in enumerate(call_order) if item[0] == "sendline"
    )
    assert setecho_false_idx < first_sendline_idx, (
        "setecho(False) must be called before any sendline"
    )

    # Verify the startup sentinel was sent and expected *before* activate.
    startup_send = [item for item in call_order if item[0] == "sendline" and "__PIPENV_STARTUP_READY__" in item[1]]
    assert startup_send, "Startup sentinel must be sent via sendline"

    startup_expect = [item for item in call_order if item[0] == "expect" and "__PIPENV_STARTUP_READY__" in str(item[1])]
    assert startup_expect, "Startup sentinel must be waited for via expect"

    startup_expect_idx = next(
        i for i, item in enumerate(call_order) if item[0] == "expect" and "__PIPENV_STARTUP_READY__" in str(item[1])
    )
    activate_idx = next(
        i for i, item in enumerate(call_order) if item == ("sendline", "source /venv/bin/activate")
    )
    assert startup_expect_idx < activate_idx, (
        "Startup sentinel expect must complete before the activate script is sent (GH-3615)"
    )

    # Verify the ready sentinel was sent and expected *after* activate.
    ready_send = [item for item in call_order if item[0] == "sendline" and "__PIPENV_SHELL_READY__" in item[1]]
    assert ready_send, "Ready sentinel must be sent via sendline"

    ready_expect = [item for item in call_order if item[0] == "expect" and "__PIPENV_SHELL_READY__" in str(item[1])]
    assert ready_expect, "Ready sentinel must be waited for via expect"

    ready_expect_idx = next(
        i for i, item in enumerate(call_order) if item[0] == "expect" and "__PIPENV_SHELL_READY__" in str(item[1])
    )
    assert activate_idx < ready_expect_idx, (
        "Ready sentinel expect must happen after the activate script"
    )

    # Verify ready sentinel expect happens before setecho(True).
    setecho_true_idx = next(
        i for i, item in enumerate(call_order) if item == ("setecho", True)
    )
    assert ready_expect_idx < setecho_true_idx, (
        "Ready sentinel expect must complete before setecho(True) to avoid the race condition"
    )


@pytest.mark.core
def test_install_uses_metadata_name_for_headers():
    """Regression test for GH-5717: headers directory must use the wheel's
    own metadata name (original casing) rather than the canonicalised/
    lowercased requirement name that comes from the lockfile.

    Example: CPyCppyy is stored as 'cpycppyy' in the lockfile (due to
    normalize_name() in format_requirement_for_lockfile), so self.req.name
    is 'cpycppyy'.  But the wheel's METADATA has 'Name: CPyCppyy'.
    The headers must land in …/include/site/pythonX.Y/CPyCppyy/ not
    …/cpycppyy/ so that downstream consumers (cppyy) can find them.

    The fix reads self.metadata["Name"] from the wheel and passes that as
    dist_name to get_scheme() and install_wheel(), overriding the lowercase
    req.name.
    """
    from pipenv.patched.pip._internal.req.req_install import InstallRequirement

    captured = {}

    def fake_get_scheme(dist_name, **kwargs):
        captured["dist_name"] = dist_name
        return MagicMock()

    def fake_install_wheel(name, *args, **kwargs):
        captured["install_name"] = name

    mock_req = MagicMock()
    mock_req.name = "cpycppyy"  # lowercase — as stored in the lockfile

    ireq = InstallRequirement.__new__(InstallRequirement)
    ireq.req = mock_req
    ireq.isolated = False
    ireq.local_file_path = "/fake/CPyCppyy-1.12.13-cp312-cp312-linux_x86_64.whl"
    ireq.install_succeeded = None
    ireq.user_supplied = True

    # is_wheel, is_direct, and metadata are all read-only properties on
    # InstallRequirement, so they must be patched at the class level.
    # metadata returns a dict-like object mimicking the wheel's METADATA file.
    metadata_mock = {"Name": "CPyCppyy"}
    with patch.object(
        InstallRequirement, "is_wheel", new_callable=PropertyMock, return_value=True
    ), patch.object(
        InstallRequirement, "is_direct", new_callable=PropertyMock, return_value=False
    ), patch.object(
        InstallRequirement, "metadata", new_callable=PropertyMock, return_value=metadata_mock
    ), patch(
        "pipenv.patched.pip._internal.req.req_install.get_scheme",
        side_effect=fake_get_scheme,
    ), patch(
        "pipenv.patched.pip._internal.req.req_install.install_wheel",
        side_effect=fake_install_wheel,
    ):
        ireq.install()

    assert captured["dist_name"] == "CPyCppyy", (
        f"get_scheme should receive 'CPyCppyy' (from wheel metadata) not {captured['dist_name']!r}"
    )
    assert captured["install_name"] == "CPyCppyy", (
        f"install_wheel should receive 'CPyCppyy' (from wheel metadata) not {captured['install_name']!r}"
    )


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


# ── Tests for [build-system] support (issue #3651) ──────────────────────────


@pytest.mark.core
def test_build_system_excluded_from_non_category_sections():
    """[build-system] must be listed in NON_CATEGORY_SECTIONS so it is never
    treated as a package category by get_package_categories."""
    assert "build-system" in NON_CATEGORY_SECTIONS


@pytest.mark.core
def test_pipfile_build_requires_empty_when_no_section(project):
    """pipfile_build_requires returns [] when Pipfile has no [build-system]."""
    with patch.object(
        type(project),
        "pipfile_exists",
        new_callable=PropertyMock,
        return_value=True,
    ), patch.object(
        type(project),
        "parsed_pipfile",
        new_callable=PropertyMock,
        return_value={},
    ):
        assert project.pipfile_build_requires == []


@pytest.mark.core
def test_pipfile_build_requires_empty_when_no_pipfile(project):
    """pipfile_build_requires returns [] when there is no Pipfile at all."""
    with patch.object(
        type(project),
        "pipfile_exists",
        new_callable=PropertyMock,
        return_value=False,
    ):
        assert project.pipfile_build_requires == []


@pytest.mark.core
def test_pipfile_build_requires_reads_requires_list(project):
    """pipfile_build_requires returns the list of packages from [build-system].requires."""
    fake_pipfile = {
        "build-system": {
            "requires": ["stwrapper>=1.0", "setuptools>=40.8.0", "wheel"],
        }
    }
    with patch.object(
        type(project),
        "pipfile_exists",
        new_callable=PropertyMock,
        return_value=True,
    ), patch.object(
        type(project),
        "parsed_pipfile",
        new_callable=PropertyMock,
        return_value=fake_pipfile,
    ):
        result = project.pipfile_build_requires
        assert result == ["stwrapper>=1.0", "setuptools>=40.8.0", "wheel"]


@pytest.mark.core
def test_build_system_not_in_package_categories(project):
    """get_package_categories must never include 'build-system' (or its lockfile
    counterpart) in the returned list."""
    fake_pipfile = {
        "source": [{"url": "https://pypi.org/simple", "verify_ssl": True, "name": "pypi"}],
        "packages": {"requests": "*"},
        "dev-packages": {"pytest": "*"},
        "build-system": {"requires": ["setuptools"]},
    }
    with patch.object(
        type(project),
        "pipfile_exists",
        new_callable=PropertyMock,
        return_value=True,
    ), patch.object(
        type(project),
        "parsed_pipfile",
        new_callable=PropertyMock,
        return_value=fake_pipfile,
    ):
        categories = project.get_package_categories()
        assert "build-system" not in categories
        lockfile_categories = project.get_package_categories(for_lockfile=True)
        assert "build-system" not in lockfile_categories


@pytest.mark.core
def test_install_build_system_packages_no_op_when_empty(project):
    """install_build_system_packages does nothing when pipfile_build_requires is []."""
    from pipenv.routines.install import install_build_system_packages

    with patch.object(
        type(project),
        "pipfile_build_requires",
        new_callable=PropertyMock,
        return_value=[],
    ), patch(
        "pipenv.routines.install.pip_install_deps"
    ) as mock_pip_install:
        install_build_system_packages(project)
        mock_pip_install.assert_not_called()


@pytest.mark.core
def test_install_build_system_packages_calls_pip_install(project):
    """install_build_system_packages calls pip_install_deps with the build requires."""
    from pipenv.routines.install import install_build_system_packages

    build_requires = ["stwrapper>=1.0", "setuptools"]

    # Create a fake subprocess result that succeeds
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate.return_value = (b"", b"")

    with patch.object(
        type(project),
        "pipfile_build_requires",
        new_callable=PropertyMock,
        return_value=build_requires,
    ), patch.object(
        type(project),
        "settings",
        new_callable=PropertyMock,
        return_value={},
    ), patch(
        "pipenv.routines.install.get_source_list",
        return_value=[{"url": "https://pypi.org/simple", "verify_ssl": True, "name": "pypi"}],
    ), patch(
        "pipenv.routines.install.pip_install_deps",
        return_value=[fake_proc],
    ) as mock_pip_install:
        install_build_system_packages(project)

    mock_pip_install.assert_called_once()
    call_kwargs = mock_pip_install.call_args
    assert call_kwargs[1]["deps"] == build_requires
    assert call_kwargs[1]["ignore_hashes"] is True



# --- Tests for --extras CLI option ---


@pytest.mark.core
def test_parse_extras_single():
    """Test that extras_option parses a single extra category."""
    from pipenv.cli.options import parse_categories

    result = parse_categories("systemd")
    assert result == ["systemd"]


@pytest.mark.core
def test_parse_extras_multiple_comma():
    """Test that extras_option parses comma-separated extras."""
    from pipenv.cli.options import parse_categories

    result = parse_categories("systemd,monitoring")
    assert result == ["systemd", "monitoring"]


@pytest.mark.core
def test_parse_extras_multiple_space():
    """Test that extras_option parses space-separated extras."""
    from pipenv.cli.options import parse_categories

    result = parse_categories("systemd monitoring")
    assert result == ["systemd", "monitoring"]


@pytest.mark.core
def test_extras_option_adds_packages_category():
    """Test that --extras ensures 'packages' is in the categories list."""
    from pipenv.cli.options import InstallState

    state = InstallState()
    assert state.categories == []

    # Simulate what extras_option callback does
    extras = ["systemd"]
    if "packages" not in state.categories:
        state.categories.insert(0, "packages")
    state.categories += extras

    assert state.categories == ["packages", "systemd"]


@pytest.mark.core
def test_extras_option_does_not_duplicate_packages():
    """Test that --extras doesn't duplicate 'packages' if already present."""
    from pipenv.cli.options import InstallState

    state = InstallState()
    state.categories = ["packages"]

    # Simulate what extras_option callback does
    extras = ["systemd"]
    if "packages" not in state.categories:
        state.categories.insert(0, "packages")
    state.categories += extras

    assert state.categories == ["packages", "systemd"]


@pytest.mark.core
def test_extras_with_dev_categories():
    """Test that --extras works alongside --dev categories."""
    from pipenv.cli.options import InstallState

    state = InstallState()
    state.categories = ["dev-packages"]  # Simulates --dev being set first

    # Simulate what extras_option callback does
    extras = ["systemd"]
    if "packages" not in state.categories:
        state.categories.insert(0, "packages")
    state.categories += extras

    assert state.categories == ["packages", "dev-packages", "systemd"]


# --- Tests for shell detection (GH-5478) ---


@pytest.mark.core
def test_detect_info_prefers_shell_env_on_windows():
    """On Windows, detect_info should prefer $SHELL over shellingham to avoid
    shellingham returning 'cmd' when pyenv shims are in the process tree.

    See: https://github.com/pypa/pipenv/issues/5478
    """
    from pathlib import PurePosixPath

    from pipenv.shells import detect_info

    mock_project = MagicMock()
    mock_project.s.PIPENV_SHELL_EXPLICIT = None
    mock_project.s.PIPENV_SHELL = "/usr/bin/bash"

    # Patch both os.name and Path to avoid WindowsPath instantiation on Linux.
    with patch("pipenv.shells.os.name", "nt"), \
         patch("pipenv.shells.Path", PurePosixPath):
        name, path = detect_info(mock_project)
        assert name == "bash"
        assert path == "/usr/bin/bash"


@pytest.mark.core
def test_detect_info_explicit_takes_priority_over_shell_env():
    """PIPENV_SHELL_EXPLICIT should always win, even on Windows."""
    from pathlib import PurePosixPath

    from pipenv.shells import detect_info

    mock_project = MagicMock()
    mock_project.s.PIPENV_SHELL_EXPLICIT = "/usr/bin/cmd"
    mock_project.s.PIPENV_SHELL = "/usr/bin/bash"

    # Patch both os.name and Path to avoid WindowsPath instantiation on Linux.
    with patch("pipenv.shells.os.name", "nt"), \
         patch("pipenv.shells.Path", PurePosixPath):
        name, path = detect_info(mock_project)
        assert name == "cmd"
        assert path == "/usr/bin/cmd"


@pytest.mark.core
def test_detect_info_falls_through_to_shellingham_on_posix():
    """On POSIX, shellingham should be used even if $SHELL is set."""
    from pathlib import PurePosixPath

    from pipenv.shells import detect_info

    mock_project = MagicMock()
    mock_project.s.PIPENV_SHELL_EXPLICIT = None
    mock_project.s.PIPENV_SHELL = "/bin/bash"

    with patch("pipenv.shells.os.name", "posix"), \
         patch("pipenv.shells.Path", PurePosixPath), \
         patch("pipenv.shells.shellingham.detect_shell", return_value=("zsh", "/bin/zsh")):
        name, path = detect_info(mock_project)
        assert name == "zsh"
        assert path == "/bin/zsh"


@pytest.mark.core
def test_detect_info_falls_back_to_shell_env_when_shellingham_fails():
    """When shellingham fails, detect_info should fall back to PIPENV_SHELL."""
    from pathlib import PurePosixPath

    from pipenv.shells import detect_info

    mock_project = MagicMock()
    mock_project.s.PIPENV_SHELL_EXPLICIT = None
    mock_project.s.PIPENV_SHELL = "/bin/bash"

    with patch("pipenv.shells.os.name", "posix"), \
         patch("pipenv.shells.Path", PurePosixPath), \
         patch("pipenv.shells.shellingham.detect_shell",
               side_effect=shellingham.ShellDetectionFailure()):
        name, path = detect_info(mock_project)
        assert name == "bash"
        assert path == "/bin/bash"



# --- Regression tests for argparse migration (GH-6628, GH-6626) ---


@pytest.mark.core
def test_python_flag_before_subcommand_is_preserved():
    """Regression test for GH-6628: ``pipenv --python 3.11 sync`` must not
    lose the ``--python`` value when the subparser's default overwrites it.
    """
    from pipenv.cli.options import build_parser

    parser = build_parser()
    args, _ = parser.parse_known_args(["--python", "3.11", "sync"])

    # Fill in SUPPRESS defaults the same way cli() does.
    for attr in ("python", "pypi_mirror", "verbose", "quiet", "clear", "system"):
        if not hasattr(args, attr):
            setattr(args, attr, None)

    assert args.python == "3.11"


@pytest.mark.core
def test_python_flag_after_subcommand_is_preserved():
    """Regression test for GH-6628: ``pipenv sync --python 3.11`` must work."""
    from pipenv.cli.options import build_parser

    parser = build_parser()
    args, _ = parser.parse_known_args(["sync", "--python", "3.11"])

    for attr in ("python", "pypi_mirror", "verbose", "quiet", "clear", "system"):
        if not hasattr(args, attr):
            setattr(args, attr, None)

    assert args.python == "3.11"


@pytest.mark.core
def test_python_flag_defaults_to_none_when_absent():
    """When ``--python`` is not provided at all, state.python must be None."""
    from pipenv.cli.options import build_parser

    parser = build_parser()
    args, _ = parser.parse_known_args(["sync"])

    for attr in ("python", "pypi_mirror", "verbose", "quiet", "clear", "system"):
        if not hasattr(args, attr):
            setattr(args, attr, None)

    assert args.python is None


@pytest.mark.core
def test_run_passes_verbose_to_remaining():
    """Regression test for GH-6626: ``pipenv run ./manage.py test --verbose``
    must pass ``--verbose`` through to the user's process, not consume it as a
    pipenv flag.  As of #6641 pass-through args are captured in ``run_args``
    (argparse REMAINDER) rather than the top-level ``remaining`` list.
    """
    from pipenv.cli.options import build_parser

    parser = build_parser()
    args, remaining = parser.parse_known_args(
        ["run", "./manage.py", "test", "--verbose"]
    )
    passthrough = list(getattr(args, "run_args", []) or []) + list(remaining)
    assert "--verbose" in passthrough


@pytest.mark.core
def test_run_passes_short_v_to_remaining():
    """Regression test for GH-6626: ``-v`` after the run command must be
    passed through to the user's process.
    """
    from pipenv.cli.options import build_parser

    parser = build_parser()
    args, remaining = parser.parse_known_args(
        ["run", "./manage.py", "test", "-v"]
    )
    passthrough = list(getattr(args, "run_args", []) or []) + list(remaining)
    assert "-v" in passthrough


@pytest.mark.core
def test_run_passes_quiet_to_remaining():
    """Regression test for GH-6626: ``--quiet`` / ``-q`` must pass through."""
    from pipenv.cli.options import build_parser

    parser = build_parser()
    args, remaining = parser.parse_known_args(
        ["run", "pytest", "-q", "--tb=short"]
    )
    passthrough = list(getattr(args, "run_args", []) or []) + list(remaining)
    assert "-q" in passthrough
    assert "--tb=short" in passthrough


@pytest.mark.core
def test_run_system_flag_still_works():
    """``pipenv run --system python -c '...'`` must still recognise --system."""
    from pipenv.cli.options import build_parser

    parser = build_parser()
    args, remaining = parser.parse_known_args(
        ["run", "--system", "python", "-c", "print('hi')"]
    )

    for attr in ("python", "pypi_mirror", "verbose", "quiet", "clear", "system"):
        if not hasattr(args, attr):
            setattr(args, attr, None)

    assert args.system is True
    assert args.run_command == "python"
    passthrough = list(getattr(args, "run_args", []) or []) + list(remaining)
    assert passthrough == ["-c", "print('hi')"]


@pytest.mark.core
def test_run_passes_dash_h_through_to_command():
    """Regression test for GH-6641: ``pipenv run psql -h localhost`` must
    pass ``-h`` through to psql instead of consuming it as pipenv's help flag.
    """
    from pipenv.cli.options import build_parser

    parser = build_parser()
    args, remaining = parser.parse_known_args(
        ["run", "psql", "-h", "localhost"]
    )
    assert args.run_command == "psql"
    assert args.help is False
    passthrough = list(getattr(args, "run_args", []) or []) + list(remaining)
    assert passthrough == ["-h", "localhost"]


@pytest.mark.core
def test_run_help_before_command_still_shows_help():
    """``pipenv run --help`` and ``pipenv run -h`` with no command must still
    trigger help (not be swallowed by the REMAINDER positional)."""
    from pipenv.cli.options import build_parser

    parser = build_parser()
    for flag in ("--help", "-h"):
        args, _ = parser.parse_known_args(["run", flag])
        assert args.help is True, f"{flag} failed to set help"
        assert args.run_command is None


# --- Regression test for shell history pollution (GH-6627) ---


@pytest.mark.core
@pytest.mark.skipif(os.name == "nt", reason="PTY/pexpect not available on Windows")
def test_fork_compat_sendline_commands_have_leading_space():
    """Regression test for GH-6627: internal sendline commands in fork_compat
    must be prefixed with a space so they are not recorded in shell history
    (most shells honour HISTCONTROL=ignorespace by default).
    """
    from pipenv.shells import Shell

    shell = Shell("/bin/bash")

    mock_child = MagicMock()
    mock_child.setecho.return_value = None
    mock_child.expect.return_value = 0
    mock_child.interact.return_value = None
    mock_child.exitstatus = 0

    sent_lines = []

    def _sendline(line):
        sent_lines.append(line)

    mock_child.sendline.side_effect = _sendline

    with patch("pipenv.vendor.pexpect.spawn", return_value=mock_child), \
         patch("pipenv.shells._get_activate_script",
               return_value=" source /venv/bin/activate"), \
         patch("pipenv.shells._get_deactivate_wrapper_script",
               return_value='eval "deactivate() { builtin deactivate; }"'), \
         patch("pipenv.shells.get_terminal_size") as mock_size, \
         patch("pipenv.shells.temp_environ"), \
         patch("pipenv.shells.signal.signal"), \
         patch("sys.exit"):
        mock_size.return_value = MagicMock(lines=24, columns=80)

        shell.fork_compat("/path/to/venv", "/project", [])

    # Every internal sendline must start with a space.
    for line in sent_lines:
        assert line.startswith(" "), (
            f"sendline {line!r} must start with a space to avoid history pollution"
        )
