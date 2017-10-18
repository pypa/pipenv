# -*- coding: utf-8 -*-

import os
import pytest
from mock import patch, Mock

import pipenv.utils


class TestUtils:

    """Test utility functions in pipenv"""

    def test_convert_deps_to_pip(self):

        # requests = '*'
        deps = {'requests': '*'}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == 'requests'

        # requests = {}
        deps = {'requests': {}}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == 'requests'

        # requests = { extras = ['socks'] }
        deps = {'requests': {'extras': ['socks']}}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == 'requests[socks]'

        # Django = '>1.10'
        deps = {'django': '>1.10'}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == 'django>1.10'

        # Pinned version with Extras
        deps = {'requests': {'extras': ['socks'], 'version': '>1.10'}}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == 'requests[socks]>1.10'

        # pinax = { git = 'git://github.com/pinax/pinax.git', ref = '1.4', editable = true }
        deps = {'pinax': {'git': 'git://github.com/pinax/pinax.git', 'ref': '1.4', 'editable': True}}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == '-e git+git://github.com/pinax/pinax.git@1.4#egg=pinax'

        # pinax = { git = 'git://github.com/pinax/pinax.git', ref = '1.4'}
        deps = {'pinax': {'git': 'git://github.com/pinax/pinax.git', 'ref': '1.4'}}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == 'git+git://github.com/pinax/pinax.git@1.4#egg=pinax'

        # test hashes
        deps = {'FooProject': {'version': '==1.2', 'hash': 'sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'}}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == 'FooProject==1.2 --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'

        # test everything
        deps = {'FooProject': {'version': '==1.2', 'extras': ['stuff'], 'hash': 'sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'}}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == 'FooProject[stuff]==1.2 --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'

        # test unicode values
        deps = {u'django': u'==1.10'}
        deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
        assert deps[0] == 'django==1.10'

    def test_convert_from_pip(self):

        # requests
        dep = 'requests'
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert dep == {'requests': '*'}

        # Django>1.10
        dep = 'Django>1.10'
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert dep == {'Django': '>1.10'}

        # requests[socks]
        dep = 'requests[socks]'
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert dep == {'requests': {'extras': ['socks']}}

        # requests[socks] w/ version
        dep = 'requests[socks]==1.10'
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert dep == {'requests': {'extras': ['socks'], 'version': '==1.10'}}

        dep = '-e svn+svn://svn.myproject.org/svn/MyProject#egg=MyProject'
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert dep == {u'MyProject': {u'svn': u'svn://svn.myproject.org/svn/MyProject', 'editable': True}}

        # mercurial repository with commit reference
        dep = 'hg+http://hg.myproject.org/MyProject@da39a3ee5e6b#egg=MyProject'
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert dep == {'MyProject': {'hg': 'http://hg.myproject.org/MyProject', 'ref': 'da39a3ee5e6b'}}

        # vcs dependency with extras_require
        dep = 'git+https://github.com/requests/requests.git@master#egg=requests[security]'
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert dep == {'requests': {'git': 'https://github.com/requests/requests.git',
                                    'ref': 'master',
                                    'extras': ['security']}}

        # vcs dependency without #egg
        dep = 'git+https://github.com/kennethreitz/requests.git'
        with pytest.raises(ValueError) as e:
            dep = pipenv.utils.convert_deps_from_pip(dep)
            assert 'pipenv requires an #egg fragment for vcs' in str(e)

    @pytest.mark.parametrize('version, specified_ver, expected', [
        ('*', '*', True),
        ('2.1.6', '==2.1.4', False),
        ('20160913', '>=20140815', True),
        ('1.4', {'svn': 'svn://svn.myproj.org/svn/MyProj', 'version': '==1.4'}, True),
        ('2.13.0', {'extras': ['socks'], 'version': '==2.12.4'}, False)
    ])
    def test_is_required_version(self, version, specified_ver, expected):
        assert pipenv.utils.is_required_version(version, specified_ver) is expected

    @pytest.mark.parametrize('entry, expected', [
        ({'git': 'package.git', 'ref': 'v0.0.1'}, True),
        ({'hg': 'https://package.com/package', 'ref': 'v1.2.3'}, True),
        ('*', False),
        ({'some_value': 5, 'other_value': object()}, False),
        ('package', False),
        ('git+https://github.com/requests/requests.git#egg=requests', True),
        ('git+git@github.com:requests/requests.git#egg=requests', True)
    ])
    def test_is_vcs(self, entry, expected):
        assert pipenv.utils.is_vcs(entry) is expected

    def test_split_vcs(self):
        pipfile_dict = {
            'packages': {
                'requests': {'git': 'https://github.com/kennethreitz/requests.git'},
                'Flask': '*'
            },
            'dev-packages': {
                'Django': '==1.10',
                'click': {'svn': 'https://svn.notareal.com/click'},
                'crayons': {'hg': 'https://hg.alsonotreal.com/crayons'}
            }
        }
        split_dict = pipenv.utils.split_vcs(pipfile_dict)

        assert list(split_dict['packages'].keys()) == ['Flask']
        assert split_dict['packages-vcs'] == {'requests': {'git': 'https://github.com/kennethreitz/requests.git'}}
        assert list(split_dict['dev-packages'].keys()) == ['Django']
        assert 'click' in split_dict['dev-packages-vcs']
        assert 'crayons' in split_dict['dev-packages-vcs']

    def test_python_version_from_bad_path(self):
        assert pipenv.utils.python_version("/fake/path") is None

    def test_python_version_from_non_python(self):
        assert pipenv.utils.python_version("/dev/null") is None

    @pytest.mark.parametrize('version_output, version', [
        ('Python 3.6.2', '3.6.2'),
        ('Python 3.6.2 :: Continuum Analytics, Inc.', '3.6.2'),
        ('Python 3.6.20 :: Continuum Analytics, Inc.', '3.6.20'),
    ])
    @patch('delegator.run')
    def test_python_version_output_variants(self, mocked_delegator, version_output, version):
        run_ret = Mock()
        run_ret.out = version_output
        mocked_delegator.return_value = run_ret
        assert pipenv.utils.python_version('some/path') == version

    @pytest.mark.windows
    @pytest.mark.skipif(os.name != 'nt', reason='Windows test only')
    def test_windows_shellquote(self):
        test_path = 'C:\Program Files\Python36\python.exe'
        expected_path = '"C:\\\\Program Files\\\\Python36\\\\python.exe"'
        assert pipenv.utils.shellquote(test_path) == expected_path

    def test_is_valid_url(self):
        url = "https://github.com/kennethreitz/requests.git"
        not_url = "something_else"
        assert pipenv.utils.is_valid_url(url)
        assert pipenv.utils.is_valid_url(not_url) is False

    def test_download_file(self):
        url = "https://github.com/kennethreitz/pipenv/blob/master/README.rst"
        output = "test_download.rst"
        pipenv.utils.download_file(url, output)
        assert os.path.exists(output)
        os.remove(output)

    def test_new_line_end_of_toml_file(this):
        # toml file that needs clean up
        toml = """
[dev-packages]

"flake8" = ">=3.3.0,<4"
pytest = "*"
mock = "*"
sphinx = "<=1.5.5"
"-e ." = "*"
twine = "*"
"sphinx-click" = "*"
"pytest-xdist" = "*"
        """
        new_toml = pipenv.utils.cleanup_toml(toml)
        # testing if the end of the generated file contains a newline
        assert new_toml[-1] == '\n'
