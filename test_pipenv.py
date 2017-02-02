import os

import pytest

from pipenv.cli import parse_download_fname
import pipenv.utils
import delegator


def test_parse_download_fname():

    fname = 'functools32-3.2.3-2.zip'
    version = parse_download_fname(fname)
    assert version == '3.2.3-2'

    fname = 'functools32-3.2.3-blah.zip'
    version = parse_download_fname(fname)
    assert version == '3.2.3-blah'

    fname = 'functools32-3.2.3.zip'
    version = parse_download_fname(fname)
    assert version == '3.2.3'

    fname = 'colorama-0.3.7-py2.py3-none-any.whl'
    version = parse_download_fname(fname)
    assert version == '0.3.7'

    fname = 'colorama-0.3.7-2-py2.py3-none-any.whl'
    version = parse_download_fname(fname)
    assert version == '0.3.7-2'

    fname = 'click-completion-0.2.1.tar.gz'
    version = parse_download_fname(fname)
    assert version == '0.2.1'

    fname = 'Twisted-16.5.0.tar.bz2'
    version = parse_download_fname(fname)
    assert version == '16.5.0'

    fname = 'Twisted-16.1.1-cp27-none-win_amd64.whl'
    version = parse_download_fname(fname)
    assert version == '16.1.1'


def test_convert_deps_to_pip():

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


def test_convert_from_pip():

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

def test_cli_usage():
    delegator.run('mkdir test_project')
    os.chdir('test_project')

    os.environ['PIPENV_VENV_IN_PROJECT'] = '1'

    assert delegator.run('touch Pipfile').return_code == 0

    assert delegator.run('pipenv --python python').return_code == 0
    assert delegator.run('pipenv install requests').return_code == 0
    assert delegator.run('pipenv install pytest --dev').return_code == 0
    assert delegator.run('pipenv lock').return_code == 0

    assert 'pytest' in delegator.run('cat Pipfile').out
    assert 'pytest' in delegator.run('cat Pipfile.lock').out

    os.chdir('..')
    delegator.run('rm -fr test_project')

