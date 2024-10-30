import contextlib
import errno
import functools
import json
import logging
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from shutil import rmtree as _rmtree
from tempfile import TemporaryDirectory

import pytest

from pipenv.patched.pip._vendor import requests
from pipenv.utils.funktools import handle_remove_readonly
from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import temp_environ
from pipenv.vendor import tomlkit

log = logging.getLogger(__name__)
warnings.simplefilter("default", category=ResourceWarning)


DEFAULT_PRIVATE_PYPI_SERVER = os.environ.get(
    "PIPENV_PYPI_SERVER", "http://localhost:8080/simple"
)


def try_internet(url="http://httpbin.org/ip", timeout=1.5):
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()


def check_internet():
    has_internet = False
    for url in ("http://httpbin.org/ip", "http://clients3.google.com/generate_204"):
        try:
            try_internet(url)
        except KeyboardInterrupt:  # noqa: PERF203
            warnings.warn(
                f"Skipped connecting to internet: {url}", RuntimeWarning, stacklevel=1
            )
        except Exception:
            warnings.warn(
                f"Failed connecting to internet: {url}", RuntimeWarning, stacklevel=1
            )
        else:
            has_internet = True
            break
    return has_internet


def check_github_ssh():
    res = False
    try:
        # `ssh -T git@github.com` will return successfully with return_code==1
        # and message 'Hi <username>! You've successfully authenticated, but
        # GitHub does not provide shell access.' if ssh keys are available and
        # registered with GitHub. Otherwise, the command will fail with
        # return_code=255 and say 'Permission denied (publickey).'
        c = subprocess_run(
            "ssh -o StrictHostKeyChecking=no -o CheckHostIP=no -T git@github.com",
            timeout=30,
            shell=True,
        )
        res = c.returncode == 1
    except KeyboardInterrupt:
        warnings.warn(
            "KeyboardInterrupt while checking GitHub ssh access",
            RuntimeWarning,
            stacklevel=1,
        )
    return res


def check_for_mercurial():
    c = subprocess_run("hg --help", shell=True)
    return c.returncode == 0


TESTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPI_VENDOR_DIR = os.path.join(TESTS_ROOT, "pypi")
WE_HAVE_HG = check_for_mercurial()


def pytest_runtest_setup(item):
    if item.get_closest_marker("needs_internet") is not None and not WE_HAVE_INTERNET:
        pytest.skip("requires internet")
    if (
        item.get_closest_marker("needs_github_ssh") is not None
        and not WE_HAVE_GITHUB_SSH_KEYS
    ):
        pytest.skip("requires github ssh")
    if item.get_closest_marker("needs_hg") is not None and not WE_HAVE_HG:
        pytest.skip("requires mercurial")
    if item.get_closest_marker("skip_py38") is not None and (
        sys.version_info[:2] == (3, 8)
    ):
        pytest.skip("test not applicable on python 3.8")
    if item.get_closest_marker("skip_osx") is not None and sys.platform == "darwin":
        pytest.skip("test does not apply on OSX")
    if item.get_closest_marker("skip_windows") is not None and (os.name == "nt"):
        pytest.skip("test does not run on windows")


WE_HAVE_INTERNET = check_internet()
WE_HAVE_GITHUB_SSH_KEYS = False


class _Pipfile:
    def __init__(self, path, index):
        self.path = path
        self.index = index
        if self.path.exists():
            self.loads()
        else:
            self.document = tomlkit.document()
        self.document["source"] = self.document.get("source", tomlkit.aot())
        self.document["requires"] = self.document.get("requires", tomlkit.table())
        self.document["packages"] = self.document.get("packages", tomlkit.table())
        self.document["dev-packages"] = self.document.get("dev-packages", tomlkit.table())
        self.write()

    def install(self, package, value, dev=False):
        section = "packages" if not dev else "dev-packages"
        if isinstance(value, dict):
            table = tomlkit.inline_table()
            table.update(value)
            self.document[section][package] = table
        else:
            self.document[section][package] = value
        self.write()

    def remove(self, package, dev=False):
        section = "packages" if not dev else "dev-packages"
        if (
            not dev
            and package not in self.document[section]
            and package in self.document["dev-packages"]
        ):
            section = "dev-packages"
        del self.document[section][package]
        self.write()

    def add(self, package, value, dev=False):
        self.install(package, value, dev=dev)

    def update(self, package, value, dev=False):
        self.install(package, value, dev=dev)

    def loads(self):
        self.document = tomlkit.loads(self.path.read_text())

    def dumps(self):
        if not self.document.get("source"):
            source_table = tomlkit.table()
            source_table["url"] = self.index
            source_table["verify_ssl"] = bool(self.index.startswith("https"))
            source_table["name"] = "pipenv_test_index"
            self.document["source"].append(source_table)
        return tomlkit.dumps(self.document)

    def write(self):
        self.path.write_text(self.dumps())

    @classmethod
    def get_fixture_path(cls, path, fixtures="test_artifacts"):
        return Path(Path(__file__).resolve().parent.parent / fixtures / path)


class _PipenvInstance:
    """An instance of a Pipenv Project..."""

    def __init__(self, pipfile=True, capfd=None, index_url=None):
        self.index_url = index_url
        self.pypi = None
        self.env = {}
        self.capfd = capfd
        if self.index_url is not None:
            self.pypi, _, _ = self.index_url.rpartition("/") if self.index_url else ""
        self.env["PYTHONWARNINGS"] = "ignore:DEPRECATION"
        os.environ.pop("PIPENV_CUSTOM_VENV_NAME", None)

        self.original_dir = Path(__file__).parent.parent.parent
        self._path = TemporaryDirectory(prefix="pipenv-", suffix="-tests")
        path = Path(self._path.name)
        try:
            self.path = str(path.resolve())
        except OSError:
            self.path = str(path.absolute())
        os.chdir(self.path)

        # set file creation perms
        self.pipfile_path = None
        p_path = os.sep.join([self.path, "Pipfile"])
        self.pipfile_path = Path(p_path)

        if pipfile:
            with contextlib.suppress(FileNotFoundError):
                os.remove(p_path)

            with open(p_path, "a"):
                os.utime(p_path, None)

            self._pipfile = _Pipfile(Path(p_path), index=self.index_url)
        else:
            self._pipfile = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        warn_msg = "Failed to remove resource: {!r}"
        if self.pipfile_path:
            with contextlib.suppress(OSError):
                os.remove(self.pipfile_path)

        os.chdir(self.original_dir)
        if self._path:
            try:
                self._path.cleanup()
            except OSError as e:
                _warn_msg = warn_msg.format(e)
                warnings.warn(_warn_msg, ResourceWarning, stacklevel=1)
        self.path = None
        self._path = None

    def run_command(self, cmd):
        result = subprocess.run(cmd, shell=True, capture_output=True, check=False)
        try:
            std_out_decoded = result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            std_out_decoded = result.stdout
        result.stdout = std_out_decoded
        try:
            std_err_decoded = result.stderr.decode("utf-8")
        except UnicodeDecodeError:
            std_err_decoded = result.stderr
        result.stderr = std_err_decoded
        return result

    def pipenv(self, cmd, block=True):
        self.capfd.readouterr()
        r = self.run_command(f"pipenv {cmd}")
        # Pretty output for failing tests.
        out, err = self.capfd.readouterr()
        if out:
            r.stdout_bytes = r.stdout_bytes + out
        if err:
            r.stderr_bytes = r.stderr_bytes + err
        if block:
            print(f"$ pipenv {cmd}")
            print(r.stdout)
            print(r.stderr, file=sys.stderr)
            if r.returncode != 0:
                print("Command failed...")

        # Where the action happens.
        return r

    @property
    def pipfile(self):
        p_path = os.sep.join([self.path, "Pipfile"])
        with open(p_path) as f:
            return tomlkit.loads(f.read())

    @property
    def lockfile(self):
        p_path = self.lockfile_path
        with open(p_path) as f:
            return json.loads(f.read())

    @property
    def lockfile_path(self):
        return Path(os.sep.join([self.path, "Pipfile.lock"]))


if sys.version_info[:2] <= (3, 8):
    # Windows python3.8 fails without this patch.  Additional details: https://bugs.python.org/issue42796
    def _rmtree_func(path, ignore_errors=True, onerror=None):
        shutil_rmtree = _rmtree
        if onerror is None:
            onerror = handle_remove_readonly
        try:
            shutil_rmtree(path, ignore_errors=ignore_errors, onerror=onerror)
        except (OSError, FileNotFoundError, PermissionError) as exc:
            # Ignore removal failures where the file doesn't exist
            if exc.errno != errno.ENOENT:
                raise

else:
    _rmtree_func = _rmtree


@pytest.fixture()
def pipenv_instance_pypi(capfdbinary, monkeypatch):
    with temp_environ(), monkeypatch.context() as m:
        m.setattr(shutil, "rmtree", _rmtree_func)
        original_umask = os.umask(0o007)
        os.environ["PIPENV_NOSPIN"] = "1"
        os.environ["CI"] = "1"
        os.environ["PIPENV_DONT_USE_PYENV"] = "1"
        warnings.simplefilter("ignore", category=ResourceWarning)
        warnings.filterwarnings(
            "ignore", category=ResourceWarning, message="unclosed.*<ssl.SSLSocket.*>"
        )
        try:
            yield functools.partial(
                _PipenvInstance, capfd=capfdbinary, index_url="https://pypi.org/simple"
            )
        finally:
            os.umask(original_umask)


@pytest.fixture()
def pipenv_instance_private_pypi(capfdbinary, monkeypatch):
    with temp_environ(), monkeypatch.context() as m:
        m.setattr(shutil, "rmtree", _rmtree_func)
        original_umask = os.umask(0o007)
        os.environ["PIPENV_NOSPIN"] = "1"
        os.environ["CI"] = "1"
        os.environ["PIPENV_DONT_USE_PYENV"] = "1"
        warnings.simplefilter("ignore", category=ResourceWarning)
        warnings.filterwarnings(
            "ignore", category=ResourceWarning, message="unclosed.*<ssl.SSLSocket.*>"
        )
        try:
            yield functools.partial(
                _PipenvInstance, capfd=capfdbinary, index_url=DEFAULT_PRIVATE_PYPI_SERVER
            )
        finally:
            os.umask(original_umask)


@pytest.fixture()
def testsroot():
    return TESTS_ROOT
