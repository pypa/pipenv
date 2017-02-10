import delegator

import pipenv.project

class TestProject():

    def test_project(self):
        proj = pipenv.project.Project()
        assert proj.name == 'pipenv'
        assert proj.pipfile_exists
        assert proj.virtualenv_exists

    def test_pew_by_default(self):
        proj = pipenv.project.Project()
        assert proj.virtualenv_location.endswith('.local/share/virtualenvs/pipenv')

    def test_proper_names(self):
        proj = pipenv.project.Project()
        assert proj.virtualenv_location in proj.proper_names_location
        assert isinstance(proj.proper_names, list)

    def test_download_location(self):
        proj = pipenv.project.Project()
        assert proj.virtualenv_location in proj.download_location
        assert proj.download_location.endswith('downloads')

    def test_parsed_pipfile(self):
        proj = pipenv.project.Project()

        # Create test space.
        delegator.run('mkdir test_pipfile')
        with open('test_pipfile/Pipfile', 'w') as f:
            f.write('[[source]]\nurl = \'https://pypi.python.org/simple\'\n'
                    'verify_ssl = true\n\n\n[packages]\n'
                    'requests = { extras = [\'socks\'] }')

        proj._pipfile_location = 'test_pipfile/Pipfile'
        pfile = proj.parsed_pipfile

        # Cleanup test space.
        delegator.run('rm -fr test_pipfile')

        assert 'source' in pfile
        assert pfile['source'][0]['url'] == 'https://pypi.python.org/simple'

        assert 'packages' in pfile
        assert pfile['packages']['requests'] == {'extras': ['socks']}
