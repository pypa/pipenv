"""Unit tests for the ``pipenv.utils.sources.Sources`` subsystem.

These tests pin the behaviour of the ``Sources`` subsystem that was
extracted from ``pipenv.project.Project`` in task T_D.2. They cover the
constructor, the data accessors (the ``all`` property and
``pipfile_sources``), and the writer (``add_index_to_pipfile``) so that
future refactors of ``Project`` cannot silently regress any of these
behaviours.
"""

from __future__ import annotations

import pytest

from pipenv.project import Project
from pipenv.utils.sources import SourceNotFound, Sources

PIPFILE_SINGLE_SOURCE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]

[dev-packages]
"""

PIPFILE_MULTI_SOURCE = """\
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[[source]]
url = "https://example.com/simple"
verify_ssl = false
name = "example"

[packages]

[dev-packages]
"""


@pytest.fixture
def project_single(tmp_path, monkeypatch):
    """Project pointing at a Pipfile with a single PyPI source."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_SINGLE_SOURCE)
    monkeypatch.chdir(tmp_path)
    return Project(chdir=False)


@pytest.fixture
def project_multi(tmp_path, monkeypatch):
    """Project pointing at a Pipfile with two named sources."""
    pipfile = tmp_path / "Pipfile"
    pipfile.write_text(PIPFILE_MULTI_SOURCE)
    monkeypatch.chdir(tmp_path)
    return Project(chdir=False)


@pytest.mark.utils
def test_sources_constructor_takes_project(project_single):
    """``Sources(project)`` accepts a ``Project`` reference."""
    sources = Sources(project_single)
    assert sources is not None


@pytest.mark.utils
def test_project_sources_returns_sources_subsystem(project_single):
    """``project.sources`` returns a ``Sources`` subsystem instance,
    cached for the project lifetime."""
    assert isinstance(project_single.sources, Sources)
    # Cached: two accesses return the same instance.
    assert project_single.sources is project_single.sources


@pytest.mark.utils
def test_sources_all_returns_list_of_dicts(project_single):
    """``project.sources.all`` exposes the source list (formerly the
    ``project.sources`` data property)."""
    entries = project_single.sources.all
    assert isinstance(entries, list)
    assert len(entries) == 1
    assert entries[0]["name"] == "pypi"
    assert entries[0]["url"] == "https://pypi.org/simple"


@pytest.mark.utils
def test_sources_default_returns_first_source(project_single):
    """``Sources.default`` returns the first source (formerly
    ``project.sources_default``)."""
    default = project_single.sources.default
    assert default["name"] == "pypi"


@pytest.mark.utils
def test_sources_pipfile_sources_reads_from_pipfile(project_multi):
    """``Sources.pipfile_sources()`` returns the [[source]] tables from
    the Pipfile, ignoring any lockfile state."""
    sources = project_multi.sources.pipfile_sources()
    assert [s["name"] for s in sources] == ["pypi", "example"]


@pytest.mark.utils
def test_sources_index_urls_returns_url_list(project_multi):
    """``Sources.index_urls`` returns just the URL strings."""
    urls = project_multi.sources.index_urls
    assert "https://pypi.org/simple" in urls
    assert "https://example.com/simple" in urls


@pytest.mark.utils
def test_sources_get_source_by_name(project_multi):
    """``Sources.get_source(name=...)`` finds a source by name."""
    source = project_multi.sources.get_source(name="example")
    assert source["url"] == "https://example.com/simple"


@pytest.mark.utils
def test_sources_get_source_by_url(project_multi):
    """``Sources.get_source(url=...)`` finds a source by URL."""
    source = project_multi.sources.get_source(url="https://example.com/simple")
    assert source["name"] == "example"


@pytest.mark.utils
def test_sources_get_source_raises_when_missing(project_single):
    """``Sources.get_source`` raises ``SourceNotFound`` for unknown names."""
    with pytest.raises(SourceNotFound):
        project_single.sources.get_source(name="does-not-exist")


@pytest.mark.utils
def test_sources_find_source_resolves_name(project_multi):
    """``Sources.find_source`` resolves a source by name or URL."""
    by_name = project_multi.sources.find_source("example")
    by_url = project_multi.sources.find_source("https://example.com/simple")
    assert by_name["name"] == "example"
    assert by_url["name"] == "example"


@pytest.mark.utils
def test_sources_get_index_by_name_returns_match(project_multi):
    """``Sources.get_index_by_name`` returns the source dict for a name."""
    source = project_multi.sources.get_index_by_name("example")
    assert source is not None
    assert source["url"] == "https://example.com/simple"


@pytest.mark.utils
def test_sources_src_name_from_url_synthesises_unique(project_single):
    """``Sources.src_name_from_url`` produces a non-empty name string for
    a new URL not already present in the Pipfile."""
    name = project_single.sources.src_name_from_url("https://my-custom-index.example.com/simple")
    assert name
    assert isinstance(name, str)


@pytest.mark.utils
def test_sources_populate_source_fills_defaults():
    """``Sources.populate_source`` infers ``name`` and ``verify_ssl`` from
    ``url`` when missing."""
    out = Sources.populate_source({"url": "https://example.org/simple"})
    assert out["name"]
    assert out["verify_ssl"] is True


@pytest.mark.utils
def test_sources_populate_source_coerces_verify_ssl_string():
    """String ``verify_ssl`` values are coerced to bool."""
    out = Sources.populate_source({
        "url": "https://example.org/simple",
        "name": "x",
        "verify_ssl": "false",
    })
    assert out["verify_ssl"] is False


@pytest.mark.utils
def test_sources_add_index_to_pipfile_appends_new_source(project_single):
    """``Sources.add_index_to_pipfile`` appends a new [[source]] block and
    writes the Pipfile."""
    index_name = project_single.sources.add_index_to_pipfile(
        "https://new-index.example.com/simple", verify_ssl=True
    )
    assert index_name
    # The new source must show up in the persisted Pipfile.
    sources_after = project_single.sources.pipfile_sources()
    urls = [s["url"] for s in sources_after]
    assert "https://new-index.example.com/simple" in urls


@pytest.mark.utils
def test_sources_add_index_to_pipfile_returns_existing_name(project_multi):
    """Re-adding an existing URL returns its existing source name without
    creating a duplicate entry."""
    before = project_multi.sources.pipfile_sources()
    name = project_multi.sources.add_index_to_pipfile("https://example.com/simple")
    after = project_multi.sources.pipfile_sources()
    assert name == "example"
    assert len(before) == len(after)
