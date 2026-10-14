from pathlib import Path

import pytest


@pytest.mark.urls
@pytest.mark.extras
@pytest.mark.install
def test_install_uri_with_extras(pipenv_instance_file_pypi):
    with pipenv_instance_file_pypi() as p:
        whl = Path(
            Path(__file__).resolve().parent.parent
            / "pypi"
            / "plette"
            / "plette-0.2.2-py2.py3-none-any.whl"
        )
        try:
            whl = whl.resolve()
        except OSError:
            whl = whl.absolute()
        file_uri = whl.as_uri()
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "testindex"

[packages]
plette = {{file = "{file_uri}", extras = ["validation"]}}
"""
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "plette" in p.lockfile["default"]
        assert "cerberus" in p.lockfile["default"]


@pytest.mark.urls
@pytest.mark.extras
@pytest.mark.install
@pytest.mark.skip_lock
def test_install_uri_with_extras_skip_lock(pipenv_instance_file_pypi):
    """--skip-lock builds the pip install line via
    install_req_from_pipfile() -> file_path_from_pipfile(), a separate
    code path from the normal/locked install above - regression for a
    Copilot PR review finding that this path appended "[extras]"
    directly onto a file:// URL instead of using the PEP 508
    "name[extras] @ url" form, breaking pip's archive-extension
    detection.
    """
    with pipenv_instance_file_pypi() as p:
        whl = Path(
            Path(__file__).resolve().parent.parent
            / "pypi"
            / "plette"
            / "plette-0.2.2-py2.py3-none-any.whl"
        )
        try:
            whl = whl.resolve()
        except OSError:
            whl = whl.absolute()
        file_uri = whl.as_uri()
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "testindex"

[packages]
plette = {{file = "{file_uri}", extras = ["validation"]}}
"""
            f.write(contents)
        c = p.pipenv("install --skip-lock")
        assert c.returncode == 0
        c = p.pipenv("run pip freeze")
        assert c.returncode == 0
        assert "plette" in c.stdout.lower()
        assert "cerberus" in c.stdout.lower()


@pytest.mark.star
@pytest.mark.install
def test_install_major_version_star_specifier(pipenv_instance_file_pypi):
    """Test that major version star specifiers like '1.*' work correctly."""
    with pipenv_instance_file_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "pypi"

[packages]
six = "==1.*"
"""
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "six" in p.lockfile["default"]


@pytest.mark.star
@pytest.mark.install
def test_install_full_wildcard_specifier(pipenv_instance_file_pypi):
    """Test that full wildcard specifiers '*' work correctly."""
    with pipenv_instance_file_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "pypi"

[packages]
requests = "*"
"""
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]


@pytest.mark.star
@pytest.mark.install
def test_install_single_equals_star_specifier(pipenv_instance_file_pypi):
    """Test that single equals star specifiers like '=8.*' work correctly."""
    with pipenv_instance_file_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "pypi"

[packages]
requests = "==2.*"
"""
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "requests" in p.lockfile["default"]
        assert p.lockfile["default"]["requests"]["version"].startswith("==2.")


@pytest.mark.star
@pytest.mark.install
def test_install_command_with_star_specifier(pipenv_instance_file_pypi):
    """Test that star specifiers work when used in the install command."""
    with pipenv_instance_file_pypi() as p:
        # Initialize pipfile first
        with open(p.pipfile_path, "w") as f:
            contents = f"""
[[source]]
url = "{p.index_url}"
verify_ssl = true
name = "pypi"

[packages]
"""
            f.write(contents)

        # Test with single equals and star specifier
        c = p.pipenv("install urllib3==1.*")
        assert c.returncode == 0
        assert "urllib3" in p.lockfile["default"]

