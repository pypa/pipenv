import json
import os

import pytest

from pipenv.utils.requirements import requirements_from_lockfile
from pipenv.utils.shell import temp_environ


@pytest.mark.requirements
def test_requirements_generates_requirements_from_lockfile(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        packages = ("requests", "2.14.0")
        dev_packages = ("flask", "0.12.2")
        with open(p.pipfile_path, "w") as f:
            contents = f"""
            [packages]
            {packages[0]}= "=={packages[1]}"
            [dev-packages]
            {dev_packages[0]}= "=={dev_packages[1]}"
            """.strip()
            f.write(contents)
        p.pipenv("lock")
        c = p.pipenv("requirements")
        assert c.returncode == 0
        assert f"{packages[0]}=={packages[1]}" in c.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" not in c.stdout

        d = p.pipenv("requirements --dev")
        assert d.returncode == 0
        assert f"{packages[0]}=={packages[1]}" in d.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" in d.stdout

        e = p.pipenv("requirements --dev-only")
        assert e.returncode == 0
        assert f"{packages[0]}=={packages[1]}" not in e.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" in e.stdout

        e = p.pipenv("requirements --hash")
        assert e.returncode == 0
        assert f"{packages[0]}=={packages[1]}" in e.stdout
        for value in p.lockfile["default"].values():
            for hash in value["hashes"]:
                assert f" --hash={hash}" in e.stdout


@pytest.mark.requirements
def test_requirements_generates_requirements_from_lockfile_multiple_sources(
    pipenv_instance_private_pypi,
):
    with pipenv_instance_private_pypi() as p:
        packages = ("six", "1.12.0")
        dev_packages = ("itsdangerous", "1.1.0")
        with open(p.pipfile_path, "w") as f:
            contents = f"""
            [[source]]
            name = "pypi"
            url = "https://pypi.org/simple"
            verify_ssl = true
            [[source]]
            name = "other_source"
            url = "https://some_other_source.org"
            verify_ssl = true
            [packages]
            {packages[0]}= "=={packages[1]}"
            [dev-packages]
            {dev_packages[0]}= "=={dev_packages[1]}"
            """.strip()
            f.write(contents)
        result = p.pipenv("lock")
        assert result.returncode == 0
        c = p.pipenv("requirements")
        assert c.returncode == 0

        assert "-i https://pypi.org/simple" in c.stdout
        assert "--extra-index-url https://some_other_source.org" in c.stdout


@pytest.mark.requirements
def test_requirements_generates_requirements_from_lockfile_from_categories(
    pipenv_instance_private_pypi,
):
    with pipenv_instance_private_pypi() as p:
        packages = ("six", "1.12.0")
        dev_packages = ("itsdangerous", "1.1.0")
        test_packages = ("pytest", "7.1.3")
        doc_packages = ("docutils", "0.19")

        with open(p.pipfile_path, "w") as f:
            contents = f"""
            [[source]]
            name = "pypi"
            url = "https://pypi.org/simple"
            verify_ssl = true
            [packages]
            {packages[0]}= "=={packages[1]}"
            [dev-packages]
            {dev_packages[0]}= "=={dev_packages[1]}"
            [test]
            {test_packages[0]}= "=={test_packages[1]}"
            [doc]
            {doc_packages[0]}= "=={doc_packages[1]}"
            """.strip()
            f.write(contents)
        result = p.pipenv("lock")
        assert result.returncode == 0

        c = p.pipenv("requirements --dev-only")
        assert c.returncode == 0
        assert f"{packages[0]}=={packages[1]}" not in c.stdout
        assert f"{test_packages[0]}=={test_packages[1]}" not in c.stdout
        assert f"{doc_packages[0]}=={doc_packages[1]}" not in c.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" in c.stdout

        d = p.pipenv('requirements --categories="test, doc"')
        assert d.returncode == 0
        assert f"{packages[0]}=={packages[1]}" not in d.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" not in d.stdout
        assert f"{test_packages[0]}=={test_packages[1]}" in d.stdout
        assert f"{doc_packages[0]}=={doc_packages[1]}" in d.stdout


@pytest.mark.requirements
def test_requirements_generates_requirements_with_from_pipfile(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        packages = ("requests", "2.31.0")
        sub_packages = (
            "urllib3",
            "2.2.1",
        )  # subpackages not explicitly written in Pipfile.
        dev_packages = ("flask", "0.12.2")

        with open(p.pipfile_path, "w") as f:
            contents = f"""
            [packages]
            {packages[0]} = "=={packages[1]}"
            [dev-packages]
            {dev_packages[0]} = "=={dev_packages[1]}"
            """.strip()
            f.write(contents)
        p.pipenv("lock")

        c = p.pipenv("requirements --from-pipfile")
        assert c.returncode == 0
        assert f"{packages[0]}=={packages[1]}" in c.stdout
        assert f"{sub_packages[0]}=={sub_packages[1]}" not in c.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" not in c.stdout

        d = p.pipenv("requirements --dev --from-pipfile")
        assert d.returncode == 0
        assert f"{packages[0]}=={packages[1]}" in d.stdout
        assert f"{sub_packages[0]}=={sub_packages[1]}" not in d.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" in d.stdout

        e = p.pipenv("requirements --dev-only --from-pipfile")
        assert e.returncode == 0
        assert f"{packages[0]}=={packages[1]}" not in e.stdout
        assert f"{sub_packages[0]}=={sub_packages[1]}" not in e.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" in e.stdout

        f = p.pipenv("requirements --categories=dev-packages --from-pipfile")
        assert f.returncode == 0
        assert f"{packages[0]}=={packages[1]}" not in f.stdout
        assert f"{sub_packages[0]}=={sub_packages[1]}" not in f.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" in f.stdout

        g = p.pipenv("requirements --categories=packages,dev-packages --from-pipfile")
        assert g.returncode == 0
        assert f"{packages[0]}=={packages[1]}" in g.stdout
        assert f"{sub_packages[0]}=={sub_packages[1]}" not in g.stdout
        assert f"{dev_packages[0]}=={dev_packages[1]}" in g.stdout


@pytest.mark.requirements
def test_requirements_with_git_requirements(pipenv_instance_pypi):
    req_hash = "3264a0046e1aa3c0a813335286ebdbc651f58b13"
    lockfile = {
        "_meta": {"sources": []},
        "default": {
            "dataclasses-json": {
                "editable": True,
                "git": "https://github.com/lidatong/dataclasses-json.git",
                "ref": req_hash,
            }
        },
        "develop": {},
    }

    with pipenv_instance_pypi() as p:
        with open(p.lockfile_path, "w") as f:
            json.dump(lockfile, f)

        c = p.pipenv("requirements")
        assert c.returncode == 0
        assert "dataclasses-json" in c.stdout
        assert req_hash in c.stdout


@pytest.mark.requirements
def test_requirements_markers_get_included(pipenv_instance_pypi):
    package, version, markers = "werkzeug", "==2.1.2", "python_version >= '3.7'"
    lockfile = {
        "_meta": {"sources": []},
        "default": {
            package: {
                "hashes": [
                    "sha256:1ce08e8093ed67d638d63879fd1ba3735817f7a80de3674d293f5984f25fb6e6",
                    "sha256:72a4b735692dd3135217911cbeaa1be5fa3f62bffb8745c5215420a03dc55255",
                ],
                "markers": markers,
                "version": version,
            }
        },
        "develop": {},
    }

    with pipenv_instance_pypi() as p:
        with open(p.lockfile_path, "w") as f:
            json.dump(lockfile, f)

        c = p.pipenv("requirements")
        assert c.returncode == 0
        assert f"{package}{version}; {markers}" in c.stdout


@pytest.mark.requirements
def test_requirements_markers_get_excluded(pipenv_instance_pypi):
    package, version, markers = "werkzeug", "==2.1.2", "python_version >= '3.7'"
    lockfile = {
        "_meta": {"sources": []},
        "default": {
            package: {
                "hashes": [
                    "sha256:1ce08e8093ed67d638d63879fd1ba3735817f7a80de3674d293f5984f25fb6e6",
                    "sha256:72a4b735692dd3135217911cbeaa1be5fa3f62bffb8745c5215420a03dc55255",
                ],
                "markers": markers,
                "version": version,
            }
        },
        "develop": {},
    }

    with pipenv_instance_pypi() as p:
        with open(p.lockfile_path, "w") as f:
            json.dump(lockfile, f)

        c = p.pipenv("requirements --exclude-markers")
        assert c.returncode == 0
        assert markers not in c.stdout


@pytest.mark.requirements
def test_requirements_hashes_get_included(pipenv_instance_pypi):
    package, version, markers = "werkzeug", "==2.1.2", "python_version >= '3.7'"
    first_hash = "sha256:1ce08e8093ed67d638d63879fd1ba3735817f7a80de3674d293f5984f25fb6e6"
    second_hash = (
        "sha256:72a4b735692dd3135217911cbeaa1be5fa3f62bffb8745c5215420a03dc55255"
    )
    lockfile = {
        "_meta": {"sources": []},
        "default": {
            package: {
                "hashes": [first_hash, second_hash],
                "markers": markers,
                "version": version,
            }
        },
        "develop": {},
    }

    with pipenv_instance_pypi() as p:
        with open(p.lockfile_path, "w") as f:
            json.dump(lockfile, f)

        c = p.pipenv("requirements --hash")
        assert c.returncode == 0
        assert (
            f"{package}{version}; {markers} --hash={first_hash} --hash={second_hash}"
            in c.stdout
        )


def test_requirements_generates_requirements_from_lockfile_without_env_var_expansion(
    pipenv_instance_pypi,
):
    lockfile = {
        "_meta": {
            "sources": [
                {
                    "name": "private_source",
                    "url": "https://${redacted_user}:${redacted_pwd}@private_source.org",
                    "verify_ssl": True,
                }
            ]
        },
        "default": {},
    }

    with pipenv_instance_pypi() as p:
        with open(p.lockfile_path, "w") as f:
            json.dump(lockfile, f)

        with temp_environ():
            os.environ["redacted_user"] = "example_user"
            os.environ["redacted_pwd"] = "example_pwd"
            c = p.pipenv("requirements")
            assert c.returncode == 0

            assert (
                "-i https://${redacted_user}:${redacted_pwd}@private_source.org"
                in c.stdout
            )


@pytest.mark.requirements
@pytest.mark.parametrize(
    "deps, include_hashes, include_markers, expected",
    [
        (
            {"django-storages": {"version": "==1.12.3", "extras": ["azure"]}},
            True,
            True,
            ["django-storages[azure]==1.12.3"],
        ),
        (
            {
                "evotum-cripto": {
                    "file": "https://gitlab.com/eVotUM/Cripto-py/-/archive/develop/Cripto-py-develop.zip"
                }
            },
            True,
            True,
            [
                "https://gitlab.com/eVotUM/Cripto-py/-/archive/develop/Cripto-py-develop.zip"
            ],
        ),
        (
            {
                "pyjwt": {
                    "git": "https://github.com/jpadilla/pyjwt.git",
                    "ref": "7665aa625506a11bae50b56d3e04413a3dc6fdf8",
                    "extras": ["crypto"],
                }
            },
            True,
            True,
            [
                "pyjwt[crypto] @ git+https://github.com/jpadilla/pyjwt.git@7665aa625506a11bae50b56d3e04413a3dc6fdf8"
            ],
        ),
    ],
)
def test_requirements_from_deps(deps, include_hashes, include_markers, expected):
    result = requirements_from_lockfile(deps, include_hashes, include_markers)
    assert result == expected
