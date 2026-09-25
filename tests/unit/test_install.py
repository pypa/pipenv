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
