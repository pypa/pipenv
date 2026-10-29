"""``pipenv uninstall`` exits non-zero when ``pip uninstall`` fails."""

from unittest import mock

import pytest

from pipenv.routines.context import RoutineContext
from pipenv.routines.uninstall import _uninstall_from_environment, do_uninstall


def _project():
    project = mock.MagicMock()
    project.lockfile.content = {"default": {}, "develop": {"pytest": {}}}
    project.lockfile.meta.return_value = {}
    project.pipfile.generate_entry.return_value = ("requests", "requests", {"version": "*"})
    project.pipfile.remove_package.return_value = True
    project.pipfile.get_section.return_value = {"pytest": "*"}
    return project


@pytest.fixture(autouse=True)
def _patch_resolution(monkeypatch):
    monkeypatch.setattr("pipenv.routines.uninstall.venv_resolve_deps", mock.MagicMock(return_value={}))
    monkeypatch.setattr(
        "pipenv.routines.uninstall.expansive_install_req_from_line",
        mock.MagicMock(return_value=(mock.MagicMock(), None)),
    )


@pytest.mark.parametrize("succeeded, expected_code", [(True, 0), (False, 1)])
def test_uninstall_package_exit_code(monkeypatch, succeeded, expected_code):
    monkeypatch.setattr(
        "pipenv.routines.uninstall._uninstall_from_environment",
        mock.MagicMock(return_value=succeeded),
    )

    with mock.patch("pipenv.routines.uninstall.sys.exit") as exit_mock:
        do_uninstall(_project(), RoutineContext.from_cli(packages=("requests",)))

    exit_mock.assert_called_once_with(expected_code)


@pytest.mark.parametrize("succeeded, expected_code", [(True, 0), (False, 1)])
def test_uninstall_all_dev_exit_code(monkeypatch, succeeded, expected_code):
    monkeypatch.setattr(
        "pipenv.routines.uninstall._uninstall_from_environment",
        mock.MagicMock(return_value=succeeded),
    )

    with mock.patch("pipenv.routines.uninstall.sys.exit") as exit_mock:
        do_uninstall(_project(), RoutineContext.from_cli(all_dev=True))

    exit_mock.assert_called_once_with(expected_code)


def test_uninstall_without_virtualenv_explains_the_failure():
    project = mock.MagicMock()
    project.environment.activated.return_value.__enter__.return_value = False

    with mock.patch("pipenv.routines.uninstall.console.print") as print_mock:
        assert _uninstall_from_environment(project, "requests") is False

    print_mock.assert_called_once()
    message = print_mock.call_args.args[0]
    assert "No virtualenv found" in message
    assert "requests" in message
