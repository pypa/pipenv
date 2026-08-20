import pytest

from pipenv.exceptions import PipenvUsageError
from pipenv.utils.dependencies import install_req_from_pipfile
from pipenv.vendor.plette.models.base import DataValidationError
from pipenv.vendor.plette.models.packages import PackageSpecfiers


def test_plette_accepts_skip_resolver():
    PackageSpecfiers.validate(
        {"path": ".", "editable": True, "skip_resolver": True}
    )


def test_install_requirement_accepts_skip_resolver():
    _, _, requirement = install_req_from_pipfile(
        "example", {"version": "*", "skip_resolver": True}
    )

    assert requirement == "example"


def test_plette_rejects_unrecognized_key():
    with pytest.raises(DataValidationError, match=r"Unrecognized.*commit"):
        PackageSpecfiers.validate({"git": "https://example.test/repo.git", "commit": "abc"})


def test_install_requirement_rejects_unrecognized_key():
    with pytest.raises(
        PipenvUsageError,
        match=r"Unrecognized option\(s\).*'example'.*commit",
    ):
        install_req_from_pipfile(
            "example",
            {"git": "https://example.test/repo.git", "commit": "abc"},
        )
