import os
from pathlib import Path

import pytest
from flaky import flaky

from pipenv.utils.shell import temp_environ


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_handle_eggs(pipenv_instance_private_pypi):
    """Ensure locking works with packages providing egg formats."""
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            f.write(
                f"""
[[source]]
url = "{p.index_url}"
verify_ssl = false
name = "testindex"

[packages]
RandomWords = "*"
            """
            )
        c = p.pipenv("lock --verbose")
        assert c.returncode == 0
        assert "randomwords" in p.lockfile["default"]
        assert p.lockfile["default"]["randomwords"]["version"] == "==0.2.1"


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_gathers_pyproject_dependencies(pipenv_instance_pypi):
    """Ensure that running `pipenv install` doesn't install dev packages"""
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
pipenvtest = { editable = true, path = "." }
            """.strip()
            f.write(contents)

        # Write the pyproject.toml
        pyproject_toml_path = os.path.join(
            os.path.dirname(p.pipfile_path), "pyproject.toml"
        )
        with open(pyproject_toml_path, "w") as f:
            contents = """
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "pipenvtest"
version = "0.0.1"
requires-python = ">=3.8"
dependencies = [
    "six"
]
            """.strip()
            f.write(contents)
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "six" in p.lockfile["default"]


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_requirements_file(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
urllib3 = "==1.23"
[dev-packages]
colorama = "==0.3.9"
            """.strip()
            f.write(contents)

        req_list = ("urllib3==1.23",)

        dev_req_list = ("colorama==0.3.9",)

        c = p.pipenv("lock")
        assert c.returncode == 0

        default = p.pipenv("requirements")
        assert default.returncode == 0
        dev = p.pipenv("requirements --dev-only")

        for req in req_list:
            assert req in default.stdout

        for req in dev_req_list:
            assert req in dev.stdout


@pytest.mark.lock
def test_lock_includes_hashes_for_all_platforms(pipenv_instance_private_pypi):
    """Locking should include hashes for *all* platforms, not just the
    platform we're running lock on."""

    # releases = pytest_pypi.app.packages['yarl'].releases

    releases = {
        "yarl-1.3.0-cp35-cp35m-manylinux1_x86_64.whl": "3890ab952d508523ef4881457c4099056546593fa05e93da84c7250516e632eb",
        "yarl-1.3.0-cp35-cp35m-win_amd64.whl": "b25de84a8c20540531526dfbb0e2d2b648c13fd5dd126728c496d7c3fea33310",
        "yarl-1.3.0-cp36-cp36m-manylinux1_x86_64.whl": "5badb97dd0abf26623a9982cd448ff12cb39b8e4c94032ccdedf22ce01a64842",
        "yarl-1.3.0-cp36-cp36m-win_amd64.whl": "c6e341f5a6562af74ba55205dbd56d248daf1b5748ec48a0200ba227bb9e33f4",
        "yarl-1.3.0-cp37-cp37m-win_amd64.whl": "73f447d11b530d860ca1e6b582f947688286ad16ca42256413083d13f260b7a0",
        "yarl-1.3.0.tar.gz": "024ecdc12bc02b321bc66b41327f930d1c2c543fa9a561b39861da9388ba7aa9",
    }

    def get_hash(release_name):
        # Convert a specific filename to a hash like what would show up in a Pipfile.lock.
        # For example:
        # 'yarl-1.3.0-cp35-cp35m-manylinux1_x86_64.whl' -> 'sha256:3890ab952d508523ef4881457c4099056546593fa05e93da84c7250516e632eb'
        return f"sha256:{releases[release_name]}"

    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = false
name = "testindex"

[packages]
yarl = "==1.3.0"
            """.strip()
            f.write(contents)

        c = p.pipenv("lock")
        assert c.returncode == 0

        lock = p.lockfile
        assert "yarl" in lock["default"]
        assert set(lock["default"]["yarl"]["hashes"]) == {
            get_hash("yarl-1.3.0-cp35-cp35m-manylinux1_x86_64.whl"),
            get_hash("yarl-1.3.0-cp35-cp35m-win_amd64.whl"),
            get_hash("yarl-1.3.0-cp36-cp36m-manylinux1_x86_64.whl"),
            get_hash("yarl-1.3.0-cp36-cp36m-win_amd64.whl"),
            get_hash("yarl-1.3.0-cp37-cp37m-win_amd64.whl"),
            get_hash("yarl-1.3.0.tar.gz"),
        }


@pytest.mark.lock
def test_resolve_skip_unmatched_requirements(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        p._pipfile.add("missing-package", {"markers": "os_name=='FakeOS'"})
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert (
            'Could not find a matching version of missing-package; os_name == "FakeOS"'
            in c.stderr
        )


@pytest.mark.lock
@pytest.mark.complex
@pytest.mark.needs_internet
def test_complex_lock_with_vcs_deps(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        dateutil_uri = p._pipfile.get_fixture_path("git/dateutil").as_uri()
        with open(p.pipfile_path, "w") as f:
            contents = (
                """
[packages]
click = "==6.7"

[dev-packages]
requests = {git = "%s"}
            """.strip()
                % requests_uri
            )
            f.write(contents)

        c = p.pipenv("install")
        assert c.returncode == 0
        lock = p.lockfile
        assert "requests" in lock["develop"]
        assert "click" in lock["default"]

        c = p.pipenv(f"run pip install -e git+{dateutil_uri}#egg=python_dateutil")
        assert c.returncode == 0

        lock = p.lockfile
        assert "requests" in lock["develop"]
        assert "click" in lock["default"]
        assert "python_dateutil" not in lock["default"]
        assert "python_dateutil" not in lock["develop"]


@pytest.mark.lock
@pytest.mark.requirements
def test_lock_with_prereleases(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
sqlalchemy = "==1.2.0b3"

[pipenv]
allow_prereleases = true
            """.strip()
            f.write(contents)

        c = p.pipenv("lock")
        assert c.returncode == 0
        assert p.lockfile["default"]["sqlalchemy"]["version"] == "==1.2.0b3"


@pytest.mark.lock
@pytest.mark.maya
@pytest.mark.complex
@pytest.mark.needs_internet
@flaky
def test_complex_deps_lock_and_install_properly(pipenv_instance_pypi):
    # This uses the real PyPI because Maya has too many dependencies...
    with pipenv_instance_pypi() as p, open(p.pipfile_path, "w") as f:
        contents = """
[packages]
maya = "*"
            """.strip()
        f.write(contents)

        c = p.pipenv("lock --verbose")
        assert c.returncode == 0

        c = p.pipenv("install")
        assert c.returncode == 0


@pytest.mark.lock
@pytest.mark.extras
def test_lock_extras_without_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
requests = {version = "*", extras = ["socks"]}
            """.strip()
            f.write(contents)

        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert "pysocks" in p.lockfile["default"]
        assert "markers" in p.lockfile["default"]["pysocks"]

        c = p.pipenv("lock")
        assert c.returncode == 0
        c = p.pipenv("requirements")
        assert c.returncode == 0
        assert "extra == 'socks'" not in c.stdout.strip()


@pytest.mark.lock
@pytest.mark.index
@pytest.mark.install  # private indexes need to be uncached for resolution
@pytest.mark.requirements
@pytest.mark.needs_internet
def test_private_index_lock_requirements(pipenv_instance_private_pypi):
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
pipenv-test-private-package = {version = "*", index = "testpypi"}
            """.strip()
            f.write(contents)
        c = p.pipenv("lock")
        assert c.returncode == 0


@pytest.mark.lock
@pytest.mark.index
@pytest.mark.install  # private indexes need to be uncached for resolution
@pytest.mark.requirements
@pytest.mark.needs_internet
def test_private_index_lock_requirements_for_not_canonical_package(
    pipenv_instance_private_pypi,
):
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
pipenv_test_private_package = {version = "*", index = "testpypi"}
            """.strip()
            f.write(contents)
        c = p.pipenv("lock")
        assert c.returncode == 0


@pytest.mark.index
@pytest.mark.install
def test_lock_updated_source(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "{url}/${{MY_ENV_VAR}}"
name = "localpypi"
verify_ssl = false

[packages]
requests = "==2.14.0"
            """.strip().format(
                url=p.pypi
            )
            f.write(contents)

        with temp_environ():
            os.environ["MY_ENV_VAR"] = "simple"
            c = p.pipenv("lock")
            assert c.returncode == 0
            assert "requests" in p.lockfile["default"]

        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "{url}/simple"
name = "localpypi"
verify_ssl = false

[packages]
requests = "==2.14.0"
            """.strip().format(
                url=p.pypi
            )
            f.write(contents)

        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_without_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        requests_uri = p._pipfile.get_fixture_path("git/six").as_uri()
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[packages]
six = {git = "%s", editable = true}
            """.strip()
                % requests_uri
            )
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "six" in p.lockfile["default"]


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_ref_in_git(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[packages]
requests = {git = "%s@883caaf", editable = true}
            """.strip()
                % requests_uri
            )
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert requests_uri in p.lockfile["default"]["requests"]["git"]
        assert (
            p.lockfile["default"]["requests"]["ref"]
            == "883caaf145fbe93bd0d208a6b864de9146087312"
        )


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.extras
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_extras_without_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[packages]
requests = {git = "%s", editable = true, extras = ["socks"]}
            """.strip()
                % requests_uri
            )
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]
        assert "socks" in p.lockfile["default"]["requests"]["extras"]
        assert "version" not in p.lockfile["default"]["requests"]


@pytest.mark.vcs
@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_editable_vcs_with_markers_without_install(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[packages]
requests = {git = "%s", editable = true, markers = "python_version >= '2.6'"}
            """.strip()
                % requests_uri
            )
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]
        assert c.returncode == 0


@pytest.mark.lock
@pytest.mark.install
def test_lockfile_corrupted(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.lockfile_path, "w") as f:
            f.write("{corrupted}")
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "Pipfile.lock is corrupted" in c.stderr
        assert p.lockfile["_meta"]


@pytest.mark.lock
def test_lockfile_with_empty_dict(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.lockfile_path, "w") as f:
            f.write("{}")
        c = p.pipenv("install")
        assert c.returncode == 0
        assert p.lockfile["_meta"]


@pytest.mark.vcs
@pytest.mark.lock
def test_vcs_lock_respects_top_level_pins(pipenv_instance_private_pypi):
    """Test that locking VCS dependencies respects top level packages pinned in Pipfiles"""

    with pipenv_instance_private_pypi() as p:
        requests_uri = p._pipfile.get_fixture_path("git/requests").as_uri()
        p._pipfile.add(
            "requests", {"editable": True, "git": f"{requests_uri}", "ref": "v2.18.4"}
        )
        p._pipfile.add("urllib3", "==1.21.1")
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert "git" in p.lockfile["default"]["requests"]
        assert "urllib3" in p.lockfile["default"]
        assert p.lockfile["default"]["urllib3"]["version"] == "==1.21.1"


@pytest.mark.lock
def test_lock_after_update_source_name(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "test"

[packages]
six = "*"
        """.strip()
        with open(p.pipfile_path, "w") as f:
            f.write(contents)
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert p.lockfile["default"]["six"]["index"] == "test"
        with open(p.pipfile_path, "w") as f:
            f.write(contents.replace('name = "test"', 'name = "custom"'))
        c = p.pipenv("lock --clear")
        assert c.returncode == 0
        assert "index" in p.lockfile["default"]["six"]
        assert p.lockfile["default"]["six"]["index"] == "custom", Path(
            p.lockfile_path
        ).read_text()


@pytest.mark.lock
def test_lock_nested_direct_url(pipenv_instance_private_pypi):
    """
    The dependency 'test_package' has a declared dependency on
    a PEP508 style VCS URL. This ensures that we capture the dependency
    here along with its own dependencies.
    """
    with pipenv_instance_private_pypi(pipfile=False) as p:
        contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "local"

[packages]
test_package = "*"
                """.strip()
        with open(p.pipfile_path, "w") as f:
            f.write(contents)
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "vistir" in p.lockfile["default"]
        assert "colorama" in p.lockfile["default"]
        assert "six" in p.lockfile["default"]


@pytest.mark.lock
@pytest.mark.needs_internet
def test_lock_nested_vcs_direct_url(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        p._pipfile.add(
            "pep508_package",
            {
                "git": "https://github.com/techalchemy/test-project.git",
                "editable": True,
                "ref": "master",
                "subdirectory": "parent_folder/pep508-package",
            },
        )
        c = p.pipenv("lock -v")
        assert c.returncode == 0
        assert "git" in p.lockfile["default"]["pep508-package"]
        assert "sibling-package" in p.lockfile["default"]
        assert "git" in p.lockfile["default"]["sibling-package"]
        assert "subdirectory" in p.lockfile["default"]["sibling-package"]
        assert (
            p.lockfile["default"]["sibling-package"]["subdirectory"]
            == "parent_folder/sibling_package"
        )
        assert "version" not in p.lockfile["default"]["sibling-package"]


@pytest.mark.lock
@pytest.mark.install
def test_lock_package_with_compatible_release_specifier(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install six~=1.11")
        assert c.returncode == 0
        assert "six" in p.pipfile["packages"]
        assert p.pipfile["packages"]["six"] == "~=1.11"
        assert "six" in p.lockfile["default"]
        assert "version" in p.lockfile["default"]["six"]
        assert p.lockfile["default"]["six"]["version"] == "==1.12.0"


@pytest.mark.lock
@pytest.mark.install
def test_default_lock_overwrite_dev_lock(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install click==6.7")
        assert c.returncode == 0
        c = p.pipenv("install -d flask")
        assert c.returncode == 0
        assert p.lockfile["default"]["click"]["version"] == "==6.7"
        assert p.lockfile["develop"]["click"]["version"] == "==6.7"


@flaky
@pytest.mark.lock
@pytest.mark.install
@pytest.mark.needs_internet
def test_pipenv_respects_package_index_restrictions(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "{url}"
verify_ssl = true
name = "local"

[packages]
requests = {requirement}
                """.strip().format(
                url=p.index_url, requirement='{version="*", index="local"}'
            )
            f.write(contents)

        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert "idna" in p.lockfile["default"]
        assert "certifi" in p.lockfile["default"]
        assert "urllib3" in p.lockfile["default"]
        assert "chardet" in p.lockfile["default"]
        # this is the newest version we have in our private pypi (but pypi.org has 2.27.1 at present)
        expected_result = {
            "hashes": [
                "sha256:63b52e3c866428a224f97cab011de738c36aec0185aa91cfacd418b5d58911d1",
                "sha256:ec22d826a36ed72a7358ff3fe56cbd4ba69dd7a6718ffd450ff0e9df7a47ce6a",
            ],
            "index": "local",
            "version": "==2.19.1",
        }
        assert p.lockfile["default"]["requests"] == expected_result


@pytest.mark.dev
@pytest.mark.lock
@pytest.mark.install
def test_dev_lock_use_default_packages_as_constraint(pipenv_instance_private_pypi):
    # See https://github.com/pypa/pipenv/issues/4371
    # See https://github.com/pypa/pipenv/issues/2987
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = false
name = "testindex"

[packages]
requests = "<=2.14.0"

[dev-packages]
requests = "*"
                """.strip()
            f.write(contents)

        c = p.pipenv("lock --dev")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert p.lockfile["default"]["requests"]["version"] == "==2.14.0"
        assert "requests" in p.lockfile["develop"]
        assert p.lockfile["develop"]["requests"]["version"] == "==2.14.0"

        # requests 2.14.0 doesn't require these packages
        assert "idna" not in p.lockfile["develop"]
        assert "certifi" not in p.lockfile["develop"]
        assert "urllib3" not in p.lockfile["develop"]
        assert "chardet" not in p.lockfile["develop"]


@pytest.mark.lock
def test_lock_specific_named_category(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi(pipfile=False) as p:
        contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "test"

[packages]
requests = "*"

[prereq]
six = "*"
        """.strip()
        with open(p.pipfile_path, "w") as f:
            f.write(contents)
        c = p.pipenv("lock --categories prereq")
        assert c.returncode == 0
        assert p.lockfile["prereq"]["six"]["index"] == "test"
        assert p.lockfile["default"] == {}
        c = p.pipenv("lock --categories packages")
        assert c.returncode == 0
        assert p.lockfile["prereq"]["six"]["index"] == "test"
        assert p.lockfile["default"]["requests"]["index"] == "test"


def test_pinned_pipfile_no_null_markers_when_extras(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
dataclasses-json = {extras = ["dev"], version = "==0.5.7"}
            """.strip()
            f.write(contents)
        c = p.pipenv("lock")
        assert c.returncode == 0
        assert "dataclasses-json" in p.pipfile["packages"]
        assert "dataclasses-json" in p.lockfile["default"]
        assert p.lockfile["default"]["dataclasses-json"].get("markers", "") is not None


@pytest.mark.index
@pytest.mark.install  # private indexes need to be uncached for resolution
@pytest.mark.skip_lock
@pytest.mark.needs_internet
def test_private_index_skip_lock(pipenv_instance_private_pypi):
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
pipenv-test-private-package = {version = "*", index = "testpypi"}

[pipenv]
install_search_all_sources = true
            """.strip()
            f.write(contents)
        c = p.pipenv("install --skip-lock")
        assert c.returncode == 0
