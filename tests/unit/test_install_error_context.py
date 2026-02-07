import queue
import pytest

def test_install_error_formats_list():
    """
    If `InstallError` receives a list/tuple of deps, it should formats it into readable
    comma-separated string instead of dumping Python repr.
    """
    from pipenv.exceptions import InstallError

    exc = InstallError(["requests==2.32.0", "flask==3.0.0"])
    text = str(exc)

    assert "requests==2.32.0" in text
    assert "flask==3.0.0" in text
    assert "Couldn't install package" in text



def test_cleanup_procs_raises_install_error_with_deps():
    """
    _cleanup_procs() should include the deps context from subprocess result
    in the raised `InstallError` message when the pip subprocess fails.
    """
    from pipenv.routines.install import _cleanup_procs
    from pipenv.exceptions import InstallError

    class _Settings:
        def is_verbose(self):
            return False

        def is_quiet(self):
            return False

    class _Project:
        s = _Settings()

    class _DummyProc:
        def __init__(self):
            self.returncode = 1
            self.stdout = "pip stdout error details"
            self.stderr = "pip stderr"
            self.deps = ["requests==0.0.0", "flask==3.0.0"]

        def communicate(self):
            return (self.stdout, self.stderr)

    procs = queue.Queue(maxsize=1)
    procs.put(_DummyProc())

    with pytest.raises(InstallError) as ctx:
        _cleanup_procs(_Project(), procs)

    text = str(ctx.value)
    assert "requests==0.0.0" in text
    assert "flask==3.0.0" in text



def test_pip_install_deps_attaches_deps_to_subprocess(monkeypatch, tmp_path):
    """
    pip_install_deps() should attach deps to the returned subproccess result.
    so error handling can display it.
    """
    from pipenv.utils import pip as pip_utils

    class _Settings:
        PIPENV_CACHE_DIR = str(tmp_path)
        PIP_EXISTS_ACTION = None

        def is_verbose(self):
            return False

    class _Project:
        s = _Settings()
        settings = {}
        virtualenv_src_location = str(tmp_path / "src")

    # Patch helpers used to build the pip command so this stays a pure unit test
    monkeypatch.setattr(pip_utils, "project_python", lambda project, system=False: "python")
    monkeypatch.setattr(pip_utils, "get_runnable_pip", lambda: "pip")
    monkeypatch.setattr(pip_utils, "get_pip_args", lambda *a, **k: [])
    monkeypatch.setattr(pip_utils, "prepare_pip_source_args", lambda sources: [])
    monkeypatch.setattr(pip_utils, "normalize_path", lambda p: p)
    # Capture subprocess_run call and return a dummy proc object
    class _DummyProc:
        def __init__(self):
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

        def communicate(self):
            return (self.stdout, self.stderr)

    def _fake_subprocess_run(*args, **kwargs):
        return _DummyProc()

    monkeypatch.setattr(pip_utils, "subprocess_run", _fake_subprocess_run)

    deps = ["requests==2.32.0"]
    cmds = pip_utils.pip_install_deps(
        project=_Project(),
        deps=deps,
        sources=[],
        allow_global=False,
        ignore_hashes=True,
        no_deps=True,
        requirements_dir=str(tmp_path),
        use_pep517=True,
        extra_pip_args=None,
    )

    assert len(cmds) >= 1
    c = cmds[0]

    assert hasattr(c, "deps")
    assert c.deps == deps

