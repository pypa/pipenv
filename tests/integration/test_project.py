# -*- coding=utf-8 -*-
import pytest
import os
from pipenv.project import Project
from pipenv.utils import temp_environ
from pipenv.patched import pipfile


@pytest.mark.project
@pytest.mark.sources
@pytest.mark.environ
def test_pipfile_envvar_expansion(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        with temp_environ():
            with open(p.pipfile_path, 'w') as f:
                f.write("""
[[source]]
url = 'https://${TEST_HOST}/simple'
verify_ssl = false
name = "pypi"

[packages]
pytz = "*"
                """.strip())
            os.environ['TEST_HOST'] = 'localhost:5000'
            project = Project()
            assert project.sources[0]['url'] == 'https://localhost:5000/simple'
            assert 'localhost:5000' not in str(pipfile.load(p.pipfile_path))


@pytest.mark.project
@pytest.mark.sources
@pytest.mark.parametrize('lock_first', [True, False])
def test_get_source(PipenvInstance, pypi, lock_first):
    with PipenvInstance(pypi=pypi, chdir=True) as p:
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

        if lock_first:
            # force source to be cached
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
            assert sorted(source.items()) == sorted(project.get_source(name=name).items())
            assert sorted(source.items()) == sorted(project.get_source(url=url).items())
            assert sorted(source.items()) == sorted(project.find_source(name).items())
            assert sorted(source.items()) == sorted(project.find_source(url).items())
