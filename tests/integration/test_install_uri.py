# -*- coding=utf-8 -*-
import pytest

from flaky import flaky

import delegator

from pipenv._compat import Path


@pytest.mark.vcs
@pytest.mark.install
@pytest.mark.needs_internet
@flaky
def test_basic_vcs_install(PipenvInstance, pip_src_dir, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        c = p.pipenv("install git+https://github.com/benjaminp/six.git@1.11.0#egg=six")
        assert c.return_code == 0
        # edge case where normal package starts with VCS name shouldn't be flagged as vcs
        c = p.pipenv("install gitdb2")
        assert c.return_code == 0
        assert all(package in p.pipfile["packages"] for package in ["six", "gitdb2"])
        assert "git" in p.pipfile["packages"]["six"]
        assert p.lockfile["default"]["six"] == {
            "git": "https://github.com/benjaminp/six.git",
            "ref": "15e31431af97e5e64b80af0a3f598d382bcdd49a",
            "version": "==1.11.0"
        }
        assert "gitdb2" in p.lockfile["default"]


@pytest.mark.vcs
@pytest.mark.install
@pytest.mark.needs_internet
@flaky
def test_git_vcs_install(PipenvInstance, pip_src_dir, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        c = p.pipenv("install git+git://github.com/benjaminp/six.git@1.11.0#egg=six")
        assert c.return_code == 0
        assert "six" in p.pipfile["packages"]
        assert "git" in p.pipfile["packages"]["six"]
        assert p.lockfile["default"]["six"] == {
            "git": "git://github.com/benjaminp/six.git",
            "ref": "15e31431af97e5e64b80af0a3f598d382bcdd49a",
            "version": "==1.11.0"
        }


@pytest.mark.vcs
@pytest.mark.install
@pytest.mark.needs_github_ssh
@pytest.mark.needs_internet
@flaky
def test_ssh_vcs_install(PipenvInstance, pip_src_dir, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        c = p.pipenv("install git+ssh://git@github.com/benjaminp/six.git@1.11.0#egg=six")
        assert c.return_code == 0
        assert "six" in p.pipfile["packages"]
        assert "git" in p.pipfile["packages"]["six"]
        assert p.lockfile["default"]["six"] == {
            "git": "ssh://git@github.com/benjaminp/six.git",
            "ref": "15e31431af97e5e64b80af0a3f598d382bcdd49a",
            "version": "==1.11.0"
        }


@pytest.mark.files
@pytest.mark.urls
@pytest.mark.needs_internet
@flaky
def test_urls_work(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        # the library this installs is "django-cms"
        path = p._pipfile.get_url("django", "3.4.x.zip")
        c = p.pipenv(
            "install {0}".format(path)
        )
        assert c.return_code == 0

        dep = list(p.pipfile["packages"].values())[0]
        assert "file" in dep, p.pipfile

        # now that we handle resolution with requirementslib, this will resolve to a name
        dep = p.lockfile["default"]["django-cms"]
        assert "file" in dep, p.lockfile


@pytest.mark.files
@pytest.mark.urls
def test_file_urls_work(PipenvInstance, pip_src_dir):
    with PipenvInstance(chdir=True) as p:
        whl = Path(__file__).parent.parent.joinpath(
            "pypi", "six", "six-1.11.0-py2.py3-none-any.whl"
        )
        try:
            whl = whl.resolve()
        except OSError:
            whl = whl.absolute()
        wheel_url = whl.as_uri()
        c = p.pipenv('install "{0}"'.format(wheel_url))
        assert c.return_code == 0
        assert "six" in p.pipfile["packages"]
        assert "file" in p.pipfile["packages"]["six"]


@pytest.mark.files
@pytest.mark.urls
@pytest.mark.needs_internet
def test_local_vcs_urls_work(PipenvInstance, pypi, tmpdir):
    six_dir = tmpdir.join("six")
    six_path = Path(six_dir.strpath)
    with PipenvInstance(pypi=pypi, chdir=True) as p:
        c = delegator.run(
            "git clone https://github.com/benjaminp/six.git {0}".format(six_dir.strpath)
        )
        assert c.return_code == 0

        c = p.pipenv("install git+{0}#egg=six".format(six_path.as_uri()))
        assert c.return_code == 0
        assert "six" in p.pipfile["packages"]


@pytest.mark.e
@pytest.mark.vcs
@pytest.mark.install
@pytest.mark.needs_internet
@flaky
def test_editable_vcs_install(PipenvInstance, pip_src_dir, pypi):
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv(
            "install -e git+https://github.com/requests/requests.git#egg=requests"
        )
        assert c.return_code == 0
        assert "requests" in p.pipfile["packages"]
        assert "git" in p.pipfile["packages"]["requests"]
        assert "editable" in p.pipfile["packages"]["requests"]
        assert "editable" in p.lockfile["default"]["requests"]
        assert "chardet" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]


@pytest.mark.install
@pytest.mark.vcs
@pytest.mark.tablib
@pytest.mark.needs_internet
@flaky
def test_install_editable_git_tag(PipenvInstance, pip_src_dir, pypi):
    # This uses the real PyPI since we need Internet to access the Git
    # dependency anyway.
    with PipenvInstance(pypi=pypi) as p:
        c = p.pipenv(
            "install -e git+https://github.com/benjaminp/six.git@1.11.0#egg=six"
        )
        assert c.return_code == 0
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]
        assert "git" in p.lockfile["default"]["six"]
        assert (
            p.lockfile["default"]["six"]["git"]
            == "https://github.com/benjaminp/six.git"
        )
        assert "ref" in p.lockfile["default"]["six"]


@pytest.mark.install
@pytest.mark.index
@pytest.mark.needs_internet
def test_install_named_index_alias(PipenvInstance):
    with PipenvInstance() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://test.pypi.org/simple"
verify_ssl = true
name = "testpypi"

[packages]
six = "*"

[dev-packages]
            """.strip()
            f.write(contents)
        c = p.pipenv("install pipenv-test-private-package --index testpypi")
        assert c.return_code == 0


@pytest.mark.vcs
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_local_vcs_not_in_lockfile(PipenvInstance, pip_src_dir):
    with PipenvInstance(chdir=True) as p:
        # six_path = os.path.join(p.path, "six")
        six_path = p._pipfile.get_fixture_path("git/six/").as_posix()
        c = delegator.run("git clone {0} ./six".format(six_path))
        assert c.return_code == 0
        c = p.pipenv("install -e ./six".format(six_path))
        assert c.return_code == 0
        six_key = list(p.pipfile["packages"].keys())[0]
        # we don't need the rest of the test anymore, this just works on its own
        assert six_key == "six"


@pytest.mark.vcs
@pytest.mark.install
@pytest.mark.needs_internet
def test_get_vcs_refs(PipenvInstance, pip_src_dir):
    with PipenvInstance(chdir=True) as p:
        c = p.pipenv(
            "install -e git+https://github.com/benjaminp/six.git@1.9.0#egg=six"
        )
        assert c.return_code == 0
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]
        assert (
            p.lockfile["default"]["six"]["ref"]
            == "5efb522b0647f7467248273ec1b893d06b984a59"
        )
        pipfile = Path(p.pipfile_path)
        new_content = pipfile.read_text().replace(u"1.9.0", u"1.11.0")
        pipfile.write_text(new_content)
        c = p.pipenv("lock")
        assert c.return_code == 0
        assert (
            p.lockfile["default"]["six"]["ref"]
            == "15e31431af97e5e64b80af0a3f598d382bcdd49a"
        )
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]


@pytest.mark.vcs
@pytest.mark.install
@pytest.mark.needs_internet
@pytest.mark.skip_py27_win
def test_vcs_entry_supersedes_non_vcs(PipenvInstance, pip_src_dir):
    """See issue #2181 -- non-editable VCS dep was specified, but not showing up
    in the lockfile -- due to not running pip install before locking and not locking
    the resolution graph of non-editable vcs dependencies.
    """
    with PipenvInstance(chdir=True) as p:
        # pyinstaller_path = p._pipfile.get_fixture_path("git/pyinstaller")
        pyinstaller_uri = "https://github.com/pyinstaller/pyinstaller.git"
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
PyUpdater = "*"
PyInstaller = {{ref = "develop", git = "{0}"}}
            """.format(pyinstaller_uri).strip()
            )
        c = p.pipenv("install")
        assert c.return_code == 0
        installed_packages = ["PyUpdater", "PyInstaller"]
        assert all([k in p.pipfile["packages"] for k in installed_packages])
        assert all([k.lower() in p.lockfile["default"] for k in installed_packages])
        assert all([k in p.lockfile["default"]["pyinstaller"] for k in ["ref", "git"]]), str(p.lockfile["default"])
        assert p.lockfile["default"]["pyinstaller"].get("ref") is not None
        assert (
            p.lockfile["default"]["pyinstaller"]["git"]
            == pyinstaller_uri
        )


@pytest.mark.vcs
@pytest.mark.install
@pytest.mark.needs_internet
def test_vcs_can_use_markers(PipenvInstance, pip_src_dir, pypi):
    with PipenvInstance(chdir=True, pypi=pypi) as p:
        path = p._pipfile.get_fixture_path("git/six/.git")
        p._pipfile.install("six", {"git": "{0}".format(path.as_uri()), "markers": "sys_platform == 'linux'"})
        assert "six" in p.pipfile["packages"]
        c = p.pipenv("install")
        assert c.return_code == 0
        assert "six" in p.lockfile["default"]
        assert "git" in p.lockfile["default"]["six"]
