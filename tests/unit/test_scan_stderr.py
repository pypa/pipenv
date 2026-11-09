"""Safety diagnostics must remain visible when scan runs quietly."""

from unittest import mock

import pytest

from pipenv.routines import scan


@pytest.mark.parametrize("quiet", [True, False])
@pytest.mark.parametrize(
    ("output", "error", "returncode"),
    [
        ("", "Safety API key is invalid\n", 1),
        ("", "Safety network error\n", 1),
        ('{"report_meta": {"vulnerabilities_found": 0}}', "", 0),
        ('{"report_meta": {"vulnerabilities_found": 0}}', "AuthlibDeprecationWarning\n", 0),
        ('{"report_meta": {"vulnerabilities_found": 1}}', "Safety warning\n", 64),
    ],
)
def test_scan_preserves_stderr(
    monkeypatch, tmp_path, capsys, quiet, output, error, returncode
):
    project = mock.MagicMock()
    project.lockfile.exists = True
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests==2.0\n")
    replacements = {
        "run_pep508_check": {},
        "check_pep508_requirements": None,
        "get_requirements": mock.Mock(stdout="requests==2.0\n"),
        "create_temp_requirements_file": str(requirements),
        "is_safety_installed": True,
        "project_python": "python",
        "build_safety_scan_options": ([], []),
        "run_safety_scan": (output, error, returncode),
    }
    for name, result in replacements.items():
        monkeypatch.setattr(scan, name, mock.Mock(return_value=result))

    with pytest.raises(SystemExit) as exc:
        scan.do_scan(project, system=True, quiet=quiet)

    assert exc.value.code == returncode
    captured = capsys.readouterr()
    if error and (not quiet or returncode != 0):
        assert captured.err.count(error) == 1
    else:
        assert captured.err == ""
    if quiet and output:
        assert "vulnerabilities found." in captured.out
    elif not quiet:
        assert captured.out == output
    assert not requirements.exists()
