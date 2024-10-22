import os
import sys

import pytest

from pipenv.project import Project
from pipenv.utils.fileutils import normalize_path
from pipenv.utils.shell import temp_environ
from pipenv.vendor.plette import Pipfile


@pytest.mark.project
@pytest.mark.sources
@pytest.mark.environ
def test_pipfile_envvar_expansion(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p, temp_environ():
        with open(p.pipfile_path, "w") as f:
            f.write(
                """
[[source]]
url = 'https://${TEST_HOST}/simple'
verify_ssl = false
name = "pypi"

[packages]
pytz = "*"
                """.strip()
            )
        os.environ["TEST_HOST"] = "localhost:5000"
        project = Project()
        assert project.sources[0]["url"] == "https://localhost:5000/simple"
        assert "localhost:5000" not in str(Pipfile.load(open(p.pipfile_path)))
        print(str(Pipfile.load(open(p.pipfile_path))))


@pytest.mark.project
@pytest.mark.sources
@pytest.mark.parametrize("lock_first", [True, False])
def test_get_source(pipenv_instance_private_pypi, lock_first):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = false
name = "testindex"

[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
pytz = "*"
six = {{version = "*", index = "pypi"}}

[dev-packages]
            """.strip()
            f.write(contents)

        if lock_first:
            # force source to be cached
            c = p.pipenv("lock")
            assert c.returncode == 0
        project = Project()
        sources = [["pypi", "https://pypi.org/simple"], ["testindex", p.index_url]]
        for src in sources:
            name, url = src
            source = [s for s in project.pipfile_sources() if s.get("name") == name]
            assert source
            source = source[0]
            assert source["name"] == name
            assert source["url"] == url
            assert sorted(source.items()) == sorted(project.get_source(name=name).items())
            assert sorted(source.items()) == sorted(project.get_source(url=url).items())
            assert sorted(source.items()) == sorted(project.find_source(name).items())
            assert sorted(source.items()) == sorted(project.find_source(url).items())


@pytest.mark.install
@pytest.mark.project
@pytest.mark.parametrize("newlines", ["\n", "\r\n"])
def test_maintain_file_line_endings(pipenv_instance_pypi, newlines):
    with pipenv_instance_pypi() as p:
        # Initial pipfile + lockfile generation
        c = p.pipenv("install pytz")
        assert c.returncode == 0

        # Rewrite each file with parameterized newlines
        for fn in [p.pipfile_path, p.lockfile_path]:
            with open(fn) as f:
                contents = f.read()

            # message because of  https://github.com/pytest-dev/pytest/issues/3443
            with open(fn, "w", newline=newlines) as f:
                f.write(contents)

        # Run pipenv install to programmatically rewrite
        c = p.pipenv("install chardet")
        assert c.returncode == 0

        # Make sure we kept the right newlines
        for fn in [p.pipfile_path, p.lockfile_path]:
            with open(fn) as f:
                f.read()  # Consumes the content to detect newlines.
                actual_newlines = f.newlines
            assert (
                actual_newlines == newlines
            ), f"{actual_newlines!r} != {newlines!r} for {fn}"


@pytest.mark.project
@pytest.mark.sources
@pytest.mark.needs_internet
def test_many_indexes(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = false
name = "testindex"

[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://pypi.python.org/simple"
verify_ssl = true
name = "legacy"

[packages]
pytz = "*"
six = {{version = "*", index = "pypi"}}

[dev-packages]
            """.strip()
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0


@pytest.mark.project
@pytest.mark.virtualenv
@pytest.mark.skipif(
    os.name == "nt" and sys.version_info[:2] == (3, 8),
    reason="Seems to work on 3.8 but not via the CI",
)
def test_run_in_virtualenv(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("run pip freeze")
        assert c.returncode == 0
        assert "Creating a virtualenv" in c.stderr
        project = Project()
        c = p.pipenv("run pip install click")
        assert c.returncode == 0
        c = p.pipenv("install six")
        assert c.returncode == 0
        c = p.pipenv('run python -c "import click;print(click.__file__)"')
        assert c.returncode == 0
        assert normalize_path(c.stdout.strip()).startswith(
            normalize_path(str(project.virtualenv_location))
        )
        c = p.pipenv("clean --dry-run")
        assert c.returncode == 0
        assert "click" in c.stdout


@pytest.mark.project
@pytest.mark.sources
def test_no_sources_in_pipfile(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
pytest = "*"
            """.strip()
            f.write(contents)
        c = p.pipenv("install --skip-lock")
        assert c.returncode == 0
