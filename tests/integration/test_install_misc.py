import os
import pytest

@pytest.mark.urls
@pytest.mark.extras
@pytest.mark.install
def test_install_uri_with_extras(pipenv_instance_private_pypi):
    file_uri = "http://localhost:8080/packages/plette/plette-0.2.2-py2.py3-none-any.whl"
    index = os.environ['PIPENV_TEST_INDEX']
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "{index}"
verify_ssl = false
name = "testindex"

[packages]
plette = {{file = "{file_uri}", extras = ["validation"]}}
""".format(file_uri=file_uri, index=index)
            f.write(contents)
        c = p.pipenv("install")
        assert c.returncode == 0
        assert "plette" in p.lockfile["default"]
