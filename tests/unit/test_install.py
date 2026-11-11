import queue
from unittest.mock import MagicMock

import pytest

from pipenv.routines.context import RoutineContext
from pipenv.routines import install


def test_batch_install_reports_missing_index_without_masking_error(monkeypatch):
    project = MagicMock()
    project.settings = {}
    project.sources.default = {"name": "missing"}
    project.environment.is_satisfied.return_value = False

    dependency = MagicMock()
    dependency.name = "example"
    dependency.markers = None

    monkeypatch.setattr(install, "get_source_list", lambda *args, **kwargs: [])

    with pytest.raises(SystemExit):
        install.batch_install(
            project,
            RoutineContext.from_cli(system=True),
            [(dependency, "example==1.0")],
            {},
            queue.Queue(maxsize=1),
            None,
        )


REMOTE_REQUIREMENTS_URL = "https://example.com/requirements.txt"


def _remote_requirements_project():
    project = MagicMock()
    project.pipfile.exists = True
    project.s.PIPENV_USE_SYSTEM = False
    project.s.PIPENV_MAX_RETRIES = 0
    project.path_to.side_effect = lambda path: path
    return project


def test_install_validations_imports_remote_requirements(monkeypatch, tmp_path):
    """`pipenv install -r <url>` imports the file it downloads.

    download_file() opens the temporary file by name, which Windows refuses
    while the file is still open, and the file must still exist when
    import_requirements() reads it.
    """

    def fake_download_file(url, filename, max_retries=1):
        with open(filename, "wb") as f:
            f.write(b"six\n")

    imported = []

    def fake_import_requirements(project, r=None, dev=False, categories=None):
        with open(r, "rb") as f:
            imported.append(f.read())

    monkeypatch.setattr(install, "download_file", fake_download_file)
    monkeypatch.setattr(install, "import_requirements", fake_import_requirements)

    install.do_install_validations(
        _remote_requirements_project(),
        RoutineContext.from_cli(requirementstxt=REMOTE_REQUIREMENTS_URL),
        tmp_path,
    )

    assert imported == [b"six\n"]


def test_install_validations_reports_failed_remote_download(monkeypatch, tmp_path):
    def failing_download_file(url, filename, max_retries=1):
        raise OSError("Unable to download file")

    monkeypatch.setattr(install, "download_file", failing_download_file)

    with pytest.raises(SystemExit) as exc_info:
        install.do_install_validations(
            _remote_requirements_project(),
            RoutineContext.from_cli(requirementstxt=REMOTE_REQUIREMENTS_URL),
            tmp_path,
        )

    assert exc_info.value.code == 1
    assert list(tmp_path.iterdir()) == []
