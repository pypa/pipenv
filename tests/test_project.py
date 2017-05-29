from hashlib import sha256
from base64 import urlsafe_b64encode

import delegator

import pipenv.project


class TestProject():

    def test_project(self):
        proj = pipenv.project.Project()
        hash = urlsafe_b64encode(
            sha256(proj.pipfile_location.encode()).digest()[:6]).decode()

        # assert proj.name == 'pipenv'
        assert proj.pipfile_exists
        assert proj.virtualenv_exists
        # assert proj.virtualenv_name == 'pipenv-' + hash

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
        proj.add_package_to_pipfile('Click-ComPletiON')
        p = proj.parsed_pipfile

        # Cleanup test space.
        delegator.run('rm -fr test_add_to_pipfile')

        # Confirm Flask added to packages.
        assert 'Flask' in p['packages']
        assert p['packages']['Flask'] == '*'

        # Confirm Django added to dev-packages.
        assert 'Django' in p['dev-packages']
        assert p['dev-packages']['Django'] == '==1.10.1'

        # Confirm casing is normalized.
        assert 'click-completion' in p['packages']
        assert p['packages']['click-completion'] == '*'

    def test_remove_package_from_pipfile(self):
        proj = pipenv.project.Project()

        # Create test space.
        delegator.run('mkdir test_remove_from_pipfile')
        with open('test_remove_from_pipfile/Pipfile', 'w') as f:
            f.write('[[source]]\nurl = \'https://pypi.python.org/simple\'\n'
                    'verify_ssl = true\n\n\n[packages]\n'
                    'requests = { extras = [\'socks\'] }\nFlask = \'*\'\n\n\n'
                    '[dev-packages]\nclick = \'*\'\nDjango = \'*\'\n')
        proj._pipfile_location = 'test_remove_from_pipfile/Pipfile'

        # Confirm initial state of Pipfile.
        p = proj.parsed_pipfile
        assert list(p['packages'].keys()) == ['requests', 'Flask']
        assert list(p['dev-packages'].keys()) == ['click', 'Django']

        # Remove requests from packages and click from dev-packages.
        proj.remove_package_from_pipfile('requests')
        proj.remove_package_from_pipfile('click', dev=True)
        proj.remove_package_from_pipfile('DJANGO', dev=True)
        p = proj.parsed_pipfile

        # Cleanup test space.
        delegator.run('rm -fr test_remove_from_pipfile')

        # Confirm state of Pipfile.
        assert 'Flask' in p['packages']
        assert len(p['packages']) == 1

        assert 'dev-packages' not in p

    def test_internal_pipfile(self):
        proj = pipenv.project.Project()

        # Create test space.
        delegator.run('mkdir test_internal_pipfile')
        with open('test_internal_pipfile/Pipfile', 'w') as f:
            f.write('[[source]]\nurl = \'https://pypi.python.org/simple\'\n'
                    'verify_ssl = true\n\n\n[packages]\n'
                    'Requests = { extras = [\'socks\'] }\nFlask_Auth = \'*\'\n\n\n'
                    '[dev-packages]\nclick = \'*\'\nDjango = {git = '
                    '"https://github.com/django/django.git", ref="1.10"}\n')

        proj._pipfile_location = 'test_internal_pipfile/Pipfile'

        p = proj._pipfile

        # Test package names are normalized as expected.
        assert list(p['packages'].keys()) == ['requests', 'flask-auth']
        assert list(p['dev-packages'].keys()) == ['click', 'django']

        delegator.run('rm -fr test_internal_pipfile')

    def test_internal_lockfile(self):
        proj = pipenv.project.Project()

        # Create test space.
        delegator.run('mkdir test_internal_lockfile')

        with open('test_internal_lockfile/Pipfile', 'w') as f:
            f.write('[[source]]\nurl = \'https://pypi.python.org/simple\'\n'
                    'verify_ssl = true\n\n\n[packages]\n'
                    'Requests = { extras = [\'socks\'] }\nFlask_Auth = \'*\'\n\n\n'
                    '[dev-packages]\nclick = \'*\'\nDjango = {git = '
                    '"https://github.com/django/django.git", ref="1.10"}\n')

        proj._pipfile_location = 'test_internal_lockfile/Pipfile'

        lockfile = proj._lockfile

        # Verify default section of lockfile.
        assert len(lockfile['default'].keys()) == 2
        assert 'requests' in lockfile['default']
        assert 'flask-auth' in lockfile['default']

        # Verify develop section of lockfile.
        assert lockfile['develop']['django']['git'] == 'https://github.com/django/django.git'
        assert lockfile['develop']['click'] == '*'

        # Verify _meta exists.
        assert lockfile['_meta']['hash'] == {'sha256': 'ff0b0584610a7091156f32ca7d5adab8f29cb17263c6d63bcab42de2137c4787'}

        delegator.run('rm -fr test_internal_lockfile')
