import ast
import contextlib
import errno
import functools
import hashlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import warnings
import zipfile
from pathlib import Path
from shutil import rmtree as _rmtree
from tempfile import TemporaryDirectory

import pytest
from packaging.utils import canonicalize_name

import pipenv
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
EXTRA_PYPI_VENDOR_DIR = os.path.join(TESTS_ROOT, "test_artifacts", "extra_pypi")
WE_HAVE_HG = check_for_mercurial()


def _parse_requires_python(metadata_text: str) -> str | None:
    for line in metadata_text.splitlines():
        if not line.strip():
            break  # end of the RFC822-style header block
        if line.lower().startswith("requires-python:"):
            return line.split(":", 1)[1].strip()
    return None


def _requires_python_of(pkg_file: Path) -> str | None:
    """Best-effort ``Requires-Python`` lookup for a wheel/sdist.

    pip's ``file://`` collector only picks up ``Requires-Python`` from the
    index page's ``data-requires-python`` link attribute (see
    pip._internal.models.link.Link.from_element), not by inspecting the
    package file itself - exactly what a real PyPI "simple" index page
    carries. We read it out of the file once at index-build time so our
    generated index.html can advertise it the same way.
    """
    try:
        if pkg_file.suffix == ".whl":
            with zipfile.ZipFile(pkg_file) as zf:
                for name in zf.namelist():
                    if name.endswith(".dist-info/METADATA"):
                        return _parse_requires_python(
                            zf.read(name).decode("utf-8", "replace")
                        )
        elif pkg_file.name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(pkg_file) as tf:
                for member in tf.getmembers():
                    if member.name.endswith("PKG-INFO"):
                        extracted = tf.extractfile(member)
                        if extracted is not None:
                            return _parse_requires_python(
                                extracted.read().decode("utf-8", "replace")
                            )
    except (zipfile.BadZipFile, tarfile.TarError, OSError):
        return None
    return None


def _build_local_simple_index(root: Path, source_dirs: list[Path]) -> None:
    """Populate `root` with a PEP 503 "simple" index, offline.

    Each immediate subdirectory of a `source_dirs` entry is treated as one
    project's package files (the same flat layout already used by
    tests/pypi/<project>/ for the real pypi-server fixture). For every such
    project we symlink its files into `root/<canonicalized-name>/` and write
    an `index.html` listing them with `#sha256=...` fragments, so pip's
    `file://` collector (which auto-appends `index.html` to a directory URL,
    see pip._internal.index.collector._get_index_content) can resolve and
    download them without any network access at all - not even loopback.
    """
    # Accumulate links per canonical project across ALL source_dirs before
    # writing index.html - a project present in more than one source_dir
    # (e.g. real old versions in tests/pypi + stub/extra versions in
    # extra_pypi) must get every version merged into one page, not have
    # the last source_dir visited silently clobber the earlier ones.
    links_by_project: dict[str, list[str]] = {}
    for source_dir in source_dirs:
        if not source_dir.is_dir():
            continue
        for project_dir in sorted(source_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            canonical = canonicalize_name(project_dir.name)
            target_dir = root / canonical
            target_dir.mkdir(parents=True, exist_ok=True)
            links = links_by_project.setdefault(canonical, [])
            for pkg_file in sorted(project_dir.iterdir()):
                if pkg_file.suffix == ".sha256" or pkg_file.is_dir():
                    continue
                target_file = target_dir / pkg_file.name
                if not target_file.exists():
                    target_file.symlink_to(pkg_file.resolve())
                digest = hashlib.sha256(pkg_file.read_bytes()).hexdigest()
                requires_python = _requires_python_of(pkg_file)
                requires_python_attr = (
                    f' data-requires-python="{html.escape(requires_python)}"'
                    if requires_python
                    else ""
                )
                links.append(
                    f'<a href="{pkg_file.name}#sha256={digest}"{requires_python_attr}>'
                    f"{pkg_file.name}</a><br/>"
                )

    for canonical, links in links_by_project.items():
        (root / canonical / "index.html").write_text(
            "<!DOCTYPE html><html><body>\n" + "\n".join(links) + "\n</body></html>"
        )


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
            # file:// has no TLS to verify (so there's nothing to flag
            # as untrusted) - marking it verify_ssl=False makes
            # prepare_pip_source_args() emit a nonsensical
            # "--trusted-host None", since file:// URLs have no host.
            # Mirrors the same file:// carve-out in
            # pipenv.utils.internet.create_mirror_source().
            source_table["verify_ssl"] = self.index.startswith(("https", "file://"))
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
        # Clean up the virtualenv before removing the project directory,
        # otherwise orphaned virtualenvs accumulate in WORKON_HOME.
        if self.path:
            try:
                c = self.run_command("pipenv --rm")
                if c.returncode != 0:
                    # If pipenv --rm fails, try to find and remove the venv directly
                    c = self.run_command("pipenv --venv")
                    if c.returncode == 0:
                        venv_loc = c.stdout.strip()
                        if venv_loc and os.path.isdir(venv_loc):
                            shutil.rmtree(venv_loc, ignore_errors=True)
            except Exception:
                pass  # Fixture teardown must not mask the test result.

        if self.pipfile_path:
            with contextlib.suppress(OSError):
                os.remove(self.pipfile_path)

        # Make sure we change back to the original directory before cleanup
        os.chdir(self.original_dir)

        self.path = None
        self._path = None

    def run_command(self, cmd):
        result = subprocess.run(cmd, shell=True, capture_output=True, check=False, cwd=self.path)
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

    @property
    def virtualenv_location(self):
        """Get the virtualenv location for this instance."""
        c = self.pipenv("--venv")
        if c.returncode == 0:
            return c.stdout.strip()
        return None


if os.name == "nt":
    # Windows needs special handling for read-only files (e.g., git pack files)
    # Use onexc for Python 3.12+ or onerror for older versions.
    # Extra kwargs are forwarded since tempfile passes private ones
    # (e.g. dir_fd/_onexc_kwargs as of 3.14.9).
    if sys.version_info >= (3, 12):

        def _rmtree_func(path, ignore_errors=False, onexc=None, **kwargs):
            if onexc is None:
                onexc = handle_remove_readonly
            try:
                _rmtree(path, ignore_errors=ignore_errors, onexc=onexc, **kwargs)
            except (OSError, FileNotFoundError, PermissionError) as exc:
                # Ignore removal failures where the file doesn't exist
                if exc.errno != errno.ENOENT:
                    raise

    else:

        def _rmtree_func(path, ignore_errors=False, onerror=None, **kwargs):
            if onerror is None:
                onerror = handle_remove_readonly
            try:
                _rmtree(path, ignore_errors=ignore_errors, onerror=onerror, **kwargs)
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


@pytest.fixture(scope="session", autouse=True)
def pipenv_on_path_is_checkout(tmp_path_factory):
    """Fail fast when the ``pipenv`` command isn't the code under test.

    Integration tests shell out to ``pipenv`` from ``PATH``.  If the test
    virtualenv has no pipenv of its own, that resolves to some other
    install (e.g. ``~/.local/bin/pipenv``) and tests fail in confusing ways
    against a different version.  Run the check from an empty directory,
    as the tests do, so the current directory can't mask the mismatch.
    """
    expected = Path(pipenv.__file__).resolve().parent
    c = subprocess.run(
        "pipenv --support",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path_factory.mktemp("pipenv-location-check"),
    )
    match = re.search(r"^Pipenv location: `(.+)`$", c.stdout, re.MULTILINE)
    actual = Path(ast.literal_eval(match.group(1))).resolve() if match else None
    if actual != expected:
        pytest.fail(
            f"The `pipenv` command on PATH runs {actual or 'nothing'}, not the "
            f"checkout under test ({expected}).  Install it into the test "
            'environment with: pipenv run python -m pip install -e ".[tests,dev]"',
            pytrace=False,
        )


@pytest.fixture(scope="session")
def local_pypi_index_root(tmp_path_factory):
    """Session-scoped root of an offline `file://` PEP 503 simple index.

    Built once from tests/pypi (the real-package fixture submodule) plus
    tests/test_artifacts/extra_pypi (fixture-only packages that aren't in
    the submodule). Requires no network access, not even loopback, so it
    also works under `--network=none` / `unshare --net`.
    """
    root = tmp_path_factory.mktemp("local-pypi-index")
    _build_local_simple_index(
        root, [Path(PYPI_VENDOR_DIR), Path(EXTRA_PYPI_VENDOR_DIR)]
    )
    return root


@pytest.fixture()
def pipenv_instance_file_pypi(capfdbinary, monkeypatch, local_pypi_index_root):
    """Like pipenv_instance_pypi/pipenv_instance_private_pypi, but backed by
    a local `file://` index instead of a real pypi server or pypi.org, so
    tests using it need no network access at all.

    This coexists with the subprocess/http-based fixtures above during the
    file-by-file migration; it is not a replacement for them yet.
    """
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
                _PipenvInstance,
                capfd=capfdbinary,
                index_url=local_pypi_index_root.as_uri(),
            )
        finally:
            os.umask(original_umask)


def _build_local_git_repo(dest: Path, files: dict[str, str], tag: str) -> None:
    """Build a throwaway local git repo at ``dest`` with ``files`` written
    and committed, then tagged ``tag``.

    ``git clone`` (and pip's VCS support) work fine against a plain
    ``file://`` path - no daemon, no network, not even loopback - so this
    lets editable-VCS-dependency tests avoid a real github.com clone.
    """
    env = {**os.environ, "GIT_AUTHOR_NAME": "pipenv-test", "GIT_AUTHOR_EMAIL": "test@example.com"}
    env["GIT_COMMITTER_NAME"] = env["GIT_AUTHOR_NAME"]
    env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_EMAIL"]
    # -b main: pin the initial branch name explicitly rather than relying
    # on this machine's init.defaultBranch config (tests pin `ref = "main"`).
    subprocess.run(["git", "init", "-q", "-b", "main", str(dest)], check=True, env=env)
    for relpath, content in files.items():
        path = dest / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True, env=env)
    # -c commit.gpgsign=false: this is a disposable, in-memory-only fixture
    # repo (never pushed, not real authorship history) - skip whatever the
    # ambient git config does for signing so building the fixture doesn't
    # hang/fail on a missing gpg-agent/keyserver in CI.
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "initial"],
        cwd=dest,
        check=True,
        env=env,
    )
    subprocess.run(["git", "tag", tag], cwd=dest, check=True, env=env)


@pytest.fixture(scope="session")
def local_gunicorn_git_repo(tmp_path_factory):
    """A throwaway local git repo standing in for
    https://github.com/benoitc/gunicorn, tagged 23.0.0 like the real test
    pins. Content is a minimal importable "gunicorn" package - enough for
    an editable VCS install and `import gunicorn` to work, without
    reproducing the real project's functionality.
    """
    dest = tmp_path_factory.mktemp("local-gunicorn-git-repo")
    _build_local_git_repo(
        dest,
        files={
            "setup.py": (
                "from setuptools import setup\n\n"
                "setup(name='gunicorn', version='23.0.0', packages=['gunicorn'])\n"
            ),
            "gunicorn/__init__.py": "__version__ = '23.0.0'\n",
        },
        tag="23.0.0",
    )
    return dest


@pytest.fixture(scope="session")
def local_requests_git_repo(tmp_path_factory):
    """A throwaway local git repo standing in for
    https://github.com/requests/requests, tagged "main". Named "requests"
    deliberately - this is the fixture that originally hit (and now
    exercises the fix for) VCS_SCHEMES missing "git+file": pipenv's
    Pipfile write-back used to collapse a `git+file://...#egg=requests`
    dependency down to a plain `requests = "*"` entry, because a VCS
    dependency whose package name also resolves via the regular index
    needs `determine_vcs_specifier()` to actually recognize the link as
    VCS first (pipenv/utils/constants.py's VCS_SCHEMES list was missing
    the "+file" variants that pipenv/utils/unpack.py's own copy already
    had).
    """
    dest = tmp_path_factory.mktemp("local-requests-git-repo")
    _build_local_git_repo(
        dest,
        files={
            "setup.py": (
                "from setuptools import setup\n\n"
                "setup(name='requests', version='99.0.0', packages=['requests'])\n"
            ),
            "requests/__init__.py": "__version__ = '99.0.0'\n",
        },
        tag="main",
    )
    return dest


@pytest.fixture(scope="session")
def local_adaptix_git_repo(tmp_path_factory):
    """A throwaway local git repo standing in for
    https://github.com/reagento/adaptix, tagged 2.16 like the real test
    pins. The real project's distribution name is "dataclass-factory"
    (a rename), which is the part these tests actually assert on - the
    fixture reproduces just that, not adaptix's real functionality.
    """
    dest = tmp_path_factory.mktemp("local-adaptix-git-repo")
    _build_local_git_repo(
        dest,
        files={
            "setup.py": (
                "from setuptools import setup\n\n"
                "setup(name='dataclass-factory', version='2.16', "
                "packages=['dataclass_factory'])\n"
            ),
            "dataclass_factory/__init__.py": "__version__ = '2.16'\n",
        },
        tag="2.16",
    )
    return dest


@pytest.fixture()
def testsroot():
    return TESTS_ROOT
