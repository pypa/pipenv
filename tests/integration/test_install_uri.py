import os
from pathlib import Path

import pytest

from pipenv.utils.processes import subprocess_run


@pytest.mark.vcs
@pytest.mark.install
@pytest.mark.needs_internet
def test_basic_vcs_install_with_env_var(pipenv_instance_pypi):
    with pipenv_instance_pypi(chdir=True) as p:
        # edge case where normal package starts with VCS name shouldn't be flagged as vcs
        os.environ["GIT_HOST"] = "github.com"
        c = p.pipenv("install git+https://${GIT_HOST}/benjaminp/six.git@1.11.0#egg=six gitdb2")
        assert c.returncode == 0
        assert all(package in p.pipfile["packages"] for package in ["six", "gitdb2"])
        assert "git" in p.pipfile["packages"]["six"]
        assert p.lockfile["default"]["six"] == {
            "git": "https://${GIT_HOST}/benjaminp/six.git",
            "ref": "15e31431af97e5e64b80af0a3f598d382bcdd49a",
        }
        assert "gitdb2" in p.lockfile["default"]


@pytest.mark.urls
@pytest.mark.files
@pytest.mark.needs_internet
def test_urls_work(pipenv_instance_pypi):
    with pipenv_instance_pypi(chdir=True) as p:
        # the library this installs is "django-cms"
        url = "https://github.com/lidatong/dataclasses-json/archive/refs/tags/v0.5.7.zip"
        c = p.pipenv(
            "install {0}".format(url)
        )
        assert c.returncode == 0

        dep = list(p.pipfile["packages"].values())[0]
        assert "file" in dep, p.pipfile

        # now that we handle resolution with requirementslib, this will resolve to a name
        dep = p.lockfile["default"]["dataclasses-json"]
        assert "file" in dep, p.lockfile


@pytest.mark.urls
@pytest.mark.files
def test_file_urls_work(pipenv_instance_pypi, pip_src_dir):
    with pipenv_instance_pypi(chdir=True) as p:
        whl = Path(__file__).parent.parent.joinpath(
            "pypi", "six", "six-1.11.0-py2.py3-none-any.whl"
        )
        try:
            whl = whl.resolve()
        except OSError:
            whl = whl.absolute()
        wheel_url = whl.as_uri()
        c = p.pipenv('install "{0}"'.format(wheel_url))
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert "file" in p.pipfile["packages"]["six"]


@pytest.mark.e
@pytest.mark.vcs
@pytest.mark.urls
@pytest.mark.install
@pytest.mark.needs_internet
def test_editable_vcs_install(pipenv_instance_pypi):
    with pipenv_instance_pypi(chdir=True) as p:
        c = p.pipenv(
            "install -e git+https://github.com/lidatong/dataclasses-json.git#egg=dataclasses-json"
        )
        assert c.returncode == 0
        assert "dataclasses-json" in p.pipfile["packages"]


@pytest.mark.vcs
@pytest.mark.urls
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_editable_git_tag(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi(chdir=True) as p:
        c = p.pipenv(
            "install -e git+https://github.com/benjaminp/six.git@1.11.0#egg=six"
        )
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]
        assert "git" in p.lockfile["default"]["six"]
        assert (
            p.lockfile["default"]["six"]["git"]
            == "https://github.com/benjaminp/six.git"
        )
        assert "ref" in p.lockfile["default"]["six"]


@pytest.mark.urls
@pytest.mark.index
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_named_index_alias(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
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
        assert c.returncode == 0


@pytest.mark.urls
@pytest.mark.index
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_specifying_index_url(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
six = "*"

[dev-packages]

[pipenv]
install_search_all_sources = true
            """.strip()
            f.write(contents)
        c = p.pipenv("install pipenv-test-private-package --index https://test.pypi.org/simple")
        assert c.returncode == 0
        pipfile = p.pipfile
        assert pipfile["source"][1]["url"] == "https://test.pypi.org/simple"
        assert pipfile["source"][1]["name"] == "testpypi"
        assert pipfile["packages"]["pipenv-test-private-package"]["index"] == "testpypi"


@pytest.mark.vcs
@pytest.mark.urls
@pytest.mark.install
@pytest.mark.needs_internet
def test_install_local_vcs_not_in_lockfile(pipenv_instance_pypi):
    with pipenv_instance_pypi(chdir=True) as p:
        # six_path = os.path.join(p.path, "six")
        six_path = p._pipfile.get_fixture_path("git/six/").as_posix()
        c = subprocess_run(["git", "clone", six_path, "./six"])
        assert c.returncode == 0
        c = p.pipenv("install -e ./six")
        assert c.returncode == 0
        six_key = list(p.pipfile["packages"].keys())[0]
        # we don't need the rest of the test anymore, this just works on its own
        assert six_key == "six"


@pytest.mark.vcs
@pytest.mark.urls
@pytest.mark.install
@pytest.mark.needs_internet
def test_get_vcs_refs(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi(chdir=True) as p:
        c = p.pipenv(
            "install -e git+https://github.com/benjaminp/six.git@1.9.0#egg=six"
        )
        assert c.returncode == 0
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
        assert c.returncode == 0
        assert (
            p.lockfile["default"]["six"]["ref"]
            == "15e31431af97e5e64b80af0a3f598d382bcdd49a"
        )
        assert "six" in p.pipfile["packages"]
        assert "six" in p.lockfile["default"]


@pytest.mark.vcs
@pytest.mark.urls
@pytest.mark.install
@pytest.mark.needs_internet
def test_vcs_entry_supersedes_non_vcs(pipenv_instance_pypi):
    """See issue #2181 -- non-editable VCS dep was specified, but not showing up
    in the lockfile -- due to not running pip install before locking and not locking
    the resolution graph of non-editable vcs dependencies.
    """
    with pipenv_instance_pypi(chdir=True) as p:
        jinja2_uri = p._pipfile.get_fixture_path("git/jinja2").as_uri()
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
Flask = "*"
Jinja2 = {{ref = "2.11.0", git = "{0}"}}
            """.format(jinja2_uri).strip()
            )
        c = p.pipenv("install")
        assert c.returncode == 0
        installed_packages = ["Flask", "Jinja2"]
        assert all([k in p.pipfile["packages"] for k in installed_packages])
        assert all([k.lower() in p.lockfile["default"] for k in installed_packages])
        assert all([k in p.lockfile["default"]["jinja2"] for k in ["ref", "git"]]), str(p.lockfile["default"])
        assert p.lockfile["default"]["jinja2"].get("ref") is not None
        assert (
            p.lockfile["default"]["jinja2"]["git"]
            == jinja2_uri
        )


@pytest.mark.vcs
@pytest.mark.urls
@pytest.mark.install
@pytest.mark.needs_internet
def test_vcs_can_use_markers(pipenv_instance_pypi):
    with pipenv_instance_pypi(chdir=True) as p:
        path = p._pipfile.get_fixture_path("git/six/.git")
        p._pipfile.install("six", {"git": "{0}".format(path.as_uri()), "markers": "sys_platform == 'linux'"})
        assert "six" in p.pipfile["packages"]
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "six" in p.lockfile["default"]
        assert "git" in p.lockfile["default"]["six"]
