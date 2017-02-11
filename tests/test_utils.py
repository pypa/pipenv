# -*- coding: utf-8 -*-

import pytest

import pipenv.utils

class TestUtils:

    """Test utility functions in pipenv"""

    def test_format_toml(self):
        """Verify that two return characters are used between each section"""
        data = ('[[source]]\nurl = "https://pypi.org/simple"\n[dev-packages]\n'
                'pytest="*"\nsphinx = "*"\n[packages]\nclick ="*"\ncrayons = "*"')

        expected = ('[[source]]\nurl = "https://pypi.org/simple"\n\n'
                    '[dev-packages]\npytest="*"\nsphinx = "*"\n\n'
                    '[packages]\nclick ="*"\ncrayons = "*"')

        assert pipenv.utils.format_toml(data) == expected

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

        dep = '-e svn+svn://svn.myproject.org/svn/MyProject#egg=MyProject'
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert dep == {u'MyProject': {u'svn': u'svn://svn.myproject.org/svn/MyProject', 'editable': True}}

        # mercurial repository with commit reference
        dep = 'hg+http://hg.myproject.org/MyProject@da39a3ee5e6b#egg=MyProject'
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert dep == {'MyProject': {'hg': 'http://hg.myproject.org/MyProject', 'ref': 'da39a3ee5e6b'}}


    @pytest.mark.parametrize('version, specified_ver, expected', [
        ('*', '*', True),
        ('2.1.6', '==2.1.4', False),
        ('20160913', '>=20140815', True),
        ('1.4', {'svn': 'svn://svn.myproj.org/svn/MyProj', 'version': '==1.4'}, True),
        ('2.13.0', {'extras': ['socks'], 'version': '==2.12.4'}, False)
    ])
    def test_is_required_version(self, version, specified_ver, expected):
        assert pipenv.utils.is_required_version(version, specified_ver) is expected
