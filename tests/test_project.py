from hashlib import sha256
from base64 import urlsafe_b64encode

import delegator

import pipenv.project

class TestProject():

    def test_project(self):
        proj = pipenv.project.Project()
        hash = urlsafe_b64encode(
            sha256(proj.pipfile_location.encode()).digest()[:6]).decode()

        assert proj.name == 'pipenv'
        assert proj.pipfile_exists
        assert proj.virtualenv_exists
        assert proj.virtualenv_name == 'pipenv-' + hash

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

        # Confirm source added correctly.
        assert 'source' in pfile
        assert pfile['source'][0]['url'] == 'https://pypi.python.org/simple'

        # Confirm requests is in packages as expected.
        assert 'packages' in pfile
        assert pfile['packages']['requests'] == {'extras': ['socks']}

    def test_add_package_to_pipfile(self):
        proj = pipenv.project.Project()

        # Create test space.
        delegator.run('mkdir test_add_to_pipfile')
        with open('test_add_to_pipfile/Pipfile', 'w') as f:
            f.write('[[source]]\nurl = \'https://pypi.python.org/simple\'\n'
                    'verify_ssl = true\n\n\n[packages]\n'
                    'requests = { extras = [\'socks\'] }')
        proj._pipfile_location = 'test_add_to_pipfile/Pipfile'

        proj.add_package_to_pipfile('Flask')
        proj.add_package_to_pipfile('Django==1.10.1', dev=True)
        p = proj.parsed_pipfile

        # Cleanup test space.
        delegator.run('rm -fr test_add_to_pipfile')

        # Confirm Flask added to packages.
        assert 'Flask' in p['packages']
        assert p['packages']['Flask'] == '*'

        # Confirm Django added to dev-packages.
        assert 'Django' in p['dev-packages']
        assert p['dev-packages']['Django'] == '==1.10.1'

    def test_remove_package_from_pipfile(self):
        proj = pipenv.project.Project()

        # Create test space.
        delegator.run('mkdir test_remove_from_pipfile')
        with open('test_remove_from_pipfile/Pipfile', 'w') as f:
            f.write('[[source]]\nurl = \'https://pypi.python.org/simple\'\n'
                    'verify_ssl = true\n\n\n[packages]\n'
                    'requests = { extras = [\'socks\'] }\nFlask = \'*\'\n\n\n'
                    '[dev-packages]\nclick = \'*\'\n')
        proj._pipfile_location = 'test_remove_from_pipfile/Pipfile'

        # Confirm initial state of Pipfile.
        p = proj.parsed_pipfile
        assert list(p['packages'].keys()) == ['requests', 'Flask']
        assert list(p['dev-packages'].keys()) == ['click']

        # Remove requests from packages and click from dev-packages.
        proj.remove_package_from_pipfile('requests')
        proj.remove_package_from_pipfile('click', dev=True)
        p = proj.parsed_pipfile

        # Cleanup test space.
        delegator.run('rm -fr test_remove_from_pipfile')

        # Confirm state of Pipfile.
        assert 'Flask' in p['packages']
        assert len(p['packages']) == 1

        assert 'dev-packages' not in p
