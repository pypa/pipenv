import pytest

from pipenv.cli import from_requirements_file
import pipenv.utils



def test_convert_deps_to_pip():

    # requests = '*'
    deps = {'requests': '*'}
    deps = pipenv.utils.convert_deps_to_pip(deps)
    assert deps[0] == 'requests'

    # requests = {}
    deps = {'requests': {}}
    deps = pipenv.utils.convert_deps_to_pip(deps)
    assert deps[0] == 'requests'

    # requests = { extras = ['socks'] }
    deps = {'requests': {'extras': ['socks']}}
    deps = pipenv.utils.convert_deps_to_pip(deps)
    assert deps[0] == 'requests[socks]'

    # Django = '>1.10'
    deps = {'django': '>1.10'}
    deps = pipenv.utils.convert_deps_to_pip(deps)
    assert deps[0] == 'django>1.10'

    # pinax = { git = 'git://github.com/pinax/pinax.git', ref = '1.4', editable = true }
    deps = {'pinax': {'git': 'git://github.com/pinax/pinax.git', 'ref': '1.4', 'editable': True}}
    deps = pipenv.utils.convert_deps_to_pip(deps)
    assert deps[0] == '-e git+git://github.com/pinax/pinax.git@1.4#egg=pinax'

    # pinax = { git = 'git://github.com/pinax/pinax.git', ref = '1.4'}
    deps = {'pinax': {'git': 'git://github.com/pinax/pinax.git', 'ref': '1.4'}}
    deps = pipenv.utils.convert_deps_to_pip(deps)
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


def test_install_from_requirements_file():

    # requests
    r = open('tests/requirements_requests.txt')
    dep = from_requirements_file(r)
    assert dep == ['requests']

    # Django>1.10
    r = open('tests/requirements_django.txt')
    dep = from_requirements_file(r)
    assert dep == ['Django>1.10']

    # requests[sock]
    r = open('tests/requirements_requests_socks.txt')
    dep = from_requirements_file(r)
    assert dep == ['requests[socks]']

    # -e svn+svn://svn.myproject.org/svn/MyProject#egg=MyProject  # comment
    r = open('tests/requirements_egg.txt')
    dep = from_requirements_file(r)
    assert dep == ['-e svn+svn://svn.myproject.org/svn/MyProject#egg=MyProject']
