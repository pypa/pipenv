# -*- coding=utf-8 -*-
import pytest
import os
from pipenv.project import Project
import unittest


@pytest.mark.project
@pytest.mark.sources
def test_get_cached_source(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:

        # Make sure unparseable packages don't wind up in the pipfile
        # Escape $ for shell input
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "{0}"
verify_ssl = false
name = "testindex"

[[source]]
url = "https://pypi.python.org/simple"
verify_ssl = "true"
name = "pypi"

[packages]
pytz = "*"
six = {{version = "*", index = "pypi"}}

[dev-packages]
            """.format(os.environ['PIPENV_TEST_INDEX']).strip()
            f.write(contents)
        c = p.pipenv('lock')
        assert c.return_code == 0
        project = Project()
        sources = [
            ['pypi', 'https://pypi.python.org/simple'],
            ['testindex', os.environ.get('PIPENV_TEST_INDEX')]
        ]
        for src in sources:
            name, url = src
            source = [s for s in project.pipfile_sources if s.get('name') == name]
            assert source
            source = source[0]
            assert source['name'] == name
            assert source['url'] == url
            assert unittest.assertDictEqual(source, project.get_source(name=name))
            assert unittest.assertDictEqual(source, project.get_source(url=url))
            assert unittest.assertDictEqual(source, project.find_source(name))
            assert unittest.assertDictEqual(source, project.find_source(url))


@pytest.mark.project
@pytest.mark.sources
def test_get_uncached_source(PipenvInstance, pypi):
    with PipenvInstance(pypi=pypi, chdir=True) as p:

        # Make sure unparseable packages don't wind up in the pipfile
        # Escape $ for shell input
        with open(p.pipfile_path, 'w') as f:
            contents = """
[[source]]
url = "{0}"
verify_ssl = false
name = "testindex"

[[source]]
url = "https://pypi.python.org/simple"
verify_ssl = "true"
name = "pypi"

[packages]
pytz = "*"
six = {{version = "*", index = "pypi"}}

[dev-packages]
            """.format(os.environ['PIPENV_TEST_INDEX']).strip()
            f.write(contents)
        project = Project()
        sources = [
            ['pypi', 'https://pypi.python.org/simple'],
            ['testindex', os.environ.get('PIPENV_TEST_INDEX')]
        ]
        for src in sources:
            name, url = src
            source = [s for s in project.pipfile_sources if s.get('name') == name]
            assert source
            source = source[0]
            assert source['name'] == name
            assert source['url'] == url
            assert unittest.assertDictEqual(source, project.get_source(name=name))
            assert unittest.assertDictEqual(source, project.get_source(url=url))
            assert unittest.assertDictEqual(source, project.find_source(name))
            assert unittest.assertDictEqual(source, project.find_source(url))
