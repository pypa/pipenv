import os

import pytest
import pipenv.project
import pipenv.core
from pipenv.vendor import delegator


class TestProject():

    @pytest.mark.project
    def test_proper_names(self):
        proj = pipenv.project.Project()
        assert proj.virtualenv_location in proj.proper_names_location
        assert isinstance(proj.proper_names, list)

    @pytest.mark.project
    def test_download_location(self):
        proj = pipenv.project.Project()
        assert proj.virtualenv_location in proj.download_location
        assert proj.download_location.endswith('downloads')

    @pytest.mark.project
    def test_create_pipfile(self):
        proj = pipenv.project.Project(which=pipenv.core.which)

        # Create test space.
        delegator.run('mkdir test_pipfile')
        with open('test_pipfile/pip.conf', 'w') as f:
            f.write('[install]\nextra-index-url = \n'
                    '    https://pypi.host.com/simple\n'
                    '    https://remote.packagehost.net/simple')
        os.chdir('test_pipfile')
        os.environ['PIP_CONFIG_FILE'] = 'pip.conf'
        proj.create_pipfile()
        proj._pipfile_location = 'Pipfile'
        pfile = proj.parsed_pipfile
        os.chdir('..')

        # Cleanup test space.
        delegator.run('rm -fr test_pipfile')

        # Confirm source added correctly.
        default_source = pfile['source'][0]
        assert default_source['url'] == 'https://pypi.python.org/simple'
        assert default_source['name'] == 'pypi'
        assert default_source['verify_ssl'] is True

        config_source_1 = pfile['source'][1]
        assert config_source_1['url'] == 'https://pypi.host.com/simple'
        assert config_source_1['name'] == 'pip_index_0'
        assert config_source_1['verify_ssl'] is True

        config_source_2 = pfile['source'][2]
        assert config_source_2['url'] == 'https://remote.packagehost.net/simple'
        assert config_source_2['name'] == 'pip_index_1'
        assert config_source_2['verify_ssl'] is True

    @pytest.mark.project
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
        assert 'socks' in pfile['packages']['requests']['extras']

    @pytest.mark.project
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
        assert 'flask' in p['packages']
        assert p['packages']['flask'] == '*'

        # Confirm Django added to dev-packages.
        assert 'django' in p['dev-packages']
        assert p['dev-packages']['django'] == '==1.10.1'

        # Confirm casing is normalized.
        assert 'click-completion' in p['packages']
        assert p['packages']['click-completion'] == '*'

    @pytest.mark.project
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
        assert 'flask' in p['packages']
        assert len(p['packages']) == 1

        # assert 'dev-packages' not in p

    @pytest.mark.project
    def test_internal_pipfile(self):
        proj = pipenv.project.Project()

        # Create test space.
        delegator.run('mkdir test_internal_pipfile')
        with open('test_internal_pipfile/Pipfile', 'w') as f:
            f.write('[[source]]\nurl = \'https://pypi.python.org/simple\'\n'
                    'verify_ssl = true\n\n\n[packages]\n'
                    'requests = { extras = [\'socks\'] }\nFlask_Auth = \'*\'\n\n\n'
                    '[dev-packages]\nclick = \'*\'\nDjango = {git = '
                    '"https://github.com/django/django.git", ref="1.10"}\n')

        proj._pipfile_location = 'test_internal_pipfile/Pipfile'

        p = proj._pipfile

        # Test package names are normalized as expected.
        assert list(p['packages'].keys()) == ['requests', 'flask-auth']
        assert list(p['dev-packages'].keys()) == ['click', 'django']

        delegator.run('rm -fr test_internal_pipfile')

    @pytest.mark.project
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
