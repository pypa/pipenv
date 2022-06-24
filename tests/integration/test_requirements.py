import json
import os
import pytest

from pipenv.utils.shell import temp_environ


@pytest.mark.requirements
def test_requirements_generates_requirements_from_lockfile(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        packages = ('requests', '2.14.0')
        dev_packages = ('flask', '0.12.2')
        with open(p.pipfile_path, 'w') as f:
            contents = f"""
            [packages]
            {packages[0]}= "=={packages[1]}"
            [dev-packages]
            {dev_packages[0]}= "=={dev_packages[1]}"
            """.strip()
            f.write(contents)
        p.pipenv('lock')
        c = p.pipenv('requirements')
        assert c.returncode == 0
        assert f'{packages[0]}=={packages[1]}' in c.stdout
        assert f'{dev_packages[0]}=={dev_packages[1]}' not in c.stdout

        d = p.pipenv('requirements --dev')
        assert d.returncode == 0
        assert f'{packages[0]}=={packages[1]}' in d.stdout
        assert f'{dev_packages[0]}=={dev_packages[1]}' in d.stdout

        e = p.pipenv('requirements --dev-only')
        assert e.returncode == 0
        assert f'{packages[0]}=={packages[1]}' not in e.stdout
        assert f'{dev_packages[0]}=={dev_packages[1]}' in e.stdout

        e = p.pipenv('requirements --hash')
        assert e.returncode == 0
        assert f'{packages[0]}=={packages[1]}' in e.stdout
        for value in p.lockfile['default'].values():
            for hash in value['hashes']:
                assert f' --hash={hash}' in e.stdout


@pytest.mark.requirements
def test_requirements_generates_requirements_from_lockfile_multiple_sources(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        packages = ('requests', '2.14.0')
        dev_packages = ('flask', '0.12.2')
        with open(p.pipfile_path, 'w') as f:
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
        l = p.pipenv('lock')
        assert l.returncode == 0
        c = p.pipenv('requirements')
        assert c.returncode == 0

        assert '-i https://pypi.org/simple' in c.stdout
        assert '--extra-index-url https://some_other_source.org' in c.stdout

@pytest.mark.requirements
def test_requirements_with_git_requirements(PipenvInstance):
    req_name, req_hash = 'example-repo', 'cc858e89f19bc0dbd70983f86b811ab625dc9292'
    lockfile = {
        "_meta": {"sources": []},
        "default": {
            req_name: {
                "editable": True,
                "git": F"ssh://git@bitbucket.org/code/{req_name}.git",
                "ref": req_hash
            }
        },
        "develop": {}
    }

    with PipenvInstance(chdir=True) as p:
        with open(p.lockfile_path, 'w') as f:
            json.dump(lockfile, f)

        c = p.pipenv('requirements')
        assert c.returncode == 0
        assert req_name in c.stdout
        assert req_hash in c.stdout


@pytest.mark.requirements
def test_requirements_markers_get_included(PipenvInstance):
    package, version, markers = "werkzeug", "==2.1.2", "python_version >= '3.7'"
    lockfile = {
        "_meta": {"sources": []},
        "default": {
            package: {
                "hashes": [
                    "sha256:1ce08e8093ed67d638d63879fd1ba3735817f7a80de3674d293f5984f25fb6e6",
                    "sha256:72a4b735692dd3135217911cbeaa1be5fa3f62bffb8745c5215420a03dc55255"
                ],
                "markers": markers,
                "version": version
            }
        },
        "develop": {}
    }

    with PipenvInstance(chdir=True) as p:
        with open(p.lockfile_path, 'w') as f:
            json.dump(lockfile, f)

        c = p.pipenv('requirements --markers')
        assert c.returncode == 0
        assert f'{package}{version}; {markers}' in c.stdout


def test_requirements_generates_requirements_from_lockfile_without_env_var_expansion(
    PipenvInstance,
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

    with PipenvInstance(chdir=True) as p:
        with open(p.lockfile_path, "w") as f:
            json.dump(lockfile, f)

        with temp_environ():
            os.environ['redacted_user'] = "example_user"
            os.environ['redacted_pwd'] = "example_pwd"
            c = p.pipenv("requirements")
            assert c.returncode == 0

            assert (
                "-i https://${redacted_user}:${redacted_pwd}@private_source.org"
                in c.stdout
            )
