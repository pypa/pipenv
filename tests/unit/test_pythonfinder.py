import pytest

import pipenv.pythonfinder


@pytest.mark.utils
def test_parse_python_version():
    ver = pipenv.pythonfinder.parse_python_version('Python 3.6.5\n')
    assert ver == {'major': '3', 'minor': '6', 'micro': '5'}


@pytest.mark.utils
def test_parse_python_version_suffix(self):
    ver = pipenv.pythonfinder.parse_python_version('Python 3.6.5rc1\n')
    assert ver == {'major': '3', 'minor': '6', 'micro': '5'}


@pytest.mark.utils
def test_parse_python_version_270():
    ver = pipenv.pythonfinder.parse_python_version('Python 2.7\n')
    assert ver == {'major': '2', 'minor': '7', 'micro': '0'}


@pytest.mark.utils
def test_parse_python_version_270_garbage():
    ver = pipenv.pythonfinder.parse_python_version('Python 2.7+\n')
    assert ver == {'major': '2', 'minor': '7', 'micro': '0'}
