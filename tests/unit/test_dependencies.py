from pipenv.utils.dependencies import clean_resolved_dep


def test_clean_resolved_dep_with_vcs_url():
    project = {}  # Mock project object, adjust as needed
    dep = {
        "name": "example-package",
        "git": "git+https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/username/repo.git",
        "ref": "main"
    }

    result = clean_resolved_dep(project, dep)

    assert "example-package" in result
    assert result["example-package"]["git"] == "git+https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/username/repo.git"
    assert result["example-package"]["ref"] == "main"

def test_clean_resolved_dep_with_vcs_url_and_extras():
    project = {}  # Mock project object, adjust as needed
    dep = {
        "name": "example-package",
        "git": "git+https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/username/repo.git[extra1,extra2]",
        "ref": "main"
    }

    result = clean_resolved_dep(project, dep)

    assert "example-package" in result
    assert result["example-package"]["git"] == "git+https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/username/repo.git[extra1,extra2]"
    assert result["example-package"]["ref"] == "main"
    assert result["example-package"]["extras"] == ["extra1", "extra2"]
