# -*- coding: utf-8 -*-
import os
import pytest
from mock import patch, Mock

import pipenv.utils


# Pipfile format <-> requirements.txt format.
DEP_PIP_PAIRS = [
    ({'requests': '*'}, 'requests'),
    ({'requests': {'extras': ['socks']}}, 'requests[socks]'),
    ({'django': '>1.10'}, 'django>1.10'),
    ({'Django': '>1.10'}, 'Django>1.10'),
    (
        {'requests': {'extras': ['socks'], 'version': '>1.10'}},
        'requests[socks]>1.10',
    ),
    (
        {'requests': {'extras': ['socks'], 'version': '==1.10'}},
        'requests[socks]==1.10',
    ),
    (
        {'pinax': {
            'git': 'git://github.com/pinax/pinax.git',
            'ref': '1.4',
            'editable': True,
        }},
        '-e git+git://github.com/pinax/pinax.git@1.4#egg=pinax',
    ),
    (
        {'pinax': {'git': 'git://github.com/pinax/pinax.git', 'ref': '1.4'}},
        'git+git://github.com/pinax/pinax.git@1.4#egg=pinax',
    ),
    (   # Mercurial.
        {'MyProject': {
            'hg': 'http://hg.myproject.org/MyProject', 'ref': 'da39a3ee5e6b',
        }},
        'hg+http://hg.myproject.org/MyProject@da39a3ee5e6b#egg=MyProject',
    ),
    (   # SVN.
        {'MyProject': {
            'svn': 'svn://svn.myproject.org/svn/MyProject', 'editable': True,
        }},
        '-e svn+svn://svn.myproject.org/svn/MyProject#egg=MyProject',
    ),

]


@pytest.mark.utils
@pytest.mark.parametrize('deps, expected', DEP_PIP_PAIRS)
def test_convert_deps_to_pip(deps, expected):
    assert pipenv.utils.convert_deps_to_pip(deps, r=False) == [expected]


@pytest.mark.utils
@pytest.mark.parametrize('deps, expected', [
    # This one should be collapsed and treated as {'requests': '*'}.
    ({'requests': {}}, 'requests'),

    # Hash value should be passed into the result.
    (
        {'FooProject': {
            'version': '==1.2',
            'hash': 'sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824',
        }},
        'FooProject==1.2 --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824',
    ),
    (
        {'FooProject': {
            'version': '==1.2',
            'extras': ['stuff'],
            'hash': 'sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824',
        }},
        'FooProject[stuff]==1.2 --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
    ),
])
def test_convert_deps_to_pip_one_way(deps, expected):
    assert pipenv.utils.convert_deps_to_pip(deps, r=False) == [expected]


@pytest.mark.skipif(
    isinstance(u'', str),
    reason="don't need to test if unicode is str",
)
@pytest.mark.utils
def test_convert_deps_to_pip_unicode():
    deps = {u'django': u'==1.10'}
    deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
    assert deps[0] == 'django==1.10'


@pytest.mark.utils
@pytest.mark.parametrize('expected, requirement', DEP_PIP_PAIRS)
def test_convert_from_pip(expected, requirement):
    assert pipenv.utils.convert_deps_from_pip(requirement) == expected


@pytest.mark.utils
@pytest.mark.parametrize('expected, requirement', [
    (   # XXX: This should work the other way around as well, but does not atm.
        {'requests': {
            'git': 'https://github.com/requests/requests.git',
            'ref': 'master', 'extras': ['security'],
        }},
        'git+https://github.com/requests/requests.git@master#egg=requests[security]',
    ),
])
def test_convert_from_pip_vcs_with_extra(expected, requirement):
    assert pipenv.utils.convert_deps_from_pip(requirement) == expected


@pytest.mark.utils
def test_convert_from_pip_fail_if_no_egg():
    """Parsing should fail without `#egg=`.
    """
    dep = 'git+https://github.com/kennethreitz/requests.git'
    with pytest.raises(ValueError) as e:
        dep = pipenv.utils.convert_deps_from_pip(dep)
        assert 'pipenv requires an #egg fragment for vcs' in str(e)


@pytest.mark.utils
def test_convert_from_pip_git_uri_normalize():
    """Pip does not parse this correctly, but we can (by converting to ssh://).
    """
    dep = 'git+git@host:user/repo.git#egg=myname'
    dep = pipenv.utils.convert_deps_from_pip(dep)
    assert dep == {
        'myname': {
            'git': 'git@host:user/repo.git',
        }
    }


class TestUtils:
    """Test utility functions in pipenv"""

    @pytest.mark.utils
    @pytest.mark.parametrize(
        'version, specified_ver, expected',
        [
            ('*', '*', True),
            ('2.1.6', '==2.1.4', False),
            ('20160913', '>=20140815', True),
            (
                '1.4',
                {'svn': 'svn://svn.myproj.org/svn/MyProj', 'version': '==1.4'},
                True,
            ),
            ('2.13.0', {'extras': ['socks'], 'version': '==2.12.4'}, False),
        ],
    )
    def test_is_required_version(self, version, specified_ver, expected):
        assert pipenv.utils.is_required_version(version, specified_ver) is expected

    @pytest.mark.utils
    @pytest.mark.parametrize(
        'entry, expected',
        [
            ({'git': 'package.git', 'ref': 'v0.0.1'}, True),
            ({'hg': 'https://package.com/package', 'ref': 'v1.2.3'}, True),
            ('*', False),
            ({'some_value': 5, 'other_value': object()}, False),
            ('package', False),
            ('git+https://github.com/requests/requests.git#egg=requests', True),
            ('git+git@github.com:requests/requests.git#egg=requests', True),
            ('gitdb2', False),
        ],
    )
    @pytest.mark.vcs
    def test_is_vcs(self, entry, expected):
        assert pipenv.utils.is_vcs(entry) is expected

    @pytest.mark.utils
    def test_split_file(self):
        pipfile_dict = {
            'packages': {
                'requests': {'git': 'https://github.com/kennethreitz/requests.git'},
                'Flask': '*',
                'tablib': {'path': '.', 'editable': True},
            },
            'dev-packages': {
                'Django': '==1.10',
                'click': {'svn': 'https://svn.notareal.com/click'},
                'crayons': {'hg': 'https://hg.alsonotreal.com/crayons'},
            },
        }
        split_dict = pipenv.utils.split_file(pipfile_dict)
        assert list(split_dict['packages'].keys()) == ['Flask']
        assert split_dict['packages-vcs'] == {
            'requests': {'git': 'https://github.com/kennethreitz/requests.git'}
        }
        assert split_dict['packages-editable'] == {
            'tablib': {'path': '.', 'editable': True}
        }
        assert list(split_dict['dev-packages'].keys()) == ['Django']
        assert 'click' in split_dict['dev-packages-vcs']
        assert 'crayons' in split_dict['dev-packages-vcs']

    @pytest.mark.utils
    def test_python_version_from_bad_path(self):
        assert pipenv.utils.python_version("/fake/path") is None

    @pytest.mark.utils
    def test_python_version_from_non_python(self):
        assert pipenv.utils.python_version("/dev/null") is None

    @pytest.mark.utils
    @pytest.mark.parametrize(
        'version_output, version',
        [
            ('Python 3.6.2', '3.6.2'),
            ('Python 3.6.2 :: Continuum Analytics, Inc.', '3.6.2'),
            ('Python 3.6.20 :: Continuum Analytics, Inc.', '3.6.20'),
            ('Python 3.5.3 (3f6eaa010fce78cc7973bdc1dfdb95970f08fed2, Jan 13 2018, 18:14:01)\n[PyPy 5.10.1 with GCC 4.2.1 Compatible Apple LLVM 9.0.0 (clang-900.0.39.2)]', '3.5.3')
        ],
    )
    @patch('delegator.run')
    def test_python_version_output_variants(
        self, mocked_delegator, version_output, version
    ):
        run_ret = Mock()
        run_ret.out = version_output
        mocked_delegator.return_value = run_ret
        assert pipenv.utils.python_version('some/path') == version

    @pytest.mark.utils
    @pytest.mark.windows
    @pytest.mark.skipif(os.name != 'nt', reason='Windows test only')
    def test_windows_shellquote(self):
        test_path = 'C:\Program Files\Python36\python.exe'
        expected_path = '"C:\\\\Program Files\\\\Python36\\\\python.exe"'
        assert pipenv.utils.escape_grouped_arguments(test_path) == expected_path

    @pytest.mark.utils
    def test_is_valid_url(self):
        url = "https://github.com/kennethreitz/requests.git"
        not_url = "something_else"
        assert pipenv.utils.is_valid_url(url)
        assert pipenv.utils.is_valid_url(not_url) is False

    @pytest.mark.utils
    @pytest.mark.parametrize(
        'input_path, expected',
        [
            ('artifacts/file.zip', './artifacts/file.zip'),
            ('./artifacts/file.zip', './artifacts/file.zip'),
            ('../otherproject/file.zip', './../otherproject/file.zip'),
        ],
    )
    @pytest.mark.skipif(os.name == 'nt', reason='Nix-based file paths tested')
    def test_nix_converted_relative_path(self, input_path, expected):
        assert pipenv.utils.get_converted_relative_path(input_path) == expected

    @pytest.mark.utils
    @pytest.mark.parametrize(
        'input_path, expected',
        [
            ('artifacts/file.zip', '.\\artifacts\\file.zip'),
            ('./artifacts/file.zip', '.\\artifacts\\file.zip'),
            ('../otherproject/file.zip', '.\\..\\otherproject\\file.zip'),
        ],
    )
    @pytest.mark.skipif(os.name != 'nt', reason='Windows-based file paths tested')
    def test_win_converted_relative_path(self, input_path, expected):
        assert pipenv.utils.get_converted_relative_path(input_path) == expected

    @pytest.mark.utils
    def test_download_file(self):
        url = "https://github.com/kennethreitz/pipenv/blob/master/README.rst"
        output = "test_download.rst"
        pipenv.utils.download_file(url, output)
        assert os.path.exists(output)
        os.remove(output)

    @pytest.mark.utils
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

    @pytest.mark.utils
    @pytest.mark.parametrize(
        'input_path, expected',
        [
            (
                'c:\\Program Files\\Python36\\python.exe',
                'C:\\Program Files\\Python36\\python.exe',
            ),
            (
                'C:\\Program Files\\Python36\\python.exe',
                'C:\\Program Files\\Python36\\python.exe',
            ),
            ('\\\\host\\share\\file.zip', '\\\\host\\share\\file.zip'),
            ('artifacts\\file.zip', 'artifacts\\file.zip'),
            ('.\\artifacts\\file.zip', '.\\artifacts\\file.zip'),
            ('..\\otherproject\\file.zip', '..\\otherproject\\file.zip'),
        ],
    )
    @pytest.mark.skipif(os.name != 'nt', reason='Windows file paths tested')
    def test_win_normalize_drive(self, input_path, expected):
        assert pipenv.utils.normalize_drive(input_path) == expected

    @pytest.mark.utils
    @pytest.mark.parametrize(
        'input_path, expected',
        [
            ('/usr/local/bin/python', '/usr/local/bin/python'),
            ('artifacts/file.zip', 'artifacts/file.zip'),
            ('./artifacts/file.zip', './artifacts/file.zip'),
            ('../otherproject/file.zip', '../otherproject/file.zip'),
        ],
    )
    @pytest.mark.skipif(os.name == 'nt', reason='*nix file paths tested')
    def test_nix_normalize_drive(self, input_path, expected):
        assert pipenv.utils.normalize_drive(input_path) == expected

    @pytest.mark.utils
    @pytest.mark.requirements
    def test_get_requirements(self):
        # Test eggs in URLs
        url_with_egg = pipenv.utils.get_requirement(
            'https://github.com/IndustriaTech/django-user-clipboard/archive/0.6.1.zip#egg=django-user-clipboard'
        )
        assert url_with_egg.uri == 'https://github.com/IndustriaTech/django-user-clipboard/archive/0.6.1.zip'
        assert url_with_egg.name == 'django-user-clipboard'
        # Test URLs without eggs pointing at installable zipfiles
        url = pipenv.utils.get_requirement(
            'https://github.com/kennethreitz/tablib/archive/0.12.1.zip'
        )
        assert url.uri == 'https://github.com/kennethreitz/tablib/archive/0.12.1.zip'
        # Test VCS urls with refs and eggnames
        vcs_url = pipenv.utils.get_requirement(
            'git+https://github.com/kennethreitz/tablib.git@master#egg=tablib'
        )
        assert vcs_url.vcs == 'git' and vcs_url.name == 'tablib' and vcs_url.revision == 'master'
        assert vcs_url.uri == 'git+https://github.com/kennethreitz/tablib.git'
        # Test normal package requirement
        normal = pipenv.utils.get_requirement('tablib')
        assert normal.name == 'tablib'
        # Pinned package  requirement
        spec = pipenv.utils.get_requirement('tablib==0.12.1')
        assert spec.name == 'tablib' and spec.specs == [('==', '0.12.1')]
        # Test complex package with both extras and markers
        extras_markers = pipenv.utils.get_requirement(
            "requests[security]; os_name=='posix'"
        )
        assert extras_markers.extras == ['security']
        assert extras_markers.name == 'requests'
        assert extras_markers.markers == "os_name=='posix'"
        # Test VCS uris get generated correctly, retain git+git@ if supplied that way, and are named according to egg fragment
        git_reformat = pipenv.utils.get_requirement(
            '-e git+git@github.com:pypa/pipenv.git#egg=pipenv'
        )
        assert git_reformat.uri == 'git+git@github.com:pypa/pipenv.git'
        assert git_reformat.name == 'pipenv'
        assert git_reformat.editable
        # Previously VCS uris were being treated as local files, so make sure these are not handled that way
        assert not git_reformat.local_file
        # Test regression where VCS uris were being handled as paths rather than VCS entries
        assert git_reformat.vcs == 'git'

    @pytest.mark.utils
    @pytest.mark.parametrize(
        'sources, expected_args',
        [
            ([{'url': 'https://test.example.com/simple', 'verify_ssl': True}],
             ['-i', 'https://test.example.com/simple']),
            ([{'url': 'https://test.example.com/simple', 'verify_ssl': False}],
             ['-i', 'https://test.example.com/simple',  '--trusted-host', 'test.example.com']),

             ([{'url': "https://pypi.python.org/simple"},
              {'url': "https://custom.example.com/simple"}],
             ['-i', 'https://pypi.python.org/simple',
              '--extra-index-url', 'https://custom.example.com/simple']),

             ([{'url': "https://pypi.python.org/simple"},
              {'url': "https://custom.example.com/simple",  'verify_ssl': False}],
             ['-i', 'https://pypi.python.org/simple',
              '--extra-index-url', 'https://custom.example.com/simple',
              '--trusted-host', 'custom.example.com']),

           ([{'url': "https://pypi.python.org/simple"},
             {'url': "https://user:password@custom.example.com/simple",  'verify_ssl': False}],
            ['-i', 'https://pypi.python.org/simple',
             '--extra-index-url', 'https://user:password@custom.example.com/simple',
             '--trusted-host', 'custom.example.com']),

            ([{'url': "https://pypi.python.org/simple"},
              {'url': "https://user:password@custom.example.com/simple",}],
             ['-i', 'https://pypi.python.org/simple',
              '--extra-index-url', 'https://user:password@custom.example.com/simple',]),
        ],
    )
    def test_prepare_pip_source_args(self, sources, expected_args):
        assert pipenv.utils.prepare_pip_source_args(sources, pip_args=None) == expected_args

    @pytest.mark.utils
    def test_parse_python_version(self):
        ver = pipenv.utils.parse_python_version('Python 3.6.5\n')
        assert ver == {'major': '3', 'minor': '6', 'micro': '5'}

    @pytest.mark.utils
    def test_parse_python_version_suffix(self):
        ver = pipenv.utils.parse_python_version('Python 3.6.5rc1\n')
        assert ver == {'major': '3', 'minor': '6', 'micro': '5'}

    @pytest.mark.utils
    def test_parse_python_version_270(self):
        ver = pipenv.utils.parse_python_version('Python 2.7\n')
        assert ver == {'major': '2', 'minor': '7', 'micro': '0'}

    @pytest.mark.utils
    def test_parse_python_version_270_garbage(self):
        ver = pipenv.utils.parse_python_version('Python 2.7+\n')
        assert ver == {'major': '2', 'minor': '7', 'micro': '0'}
