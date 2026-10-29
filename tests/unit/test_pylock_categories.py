"""Category selection must survive pylock conversion and requirement generation."""

import json

import pytest

from pipenv.utils.locking import Lockfile
from pipenv.utils.pylock import PylockFile, PylockFormatError

PY312 = {"python_version": "3.12", "python_full_version": "3.12.4"}


def _pylock(tmp_path, packages, groups=("dev", "lint", "docs")):
    return PylockFile(
        tmp_path / "pylock.toml",
        {
            "lock-version": "1.0",
            "created-by": "test",
            "dependency-groups": list(groups),
            "default-groups": ["default"],
            "packages": packages,
        },
    )


def _requirements(tmp_path, data, category, environment=PY312):
    lock = Lockfile.from_data(str(tmp_path), data, meta_from_project=False)
    return {
        dep.name: line
        for dep, line in lock.get_requirements(categories=[category])
        if dep.markers is None or dep.markers.evaluate(environment=environment)
    }


@pytest.mark.parametrize("marker", ["'dev'in dependency_groups", '"dev" in dependency_groups'])
def test_dev_marker_whitespace_does_not_leak_into_production(tmp_path, marker):
    pylock = _pylock(tmp_path, [{"name": "pytest", "version": "9.0", "marker": marker}])

    converted = pylock.convert_to_pipenv_lockfile(environment=PY312)

    assert _requirements(tmp_path, converted, "default") == {}
    assert _requirements(tmp_path, converted, "develop") == {"pytest": "pytest==9.0"}


def test_custom_categories_remain_separate(tmp_path):
    pylock = _pylock(tmp_path, [
        {"name": "ruff", "version": "0.5", "marker": "'lint' in dependency_groups"},
        {"name": "sphinx", "version": "8.0", "marker": "'docs' in dependency_groups"},
        {"name": "requests", "version": "2.32"},
    ])

    converted = pylock.convert_to_pipenv_lockfile(environment=PY312)

    assert _requirements(tmp_path, converted, "lint") == {"ruff": "ruff==0.5"}
    assert _requirements(tmp_path, converted, "docs") == {"sphinx": "sphinx==8.0"}
    assert _requirements(tmp_path, converted, "develop") == {}
    assert _requirements(tmp_path, converted, "default") == {"requests": "requests==2.32"}


def test_shared_package_keeps_each_categorys_environment_condition(tmp_path):
    pylock = _pylock(tmp_path, [{
        "name": "tomli", "version": "2.0.1",
        "marker": "(python_version < '3.11') or ('lint' in dependency_groups)",
    }])

    converted = pylock.convert_to_pipenv_lockfile(environment=PY312)

    assert _requirements(tmp_path, converted, "default") == {}
    assert _requirements(tmp_path, converted, "default", {"python_version": "3.10"}) == {
        "tomli": 'tomli==2.0.1; python_version < "3.11"'
    }
    assert _requirements(tmp_path, converted, "lint") == {"tomli": "tomli==2.0.1"}


@pytest.mark.parametrize(
    "marker, categories, expected",
    [
        ("'lint' in dependency_groups and 'docs' not in dependency_groups", ["lint"], {"ruff"}),
        ("'lint' in dependency_groups and 'docs' not in dependency_groups", ["lint", "docs"], set()),
        ("'lint' in dependency_groups and 'docs' in dependency_groups", ["lint", "docs"], {"ruff"}),
        ("'lint' in dependency_groups and 'docs' in dependency_groups", ["lint"], set()),
    ],
)
def test_marker_uses_only_the_requested_groups(tmp_path, marker, categories, expected):
    pylock = _pylock(tmp_path, [{"name": "ruff", "version": "0.5", "marker": marker}])

    converted = pylock.convert_to_pipenv_lockfile(environment=PY312, categories=categories)

    actual = set().union(*(_requirements(tmp_path, converted, category) for category in categories))
    assert actual == expected


def test_duplicate_versions_are_narrowed_per_selected_category(tmp_path):
    pylock = _pylock(tmp_path, [
        {"name": "demo", "version": "1.0", "marker": "'lint' in dependency_groups"},
        {"name": "demo", "version": "2.0", "marker": "'docs' in dependency_groups"},
    ])

    for category, version in [("lint", "1.0"), ("docs", "2.0")]:
        pylock.check_environment(dependency_groups={category}, environment=PY312)
        converted = pylock.convert_to_pipenv_lockfile(environment=PY312, categories=[category])
        assert _requirements(tmp_path, converted, category) == {"demo": f"demo=={version}"}

    with pytest.raises(PylockFormatError, match="demo"):
        pylock.check_environment(dependency_groups={"lint", "docs"}, environment=PY312)


def test_export_round_trip_preserves_custom_and_shared_packages(tmp_path):
    data = {
        "_meta": {"sources": [], "requires": {}, "hash": {"sha256": ""}, "pipfile-spec": 6},
        "default": {"shared": {"version": "==1.0", "markers": "python_version < '3.11'"}},
        "develop": {"shared": {"version": "==1.0"}},
        "lint": {"shared": {"version": "==1.0"}, "ruff": {"version": "==0.5"}},
        "docs": {"shared": {"version": "==1.0"}, "sphinx": {"version": "==8.0"}},
    }
    path = tmp_path / "Pipfile.lock"
    path.write_text(json.dumps(data))

    pylock = PylockFile.from_lockfile(path)
    pylock.write()
    loaded = PylockFile.from_path(pylock.path)
    converted = loaded.convert_to_pipenv_lockfile(environment=PY312)

    assert set(loaded.dependency_groups) == {"dev", "lint", "docs"}
    assert len([pkg for pkg in loaded.packages if pkg["name"] == "shared"]) == 1
    for category in ("default", "develop", "lint", "docs"):
        assert _requirements(tmp_path, converted, category) == _requirements(tmp_path, data, category)


def test_unconditional_shared_package_survives_custom_only_round_trip(tmp_path):
    data = {
        "_meta": {"sources": [], "requires": {}},
        "default": {"shared": {"version": "==1.0"}},
        "develop": {},
        "lint": {"shared": {"version": "==1.0"}},
    }
    path = tmp_path / "Pipfile.lock"
    path.write_text(json.dumps(data))

    converted = PylockFile.from_lockfile(path).convert_to_pipenv_lockfile(categories=["lint"])

    assert _requirements(tmp_path, converted, "lint") == {"shared": "shared==1.0"}


@pytest.mark.parametrize("categories, expected", [
    (["packages"], {"runtime"}),
    (["dev-packages"], {"devonly"}),
    (["lint"], {"lintonly"}),
    (["packages", "lint"], {"runtime", "lintonly"}),
])
def test_project_loads_only_the_requested_pylock_categories(tmp_path, monkeypatch, categories, expected):
    from pipenv.project import Project
    from pipenv.routines.install import _check_pylock_environment

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PIPENV_PIPFILE", str(tmp_path / "Pipfile"))
    (tmp_path / "Pipfile").write_text("[packages]\n[dev-packages]\n[lint]\n[docs]\n")
    pylock = _pylock(tmp_path, [
        {"name": "runtime", "version": "1.0", "marker": "'default' in dependency_groups"},
        {"name": "devonly", "version": "1.0", "marker": "'dev'in dependency_groups"},
        {"name": "lintonly", "version": "1.0", "marker": "'lint' in dependency_groups"},
        {"name": "docsonly", "version": "1.0", "marker": "'docs' in dependency_groups", "requires-python": ">=99"},
    ])
    pylock.write()
    project = Project(chdir=False)

    # The incompatible docs package must not prevent a default, dev, or lint install.
    _check_pylock_environment(project, categories, allow_global=True)
    lock = project.get_or_create_lockfile(categories=categories)

    assert {dep.name for dep, _ in lock.get_requirements(categories=categories)} == expected


def test_install_validates_custom_group_python_requirement(tmp_path):
    from unittest.mock import Mock

    from pipenv.exceptions import PipenvException
    from pipenv.routines.install import _check_pylock_environment

    pylock = _pylock(tmp_path, [{
        "name": "ruff", "version": "0.5", "marker": "'lint' in dependency_groups", "requires-python": ">=99",
    }])
    pylock.write()
    project = Mock()
    project.lockfile.pylock_location = str(pylock.path)

    with pytest.raises(PipenvException, match="of package 'ruff'"):
        _check_pylock_environment(project, ["lint"], allow_global=True)


def test_lock_data_keeps_unselected_pylock_categories(tmp_path, monkeypatch):
    """Locking a subset of categories must not empty the others it writes back."""
    from pipenv.project import Project

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PIPENV_PIPFILE", str(tmp_path / "Pipfile"))
    (tmp_path / "Pipfile").write_text("[packages]\n[dev-packages]\n[lint]\n")
    _pylock(tmp_path, [
        {"name": "runtime", "version": "1.0", "marker": "'default' in dependency_groups"},
        {"name": "devonly", "version": "1.0", "marker": "'dev' in dependency_groups"},
        {"name": "lintonly", "version": "1.0", "marker": "'lint' in dependency_groups"},
    ]).write()
    project = Project(chdir=False)

    lockfile = project.lockfile.as_dict(categories=["lint"])

    assert list(lockfile["default"]) == ["runtime"]
    assert list(lockfile["develop"]) == ["devonly"]
    assert list(lockfile["lint"]) == ["lintonly"]


def _lockfile(tmp_path, sections):
    data = {"_meta": {"sources": [], "requires": {}}, "default": {}, "develop": {}, **sections}
    path = tmp_path / "Pipfile.lock"
    path.write_text(json.dumps(data))
    return path


def test_export_normalizes_group_names_and_restores_categories(tmp_path):
    path = _lockfile(tmp_path, {
        "develop": {"pytest": {"version": "==9.0"}},
        "My_Docs": {"sphinx": {"version": "==8.0"}},
    })

    pylock = PylockFile.from_lockfile(path, dev_groups=["dev", "Test"])
    pylock.write()
    loaded = PylockFile.from_path(pylock.path)

    assert loaded.dependency_groups == ["dev", "test", "my-docs"]
    assert [pkg["marker"] for pkg in loaded.packages] == [
        "'dev' in dependency_groups or 'test' in dependency_groups",
        "'my-docs' in dependency_groups",
    ]
    converted = loaded.convert_to_pipenv_lockfile(environment=PY312)
    # The --dev-groups alias reads back as develop, not as a "test" category.
    assert sorted(key for key in converted if key != "_meta") == ["My_Docs", "default", "develop"]
    assert list(converted["develop"]) == ["pytest"]
    assert list(converted["My_Docs"]) == ["sphinx"]
    assert loaded.groups_for_categories(["My_Docs"]) == {"my-docs"}


@pytest.mark.parametrize("sections, dev_groups", [
    ({"docs": {}}, ["dev", "docs"]),
    ({"dev": {}}, None),
    ({"my_docs": {}, "My-Docs": {}}, None),
    ({}, ["default"]),
])
def test_export_rejects_categories_sharing_a_group(tmp_path, sections, dev_groups):
    path = _lockfile(tmp_path, sections)

    with pytest.raises(ValueError, match="both map to the dependency group"):
        PylockFile.from_lockfile(path, dev_groups=dev_groups)
