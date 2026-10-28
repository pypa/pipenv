"""``pipenv install -r`` decodes the requirements file the way pip does."""

from unittest import mock

import pytest

from pipenv.utils.dependencies import import_requirements

CONTENT = "# dépendances\n-i https://private.example/simple\nrequests==2.31.0\n"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(CONTENT.encode("utf-16"), id="utf-16-bom"),
        pytest.param(b"\xef\xbb\xbf-i https://private.example/simple\nrequests==2.31.0\n", id="utf-8-bom"),
        pytest.param(CONTENT.encode("latin-1").replace(b"# d", b"# coding: latin-1\n# d", 1), id="coding-cookie"),
    ],
)
def test_import_requirements_decodes_like_pip(tmp_path, data):
    requirements = tmp_path / "requirements.txt"
    requirements.write_bytes(data)
    project = mock.MagicMock()

    with mock.patch(
        "pipenv.utils.dependencies.add_index_to_pipfile_with_trust_check", return_value="private"
    ) as add_index:
        import_requirements(project, r=str(requirements))

    assert add_index.call_args.args[1] == "https://private.example/simple"
    packages = project.pipfile.add_packages_batch.call_args.args[0]
    assert [string for _, string in packages] == ["requests==2.31.0"]
