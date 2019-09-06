from __future__ import absolute_import
import pytest
from .app import app as pypi_app
from . import serve, certs


@pytest.fixture(scope='session')
def pypi(request):
    server = serve.Server(application=pypi_app)
    server.start()
    request.addfinalizer(server.stop)
    return server


@pytest.fixture(scope='session')
def pypi_secure(request):
    server = serve.SecureServer(application=pypi_app)
    server.start()
    request.addfinalizer(server.stop)
    return server


@pytest.fixture(scope='session', params=['http', 'https'])
def pypi_both(request, pypi, pypi_secure):
    if request.param == 'http':
        return pypi
    elif request.param == 'https':
        return pypi_secure


@pytest.fixture(scope='class')
def class_based_pypi(request, pypi):
    request.cls.pypi = pypi


@pytest.fixture(scope='class')
def class_based_pypi_secure(request, pypi_secure):
    request.cls.pypi_secure = pypi_secure


@pytest.fixture(scope='function')
def pypi_ca_bundle(monkeypatch):
    monkeypatch.setenv('REQUESTS_CA_BUNDLE', certs.where())
