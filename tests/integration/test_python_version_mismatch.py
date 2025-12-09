import pytest

from pipenv.utils.virtualenv import ensure_python


def test_ensure_python_non_interactive_no_yes(monkeypatch, project):
    """Test ensure_python when SESSION_IS_INTERACTIVE=False and PIPENV_YES=False."""
    # Mock the environments.SESSION_IS_INTERACTIVE to be False
    monkeypatch.setattr("pipenv.environments.SESSION_IS_INTERACTIVE", False)

    # Mock project.s.PIPENV_YES to be False
    monkeypatch.setattr(project.s, "PIPENV_YES", False)

    # Mock find_version_to_install to return a version
    class MockInstaller:
        def __init__(self, *args, **kwargs):
            self.cmd = "mock_installer"

        def find_version_to_install(self, *args, **kwargs):
            return "3.11.0"

    monkeypatch.setattr("pipenv.installers.Pyenv", MockInstaller)

    # Mock find_a_system_python to return None (Python not found)
    monkeypatch.setattr("pipenv.utils.virtualenv.find_a_system_python", lambda x: None)

    # Mock os.name to not be 'nt' to skip Windows-specific code
    monkeypatch.setattr("os.name", "posix")

    # Mock project.s.PIPENV_DONT_USE_PYENV to be False
    monkeypatch.setattr(project.s, "PIPENV_DONT_USE_PYENV", False)

    # The function should call sys.exit(1) when SESSION_IS_INTERACTIVE=False and PIPENV_YES=False
    # We'll catch this with pytest.raises
    with pytest.raises(SystemExit) as excinfo:
        ensure_python(project, python="3.11.0")

    # Verify that sys.exit was called with code 1
    assert excinfo.value.code == 1


def test_ensure_python_non_interactive_with_yes(monkeypatch, project):
    """Test ensure_python when SESSION_IS_INTERACTIVE=False but PIPENV_YES=True."""
    # Mock the environments.SESSION_IS_INTERACTIVE to be False
    monkeypatch.setattr("pipenv.environments.SESSION_IS_INTERACTIVE", False)

    # Mock project.s.PIPENV_YES to be True
    monkeypatch.setattr(project.s, "PIPENV_YES", True)

    # Mock find_version_to_install to return a version
    class MockInstaller:
        def __init__(self, *args, **kwargs):
            self.cmd = "mock_installer"

        def find_version_to_install(self, *args, **kwargs):
            return "3.11.0"

        def install(self, *args, **kwargs):
            class Result:
                stdout = "Installed successfully"
            return Result()

    monkeypatch.setattr("pipenv.installers.Pyenv", MockInstaller)

    # Mock find_a_system_python to return None initially (Python not found)
    # and then return a path after "installation"
    find_python_calls = [None]

    def mock_find_python(version):
        if len(find_python_calls) == 1:
            find_python_calls.append("/mock/path/to/python")
            return find_python_calls[-1]
        return find_python_calls[-1]

    monkeypatch.setattr("pipenv.utils.virtualenv.find_a_system_python", mock_find_python)

    # Mock python_version to return the expected version
    monkeypatch.setattr("pipenv.utils.dependencies.python_version", lambda x: "3.11.0")

    # Mock os.name to not be 'nt' to skip Windows-specific code
    monkeypatch.setattr("os.name", "posix")

    # Mock project.s.PIPENV_DONT_USE_PYENV to be False
    monkeypatch.setattr(project.s, "PIPENV_DONT_USE_PYENV", False)

    # Mock console.status to do nothing
    def mock_status(*args, **kwargs):
        class MockContextManager:
            def __enter__(self):
                return None

            def __exit__(self, *args):
                pass

        return MockContextManager()

    monkeypatch.setattr("pipenv.utils.console.status", mock_status)

    # The function should proceed with installation when PIPENV_YES=True
    result = ensure_python(project, python="3.11.0")

    # Verify that the function returned the path to Python
    assert result == "/mock/path/to/python"
