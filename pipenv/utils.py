# -*- coding: utf-8 -*-
import os
import hashlib
import tempfile
import sys
import shutil
import logging

import click
import crayons
import delegator
import pip
import parse
import requirements
import fuzzywuzzy.process
import requests
import six
from time import time

logging.basicConfig(level=logging.ERROR)

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path

from distutils.spawn import find_executable
from contextlib import contextmanager
from piptools.resolver import Resolver
from piptools.repositories.pypi import PyPIRepository
from piptools.scripts.compile import get_pip_command
from piptools import logging
from piptools.exceptions import NoCandidateFound
from pip.exceptions import DistributionNotFound
from requests.exceptions import HTTPError, ConnectionError

from .pep508checker import lookup
from .environments import SESSION_IS_INTERACTIVE, PIPENV_MAX_ROUNDS, PIPENV_CACHE_DIR

specifiers = [k for k in lookup.keys()]

# List of version control systems we support.
VCS_LIST = ('git', 'svn', 'hg', 'bzr')
SCHEME_LIST = ('http://', 'https://', 'ftp://', 'file://')

requests = requests.Session()

packages = [
    'simplejson', 'six', 'botocore', 'python-dateutil', 'pyasn1', 'setuptools',
    'requests', 'pyyaml', 'docutils', 's3transfer', 'futures', 'pip',
    'jmespath', 'awscli', 'rsa', 'colorama', 'idna', 'certifi', 'urllib3',
    'chardet', 'cffi', 'awscli-cwlogs', 'wheel', 'pycparser', 'enum34', 'pbr',
    'cryptography', 'virtualenv', 'pytz', 'setuptools-scm', 'jinja2',
    'ipaddress', 'markupsafe', 'boto3', 'asn1crypto', 'boto', 'paramiko',
    'ptyprocess', 'pexpect', 'pytest-runner', 'psutil', 'flask', 'werkzeug',
    'bcrypt', 'pynacl', 'sqlalchemy', 'click', 'numpy', 'pyparsing', 'lxml',
    'pyopenssl', 'future', 'decorator', 'vcversioner', 'mock', 'argparse',
    'pyasn1-modules', 'jsonschema', 'funcsigs', 'nose', 'tornado', 'httplib2',
    'protobuf', 'pandas', 'coverage', 'psycopg2', 'pygments', 'oauth2client',
    'singledispatch', 'itsdangerous', 'pytest', 'functools32', 'docopt',
    'mccabe', 'babel', 'pillow', 'grpcio', 'backports-abc', 'public',
    'query-string', 'redis', 'zope-interface',
    'pyflakes', 'pycrypto', 'wrapt', 'django', 'selenium', 'flake8',
    'html5lib', 'elasticsearch', 'markdown', 'pycodestyle',
    'backports-ssl-match-hostname', 'scipy', 'websocket-client', 'lockfile',
    'ipython', 'beautifulsoup4', 'gevent', 'uritemplate', 'pymysql',
    'configparser', 'kombu', 'arrow', 'scikit-learn', 'greenlet', 'amqp',
    'wcwidth', 'googleapis-common-protos', 'bleach',
    'google-api-python-client', 'gunicorn', 'gitpython', 'typing',
    'prompt-toolkit', 'google-cloud-core', 'google-gax', 'requests-oauthlib',
    'stevedore', 'ordereddict', 'traitlets', 'packaging', 'pymongo',
    'ipython-genutils', 'appdirs', 'celery', 'google-auth', 'cython',
    'billiard', 'xmltodict', 'pickleshare', 'unittest2', 'simplegeneric',
    'msgpack-python', 'snowballstemmer', 'sphinx', 'matplotlib', 'pep8',
    'pylint', 'netaddr', 'flask-restful', 'oauthlib', 'linecache2', 'ply',
    'traceback2', 'alabaster', 'monotonic', 'olefile', 'isort', 'astroid',
    'pyjwt', 'lazy-object-proxy', 'imagesize', 'smmap2', 'gitdb2',
    'incremental', 'contextlib2', 'ndg-httpsclient', 'ujson', 'unidecode',
    'raven', 'blessings', 'docker-pycreds', 'ansible', 'vine', 'mako',
    'netifaces', 'retrying', 'attrs', 'requests-toolbelt', 'supervisor',
    'python-daemon', 'sqlparse', 'prettytable', 'iso8601', 'pytest-cov',
    'cycler', 'cachetools', 'pyzmq', 'tabulate', 'google-cloud-logging',
    'tqdm', 'mozsystemmonitor', 'gapic-google-cloud-logging-v2',
    'blobuploader', 'tzlocal', 'tox', 'pluggy', 'xlrd', 'configobj',
    'djangorestframework', 'webencodings', 'unicodecsv', 'grpcio-tools',
    'pystache', 'meld3', 'mysql-python', 'uwsgi', 'oslo-utils',
    'grpc-google-cloud-logging-v2', 'oslo-i18n', 'nbformat', 'statsd',
    'debtcollector', 'docker-py', 'oslo-config', 'sphinxcontrib-websupport',
    'pathlib2', 'parsedatetime', 'ecdsa', 'oslo-serialization',
    'configargparse', 'backports-weakref', 'backports-functools-lru-cache',
    'alembic', 'jupyter-core', 'cached-property', 'scandir', 'rfc3986',
    'frida', 'subprocess32', 'keystoneauth1', 'thrift', 'jedi', 'ccxt',
    'fabric', 'mistune', 'dnspython', 'service-identity', 'datadog',
    'python-magic', 'altgraph', 'twisted', 'openpyxl', 'webob', 'macholib',
    'docker', 'regex', 'python-keystoneclient',
    'backports-shutil-get-terminal-size', 'zope-component', 'python-editor',
    'zope-event', 'isodate', 'tensorflow', 'pika', 'anyjson', 'tldextract',
    'tensorflow-tensorboard', 'pyrfc3339', 'requests-file', 'networkx',
    'easyprocess', 'dockerpty', 'texttable', 'positional', 'python-augeas',
    'acme', 'jdcal', 'mmh3', 'dill', 'certbot', 'termcolor', 'nbconvert',
    'certbot-apache', 'ipykernel', 'python-mimeparse', 'ruamel-yaml',
    'et-xmlfile', 'letsencrypt', 'opencv-python', 'cmd2', 'w3lib', 'cliff',
    'jupyter-client', 'ipywidgets', 'passlib', 'gcloud', 'cssselect',
    'notebook', 'python-swiftclient', 'widgetsnbextension', 'entrypoints',
    'flask-sqlalchemy', 'kazoo', 'defusedxml', 'pandocfilters', 'python-gflags',
    'testpath', 'python-memcached', 'keras', 'jsonpatch', 'python-novaclient',
    'sympy', 'qtconsole', 'freezegun', 'whichcraft', 'docker-compose',
    'binaryornot', 'blinker', 'cookiecutter', 'azure-common', 'jinja2-time',
    'poyo', 'certbot-nginx', 'nltk', 'google-cloud-storage', 'sklearn',
    'pyhocon', 'django-extensions', 'ua-parser', 'os-client-config',
    'jupyter-console', 'inflection', 'newrelic', 'tempita', 'azure-nspkg',
    'codecov', 'argh', 'sqlalchemy-migrate', 'requestsexceptions', 'geopy',
    'azure-storage', 'pytest-xdist', 'jupyter', 'grpc-google-pubsub-v1',
    'faker', 'execnet', 'constantly', 'grpc-google-logging-v2', 'automat',
    'argcomplete', 'apipkg', 'wtforms', 'sphinx-rtd-theme', 'aiohttp',
    'hyperlink', 'py4j', 'multidict', 'django-filter', 'coala', 'crcmod',
    'jsonpointer', 'pytesseract', 'gax-google-pubsub-v1',
    'gax-google-logging-v2', 'distribute', 'patsy', 'flask-wtf', 'waitress',
    'coveralls', 'pyaml', 'bz2file', 'hjson', 'fake-useragent', 'terminado',
    'pyperclip', 'repoze-lru', 'mysqlclient', 'smart-open', 'theano', 'pycurl',
    'sqlobject', 'python-glanceclient', 'paste', 'python-cinderclient',
    'pathspec', 'watchdog', 'testtools', 'plotly', 'python-openstackclient',
    'scrapy-crawlera', 'pathtools', 'azure', 'flask-login', 'aniso8601',
    'google-resumable-media', 'python-jenkins', 'slacker', 'xlsxwriter',
    'async-timeout', 'pyserial', 'openstacksdk', 'python-jose', 'tenacity',
    'python-slugify', 'keyring', 'pkginfo', 'pastedeploy', 'seaborn',
    'eventlet', 'google-cloud-bigquery', 'h5py', 'aws-requests-auth',
    'maxminddb', 's3cmd', 'django-debug-toolbar', 'flask-script',
    'multi-key-dict', 'fuzzywuzzy', 'fasteners', 'youtube-dl',
    'pycryptodome', 'smmap', 'gitdb', 'setuptools-git', 'pager',
    'python-subunit', 'warlock', 'extras', 'capstone', 'httpretty',
    'factory_boy', 'webtest', 'django-cors-headers', 'codeintel', 'suds',
    'pyodbc', 'geoip2', 'filechunkio', 'fixtures', 'pysocks', 'statsmodels',
    'google-auth-httplib2', 'kafka-python', 'applicationinsights', 'yarl',
    'cassandra-driver', 'azure-mgmt-compute', 'pathlib', 'python-jwt', 'sh',
    'flask-cors', 'shapely', 'twine', 'taskcluster', 'enum-compat',
    'python-twitter', 'cookiejar', 'cookies', 'semantic-version', 'slugid',
    'suds-jurko', 'joblib', 'azure-mgmt-network', 'azure-mgmt-resource',
    'hiredis', 'pyhawk-with-a-single-extra-commit', 'jws', 'moto', 'bokeh',
    'ipaddr', 'invoke', 'azure-mgmt-storage', 'pyxdg', 'azure-mgmt-nspkg',
    'pytest-mock', 'google-cloud-pubsub', 'send2trash', 'yarg', 'subliminal',
    'pydevd', 'xlwt', 'user-agents', 'python-fanart', 'bs4', 'rtorrent-python',
    'django-storages', 'tmdbsimple', 'autopep8', 'pysftp', 'ipdb',
    'setproctitle', 'osc-lib', 'importlib', 'validate-email', 'django-appconf',
    'bottle', 'hgtools', 'stripe', 'azure-servicebus', 'marshmallow',
    'voluptuous', 'ptvsd', 'jsonpickle', 'reportlab', 'python-geohash',
    'dicttoxml', 'ddt', 'secretstorage', 'pytest-django', 'flexget',
    'httpagentparser', 'beautifulsoup', 'azure-mgmt', 'haversine',
    'flower', 'sortedcontainers', 'requests-mock',
    'azure-servicemanagement-legacy', 'flask-migrate', 'pyinotify',
    'carbon', 'zc-buildout', 'unittest-xml-reporting', 'parse', 'hacking',
    'mxnet', 'qds-sdk', 'twilio', 'gspread', 'oslo-log', 'pytest-timeout',
    'python-heatclient', 'oslo-context', 'numexpr', 'toolz', 'adal',
    'troposphere', 'humanfriendly', 'path-py', 'dogpile-cache', 'plumbum',
    'gapic-google-cloud-pubsub-v1', 'graphite-web', 'grpc-google-iam-v1',
    'deprecation', 'mpmath', 'oslo-concurrency', 'feedparser', 'python-ldap',
    'proto-google-cloud-pubsub-v1', 'pyzabbix', 'humanize', 'colorlog',
    'msrestazure', 'msrest', 'python-ironicclient', 'pycountry',
    'email-validator', 'hypothesis', 'coala-bears', 'phonenumbers',
    'dj-database-url', 'elasticsearch-dsl', 'responses',
    'python-neutronclient', 'sasl', 'django-nose', 'munch', 'pydns',
    'proto-google-cloud-datastore-v1', 'apscheduler', 'django-redis',
    'pytest-forked', 'python-levenshtein', 'dateparser',
    'google-cloud-datastore', 'pytimeparse', 'pytest-html',
    'virtualenv-clone', 'zope-deprecation', 'django-rest-swagger',
    'whitenoise', 'gensim', 'python-consul', 'pypdf2', 'pydispatcher',
    'scp', 'requires', 'cement', 'cx-oracle', 'graphviz', 'slackclient',
    'hponeview', 'croniter', 'cssutils', 'appier', 'jsonpath-rw',
    'requests-futures', 'mrjob', 'cachet', 'influxdb', 'virtualenvwrapper',
    'appnope', 'pymssql', 'testfixtures', 'glob2', 'django-model-utils',
    'awsebcli', 'tweepy', 'gapic-google-cloud-datastore-v1', 'coreapi',
    'bkcharts', 'requests-ntlm', 'sqlalchemy-utils', 'more-itertools',
    'testrepository', 'blessed', 'jsonfield', 'logilab-common',
    'flake8-import-order', 'parse-type', 'clint', 'queuelib', 'robotframework',
    'python-gnupg', 'tensorflow-gpu', 'jira', 'gcdt-bundler',
    'azure-mgmt-redis', 'avro', 'args', 'pythonwhois', 'pyhamcrest',
    'scrapy', 'ruamel-ordereddict', 'retry', 'azure-mgmt-batch',
    'azure-batch', 'junit-xml', 'django-compressor', 'pyvirtualdisplay',
    'python-openid', 'itypes', 'flask-cache', 'azure-mgmt-keyvault',
    'pip-tools', 'apache-libcloud', 'inflect', 'django-celery', 'routes',
    'google-apputils', 'bitarray', 'websockets', 'cherrypy', 'pyhive',
    'os-testr', 'whoosh', 'django-braces', 'findspark', 'parsel',
    'zope-exceptions', 'coreschema', 'ntlm-auth', 'fake-factory',
    'enum', 'googleads', 'iptools', 'google-cloud-translate',
    'google-cloud', 'pywinrm', 'google-cloud-vision', 'google-cloud-language',
    'brotlipy', 'google-cloud-bigtable', 'google-cloud-error-reporting',
    'oslo-messaging', 'zope-testrunner', 'google-cloud-monitoring', 'awacs',
    'pydocstyle', 'lmdb', 'django-crispy-forms', 'jellyfish',
    'google-cloud-speech', 'google-cloud-runtimeconfig', 'testscenarios',
    'first', 'py-zabbix', 'bcdoc', 'azure-mgmt-web', 'google-cloud-dns',
    'google-cloud-resource-manager', 'google-compute-engine', 'oslo-db',
    'autobahn', 'ldap3', 'azure-mgmt-monitor', 'proto-google-cloud-logging-v2',
    'azure-mgmt-trafficmanager', 'pypiwin32', 'azure-mgmt-cdn',
    'oslo-middleware', 'azure-mgmt-authorization', 'google-cloud-spanner',
    'python-json-logger', 'datetime', 'eggtestinfo', 'thriftpy', 'nosexcover',
    'falcon', 'csvkit', 'ggplot', 'pyramid', 'pg8000', 'munkres', 'futurist',
    'ciso8601', 'azure-graphrbac', 'python-dotenv', 'py2-ipaddress', 'peewee',
    'brewer2mpl', 'dulwich', 'zeep', 'azure-mgmt-cognitiveservices',
    'translationstring', 'sendgrid', 'xgboost', 'aws', 'prometheus-client',
    'runcython', 'azure-mgmt-sql', 'kubernetes', 'oslo-service', 'annoy',
    'oauth2', 'dbfread', 'mox3', 'wincertstore', 'initools', 'scikit-image',
    'backport-collections', 'commonmark', 'pyproj', 'behave', 'qrcode',
    'azure-mgmt-dns', 'azure-datalake-store',
    'gapic-google-cloud-error-reporting-v1beta1', 'requests-aws4auth',
    'flask-admin', 'pygame', 'cov-core', 'gapic-google-cloud-spanner-v1',
    'agate', 'gapic-google-cloud-spanner-admin-database-v1',
    'openstackdocstheme', 'azure-mgmt-containerregistry',
    'djangorestframework-jwt',
    'proto-google-cloud-error-reporting-v1beta1',
    'proto-google-cloud-spanner-admin-database-v1',
    'gapic-google-cloud-spanner-admin-instance-v1',
    'azure-mgmt-datalake-store', 'proto-google-cloud-spanner-v1',
    'proto-google-cloud-spanner-admin-instance-v1', 'runtime',
    'azure-mgmt-datalake-analytics', 'oslotest', 'txaio', 'django-mptt',
    'azure-keyvault', 'azure-mgmt-iothub', 'azure-mgmt-documentdb',
    'oslo-policy', 'shade', 'pywavelets', 'flask-mail',
    'azure-mgmt-devtestlabs', 'atx', 'azure-mgmt-scheduler', 'wand',
    'azure-mgmt-datalake-nspkg', 'azure-mgmt-rdbms', 'empy',
    'azure-mgmt-common', 'venusian', 'cairocffi', 'pysubnettree',
    'agate-excel', 'toml', 'pyvmomi', 'oslosphinx', 'cchardet',
    'requesocks', 'agate-dbf', 'openapi-codec', 'pylibmc', 'reno',
    'httpbin', 'google-cloud-videointelligence', 'udatetime', 'pyroute2',
    'flake8-docstrings', 'autograd', 'nodeenv', 'logutils', 'rq',
    'azure-servicefabric', 'mongoengine', 'pycryptodomex', 'azure-mgmt-logic',
    'leather', 'agate-sql', 'python-logstash', 'delorean', 'thrift-sasl',
    'jpype1', 'shutit', 'wordsegment', 'flufl-enum', 'rjsmin', 'html2text',
    'watchtower', 'pymeta3', 'netius', 'cairosvg', 'pybars3', 'recommonmark',
    'uritemplate-py', 'fakeredis', 'python3-openid', 'filelock', 'jsmin',
    'pipenv', 'django-environ', 'pyhs2', 'pep8-naming', 'typed-ast', 'pyusb',
    'dedupe', 'dateutils', 'tablib', 'luigi', 'pysnmp', 'prettyplotlib',
    'pre-commit', 'polib', 'jenkinsapi', 'rcssmin', 'ptable', 'multiprocess',
    'pymc', 'pytest-metadata', 'django-oauth-toolkit', 'django-allauth',
    'pygithub', 'python-crfsuite', 'python-cdb', 'pydas', 'pytest-cache',
    'pyspin', 'pypi-publisher', 'pika-pool', 'pulp', 'pyinstaller',
    'profilehooks', 'jenkins-job-builder', 'clickclick', 'urwid', 'pep257',
    'sirepo', 'bandit', 'google-apitools', 'zope-proxy', 'cvxopt',
    'pytest-catchlog', 'pybrain', 'gdata', 'toil', 'mypy',
    'python2-pythondialog', 'pypng', 'sure', 'yamllint',
    'robotframework-selenium2library', 'll-xist', 'tempora', 'webassets',
    'pycadf', 'dropbox', 'pypandoc', 'django-taggit', 'paho-mqtt',
    'keystonemiddleware', 'livereload', 'psycogreen', 'geocoder', 'ftfy',
    'yapf', 'glances', 'grequests', 'coloredlogs', 'python-http-client',
    'parsley', 'nose-exclude', 'transaction', 'flask-swagger', 'homeassistant',
    'hvac', 'vcrpy', 'github3-py', 'schematics', 'tinycss',
    'swagger-spec-validator', 'progressbar2', 'pydot', 'backoff', 'pytsite',
    'scapy', 'attrdict', 'shellescape', 'impyla', 'flatten-dict',
    'requests-kerberos', 'pykerberos', 'repoze-who', 'mxnet-mkl', 'cssmin',
    'dask', 'cheroot', 'flake8-polyfill', 'pyotp', 'python-designateclient',
    'simple-salesforce', 'hupper', 'neutron-lib', 'wavefront-cli', 'deepdiff',
    'connexion', 'phonenumberslite', 'natsort', 'tox-travis', 'btrees',
    'rednose', 'flask-testing', 'premailer', 'shortuuid', 'django-countries',
    'ocflib', 'pylint-plugin-utils', 'pyenchant', 'logging', 'pysmi',
    'appier-extras', 'zc-recipe-egg', 'oslo-rootwrap', 'flaky', 'libsass',
    'oslo-versionedobjects', 'ipy', 'pecan', 'diff-match-patch',
    'oslo-reports', 'google', 'aspen', 'rollbar', 'cobra',
    'restructuredtext-lint', 'pythonnet', 'line-profiler', 'trollius',
    'django-bootstrap3', 'pygeoip', 'django-picklefield', 'django-reversion',
    'cytoolz', 'beaker', 'tooz', 'flask-assets', 'uuid', 'osprofiler',
    'bitstring', 'naked', 'flask-babel', 'plac', 'semver', 'django-formtools',
    'python-snappy', 'persistent', 'terminaltables', 'taskflow', 'boxsdk',
    'cerberus', 'flask-principal', 'thinc', 'spacy', 'pycares', 'pylru',
    'kafka', 'pkgconfig', 'couchbase', 'python-utils', 'django-localflavor',
    'django-redis-cache', 'webapp2', 'sqlalchemy-redshift', 'salt',
    'structlog', 'mandrill', 'googlemaps', 'easy-thumbnails', 'automaton',
    'webcolors'
]


def get_requirement(dep):
    """Pre-clean requirement strings passed to the requirements parser.

    Ensures that we can accept both local and relative paths, file and VCS URIs,
    remote URIs, and package names, and that we pass only valid requirement strings
    to the requirements parser. Performs necessary modifications to requirements
    object if the user input was a local relative path.
    
    :param str dep: A requirement line
    :returns: :class:`requirements.Requirement` object
    """
    path = None
    # Split out markers if they are present - similar to how pip does it
    # See pip.req.req_install.InstallRequirement.from_line
    if not any(dep.startswith(uri_prefix) for uri_prefix in SCHEME_LIST):
        marker_sep = ';'
    else:
        marker_sep = '; '
    if marker_sep in dep:
        dep, markers = dep.split(marker_sep, 1)
        markers = markers.strip()
        if not markers:
            markers = None
    else:
        markers = None
    # Strip extras from the requirement so we can make a properly parseable req
    dep, extras = pip.req.req_install._strip_extras(dep)
    # Only operate on local, existing, non-URI formatted paths
    if (is_file(dep) and isinstance(dep, six.string_types) and
            not any(dep.startswith(uri_prefix) for uri_prefix in SCHEME_LIST)):
        dep_path = Path(dep)
        # Only parse if it is a file or an installable dir
        if dep_path.is_file() or (dep_path.is_dir() and pip.utils.is_installable_dir(dep)):
            if dep_path.is_absolute() or dep_path.as_posix() == '.':
                path = dep_path.as_posix()
            else:
                path = get_converted_relative_path(dep)
            dep = dep_path.resolve().as_uri()
    req = [r for r in requirements.parse(dep)][0]
    # If the result is a local file with a URI and we have a local path, unset the URI
    # and set the path instead
    if req.local_file and req.uri and not req.path and path:
        req.path = path
        req.uri = None
    if markers:
        req.markers = markers
    if extras:
        # Bizarrely this is also what pip does...
        req.extras = [r for r in requirements.parse('fakepkg{0}'.format(extras))][0].extras
    return req


def cleanup_toml(tml):
    toml = tml.split('\n')
    new_toml = []

    # Remove all empty lines from TOML.
    for line in toml:
        if line.strip():
            new_toml.append(line)

    toml = '\n'.join(new_toml)
    new_toml = []

    # Add newlines between TOML sections.
    for i, line in enumerate(toml.split('\n')):
        after = False
        # Skip the first line.
        if line.startswith('['):
            if i > 0:
                # Insert a newline before the heading.
                new_toml.append('\n')
            after = True

        new_toml.append(line)
        # Insert a newline after the heading.
        if after:
            new_toml.append('')

    # adding new line at the end of the TOML file
    new_toml.append('')
    toml = '\n'.join(new_toml)
    return toml


def suggest_package(package):
    """Suggests a package name, given a package name."""
    if SESSION_IS_INTERACTIVE:

        if ('-' in package) or ('[' in package) or ('+' in package):
            THRESHOLD = 90
        else:
            THRESHOLD = 86

        # Bypass for speed.
        if package in packages:
            return package

        result = fuzzywuzzy.process.extractOne(package, packages)

        if result[1] > THRESHOLD:
            return result[0]


def python_version(path_to_python):
    if not path_to_python:
        return None

    try:
        c = delegator.run([path_to_python, '--version'], block=False)
    except Exception:
        return None
    output = c.out.strip() or c.err.strip()

    @parse.with_pattern(r'.*')
    def allow_empty(text):
        return text

    TEMPLATE = 'Python {}.{}.{:d}{:AllowEmpty}'
    parsed = parse.parse(TEMPLATE, output, dict(AllowEmpty=allow_empty))
    if parsed:
        parsed = parsed.fixed
    else:
        return None

    return u"{v[0]}.{v[1]}.{v[2]}".format(v=parsed)


def shellquote(s):
    """Prepares a string for the shell (on Windows too!)"""
    if s is None:
        return None
    # Additional escaping for windows paths
    if os.name == 'nt':
        s = "{}".format(s.replace("\\", "\\\\"))

    return '"' + s.replace("'", "'\\''") + '"'


def clean_pkg_version(version):
    """Uses pip to prepare a package version string, from our internal version."""
    return six.u(pep440_version(str(version).replace('==', '')))


class HackedPythonVersion(object):
    """A Beautiful hack, which allows us to tell pip which version of Python we're using."""
    def __init__(self, python_version, python_path):
        self.python_version = python_version
        self.python_path = python_path

    def __enter__(self):
        os.environ['PIP_PYTHON_VERSION'] = str(self.python_version)
        os.environ['PIP_PYTHON_PATH'] = str(self.python_path)

    def __exit__(self, *args):
        # Restore original Python version information.
        del os.environ['PIP_PYTHON_VERSION']


def prepare_pip_source_args(sources, pip_args=None):
    if pip_args is None:
        pip_args = []

    if sources:
        # Add the source to pip.
        pip_args.extend(['-i', sources[0]['url']])

        # Trust the host if it's not verified.
        if not sources[0].get('verify_ssl', True):
            pip_args.extend(['--trusted-host', urlparse(sources[0]['url']).netloc.split(':')[0]])

        # Add additional sources as extra indexes.
        if len(sources) > 1:
            for source in sources[1:]:
                pip_args.extend(['--extra-index-url', source['url']])

                # Trust the host if it's not verified.
                if not source.get('verify_ssl', True):
                    pip_args.extend(['--trusted-host', urlparse(source['url']).netloc.split(':')[0]])

    return pip_args


def actually_resolve_reps(deps, index_lookup, markers_lookup, project, sources, verbose, clear, pre):

    class PipCommand(pip.basecommand.Command):
        """Needed for pip-tools."""
        name = 'PipCommand'

    constraints = []

    for dep in deps:
        t = tempfile.mkstemp(prefix='pipenv-', suffix='-requirement.txt')[1]
        with open(t, 'w') as f:
            f.write(dep)

        if dep.startswith('-e '):
            constraint = pip.req.InstallRequirement.from_editable(dep[len('-e '):])
        else:
            constraint = [c for c in pip.req.parse_requirements(t, session=pip._vendor.requests)][0]
            # extra_constraints = []

        if ' -i ' in dep:
            index_lookup[constraint.name] = project.get_source(url=dep.split(' -i ')[1]).get('name')

        if constraint.markers:
            markers_lookup[constraint.name] = str(constraint.markers).replace('"', "'")

        constraints.append(constraint)

    pip_command = get_pip_command()

    pip_args = []

    if sources:
        pip_args = prepare_pip_source_args(sources, pip_args)

    if verbose:
        print('Using pip: {0}'.format(' '.join(pip_args)))

    pip_options, _ = pip_command.parse_args(pip_args)

    session = pip_command._build_session(pip_options)
    pypi = PyPIRepository(pip_options=pip_options, session=session)

    if verbose:
        logging.log.verbose = True


    resolved_tree = set()

    resolver = Resolver(constraints=constraints, repository=pypi, clear_caches=clear, prereleases=pre)
    # pre-resolve instead of iterating to avoid asking pypi for hashes of editable packages
    try:
        resolved_tree.update(resolver.resolve(max_rounds=PIPENV_MAX_ROUNDS))
    except (NoCandidateFound, DistributionNotFound, HTTPError) as e:
        click.echo(
            '{0}: Your dependencies could not be resolved. You likely have a mismatch in your sub-dependencies.\n  '
            'You can use {1} to bypass this mechanism, then run {2} to inspect the situation.'
            ''.format(
                crayons.red('Warning', bold=True),
                crayons.red('$ pipenv install --skip-lock'),
                crayons.red('$ pipenv graph')
            ),
            err=True)

        click.echo(crayons.blue(e))

        if 'no version found at all' in str(e):
            click.echo(crayons.blue('Please check your version specifier and version number. See PEP440 for more information.'))

        raise RuntimeError

    return resolved_tree, resolver


def resolve_deps(deps, which, which_pip, project, sources=None, verbose=False, python=False, clear=False, pre=False):
    """Given a list of dependencies, return a resolved list of dependencies,
    using pip-tools -- and their hashes, using the warehouse API / pip.
    """

    index_lookup = {}
    markers_lookup = {}

    python_path = which('python')
    backup_python_path = shellquote(sys.executable)

    results = []

    # First (proper) attempt:
    with HackedPythonVersion(python_version=python, python_path=python_path):

        try:
            resolved_tree, resolver = actually_resolve_reps(deps, index_lookup, markers_lookup, project, sources, verbose, clear, pre)
        except RuntimeError:
            # Don't exit here, like usual.
            resolved_tree = None

    # Second (last-resort) attempt:
    if resolved_tree is None:
        with HackedPythonVersion(python_version='.'.join([str(s) for s in sys.version_info[:3]]), python_path=backup_python_path):

            try:
                # Attempt to resolve again, with different Python version information,
                # particularly for particularly particular packages.
                resolved_tree, resolver = actually_resolve_reps(deps, index_lookup, markers_lookup, project, sources, verbose, clear, pre)
            except RuntimeError:
                sys.exit(1)


    for result in resolved_tree:
        if not result.editable:
            name = pep423_name(result.name)
            version = clean_pkg_version(result.specifier)
            index = index_lookup.get(result.name)

            if not markers_lookup.get(result.name):
                markers = str(result.markers) if result.markers and 'extra' not in str(result.markers) else None
            else:
                markers = markers_lookup.get(result.name)

            collected_hashes = []
            if 'python.org' in '|'.join([source['url'] for source in sources]):
                try:
                    # Grab the hashes from the new warehouse API.
                    r = requests.get('https://pypi.org/pypi/{0}/json'.format(name), timeout=10)
                    api_releases = r.json()['releases']

                    cleaned_releases = {}
                    for api_version, api_info in api_releases.items():
                        cleaned_releases[clean_pkg_version(api_version)] = api_info

                    for release in cleaned_releases[version]:
                        collected_hashes.append(release['digests']['sha256'])

                    collected_hashes = ['sha256:' + s for s in collected_hashes]

                    # Collect un-collectable hashes.
                    if not collected_hashes:
                        collected_hashes = list(list(resolver.resolve_hashes([result]).items())[0][1])

                except (ValueError, KeyError, ConnectionError):
                    if verbose:
                        print('Error fetching {}'.format(name))

            d = {'name': name, 'version': version, 'hashes': collected_hashes}

            if index:
                d.update({'index': index})

            if markers:
                d.update({'markers': markers.replace('"', "'")})

            results.append(d)

    return results


def multi_split(s, split):
    """Splits on multiple given separators."""

    for r in split:
        s = s.replace(r, '|')

    return [i for i in s.split('|') if len(i) > 0]


def convert_deps_from_pip(dep):
    """"Converts a pip-formatted dependency to a Pipfile-formatted one."""

    dependency = {}

    req = get_requirement(dep)
    extras = {'extras': req.extras}

    # File installs.
    if (req.uri or req.path or (os.path.isfile(req.name) if req.name else False)) and not req.vcs:
        # Assign a package name to the file, last 7 of it's sha256 hex digest.
        if not req.uri and not req.path:
            req.path = os.path.abspath(req.name)

        hashable_path = req.uri if req.uri else req.path
        req.name = hashlib.sha256(hashable_path.encode('utf-8')).hexdigest()
        req.name = req.name[len(req.name) - 7:]
        # {path: uri} TOML (spec 4 I guess...)
        if req.uri:
            dependency[req.name] = {'file': hashable_path}
        else:
            dependency[req.name] = {'path': hashable_path}

        if req.extras:
            dependency[req.name].update(extras)

        # Add --editable if applicable
        if req.editable:
            dependency[req.name].update({'editable': True})

    # VCS Installs. Extra check for unparsed git over SSH
    elif req.vcs or is_vcs(req.path):
        if req.name is None:
            raise ValueError('pipenv requires an #egg fragment for version controlled '
                             'dependencies. Please install remote dependency '
                             'in the form {0}#egg=<package-name>.'.format(req.uri))

        # Set up this requirement as a proper VCS requirement if it was not
        if not req.vcs and req.path.startswith(VCS_LIST):
            req.vcs = [vcs for vcs in VCS_LIST if req.path.startswith(vcs)][0]
            req.uri = '{0}'.format(req.path)
            req.path = None

        # Crop off the git+, etc part.
        if req.uri.startswith('{0}+'.format(req.vcs)):
            req.uri = req.uri[len(req.vcs) + 1:]
        dependency.setdefault(req.name, {}).update({req.vcs: req.uri})

        # Add --editable, if it's there.
        if req.editable:
            dependency[req.name].update({'editable': True})

        # Add subdirectory, if it's there
        if req.subdirectory:
            dependency[req.name].update({'subdirectory': req.subdirectory})

        # Add the specifier, if it was provided.
        if req.revision:
            dependency[req.name].update({'ref': req.revision})

        # Extras: e.g. #egg=requests[security]
        if req.extras:
            dependency[req.name].update({'extras': req.extras})

    elif req.extras or req.specs:

        specs = None
        # Comparison operators: e.g. Django>1.10
        if req.specs:
            r = multi_split(dep, '!=<>~')
            specs = dep[len(r[0]):]
            dependency[req.name] = specs

        # Extras: e.g. requests[socks]
        if req.extras:
            dependency[req.name] = extras

            if specs:
                dependency[req.name].update({'version': specs})

    # Bare dependencies: e.g. requests
    else:
        dependency[dep] = '*'

    # Cleanup when there's multiple values, e.g. -e.
    if len(dependency) > 1:
        for key in dependency.copy():
            if not hasattr(dependency[key], 'keys'):
                del dependency[key]
    return dependency


def convert_deps_to_pip(deps, project=None, r=True, include_index=False):
    """"Converts a Pipfile-formatted dependency to a pip-formatted one."""

    dependencies = []

    for dep in deps.keys():

        # Default (e.g. '>1.10').
        extra = deps[dep] if isinstance(deps[dep], six.string_types) else ''
        version = ''
        index = ''

        # Get rid of '*'.
        if deps[dep] == '*' or str(extra) == '{}':
            extra = ''

        hash = ''
        # Support for single hash (spec 1).
        if 'hash' in deps[dep]:
            hash = ' --hash={0}'.format(deps[dep]['hash'])

        # Support for multiple hashes (spec 2).
        if 'hashes' in deps[dep]:
            hash = '{0} '.format(''.join([' --hash={0} '.format(h) for h in deps[dep]['hashes']]))

        # Support for extras (e.g. requests[socks])
        if 'extras' in deps[dep]:
            extra = '[{0}]'.format(deps[dep]['extras'][0])

        if 'version' in deps[dep]:
            if not deps[dep]['version'] == '*':
                version = deps[dep]['version']

        # For lockfile format.
        if 'markers' in deps[dep]:
            specs = '; {0}'.format(deps[dep]['markers'])
        else:
            # For pipfile format.
            specs = []
            for specifier in specifiers:
                if specifier in deps[dep]:
                    if not deps[dep][specifier] == '*':
                        specs.append('{0} {1}'.format(specifier, deps[dep][specifier]))
            if specs:
                specs = '; {0}'.format(' and '.join(specs))
            else:
                specs = ''

        if include_index:
            if 'index' in deps[dep]:
                pip_args = prepare_pip_source_args([project.get_source(deps[dep]['index'])])
                index = ' '.join(pip_args)

        # Support for version control
        maybe_vcs = [vcs for vcs in VCS_LIST if vcs in deps[dep]]
        vcs = maybe_vcs[0] if maybe_vcs else None

        # Support for files.
        if 'file' in deps[dep]:
            extra = '{1}{0}'.format(extra, deps[dep]['file']).strip()

            # Flag the file as editable if it is a local relative path
            if 'editable' in deps[dep]:
                dep = '-e '
            else:
                dep = ''

        # Support for paths.
        elif 'path' in deps[dep]:
            extra = '{1}{0}'.format(extra, deps[dep]['path']).strip()

            # Flag the file as editable if it is a local relative path
            if 'editable' in deps[dep]:
                dep = '-e '
            else:
                dep = ''

        if vcs:
            extra = '{0}+{1}'.format(vcs, deps[dep][vcs])

            # Support for @refs.
            if 'ref' in deps[dep]:
                extra += '@{0}'.format(deps[dep]['ref'])

            extra += '#egg={0}'.format(dep)

            # Support for subdirectory
            if 'subdirectory' in deps[dep]:
                extra += '&subdirectory={0}'.format(deps[dep]['subdirectory'])

            # Support for editable.
            if 'editable' in deps[dep]:
                # Support for --egg.
                dep = '-e '
            else:
                dep = ''

        s = '{0}{1}{2}{3}{4} {5}'.format(dep, extra, version, specs, hash, index).strip()
        dependencies.append(s)
    if not r:
        return dependencies

    # Write requirements.txt to tmp directory.
    f = tempfile.NamedTemporaryFile(suffix='-requirements.txt', delete=False)
    f.write('\n'.join(dependencies).encode('utf-8'))
    return f.name


def mkdir_p(newdir):
    """works the way a good mkdir should :)
        - already exists, silently complete
        - regular file in the way, raise an exception
        - parent directory(ies) does not exist, make them as well
        From: http://code.activestate.com/recipes/82465-a-friendly-mkdir/
    """

    if os.path.isdir(newdir):
        pass
    elif os.path.isfile(newdir):
        raise OSError("a file with the same name as the desired dir, '{0}', already exists.".format(newdir))
    else:
        head, tail = os.path.split(newdir)
        if head and not os.path.isdir(head):
            mkdir_p(head)
        if tail:
            os.mkdir(newdir)


def is_required_version(version, specified_version):
    """Check to see if there's a hard requirement for version
    number provided in the Pipfile.
    """

    # Certain packages may be defined with multiple values.
    if isinstance(specified_version, dict):
        specified_version = specified_version.get('version', '')
    if specified_version.startswith('=='):
        return version.strip() == specified_version.split('==')[1].strip()
    return True


def is_vcs(pipfile_entry):
    """Determine if dictionary entry from Pipfile is for a vcs dependency."""

    if hasattr(pipfile_entry, 'keys'):
        return any(key for key in pipfile_entry.keys() if key in VCS_LIST)
    elif isinstance(pipfile_entry, six.string_types):
        # Add scheme for parsing purposes, this is also what pip does
        if pipfile_entry.startswith('git+') and '://' not in pipfile_entry:
            pipfile_entry = pipfile_entry.replace('git+', 'git+ssh://')
        return bool(requirements.requirement.VCS_REGEX.match(pipfile_entry))
    return False


def is_installable_file(path):
    """Determine if a path can potentially be installed"""
    if hasattr(path, 'keys') and any(key for key in path.keys() if key in ['file', 'path']):
        path = urlparse(path['file']).path if 'file' in path else path['path']
    if not isinstance(path, six.string_types) or path == '*':
        return False
    # If the string starts with a valid specifier operator, test if it is a valid
    # specifier set before making a path object (to avoid breakng windows)
    if any(path.startswith(spec) for spec in '!=<>'):
        try:
            pip.utils.packaging.specifiers.SpecifierSet(path)
        # If this is not a valid specifier, just move on and try it as a path
        except pip.utils.packaging.specifiers.InvalidSpecifier:
            pass
        else:
            return False
    lookup_path = Path(path)
    return lookup_path.is_file() or (lookup_path.is_dir() and
            pip.utils.is_installable_dir(lookup_path.resolve().as_posix()))


def is_file(package):
    """Determine if a package name is for a File dependency."""
    if hasattr(package, 'keys'):
        return any(key for key in package.keys() if key in ['file', 'path'])

    if os.path.exists(str(package)):
        return True

    for start in SCHEME_LIST:
        if str(package).startswith(start):
            return True

    return False


def pep440_version(version):
    """Normalize version to PEP 440 standards"""

    # Use pip built-in version parser.
    return str(pip.index.parse_version(version))


def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""
    name = name.lower()
    if any(i not in name for i in (VCS_LIST+SCHEME_LIST)):
        return name.replace('_', '-')
    else:
        return name


def proper_case(package_name):
    """Properly case project name from pypi.org."""

    # Hit the simple API.
    r = requests.get('https://pypi.org/pypi/{0}/json'.format(package_name), timeout=0.3, stream=True)
    if not r.ok:
        raise IOError('Unable to find package {0} in PyPI repository.'.format(package_name))

    r = parse.parse('https://pypi.org/pypi/{name}/json', r.url)
    good_name = r['name']

    return good_name


def split_section(input_file, section_suffix, test_function):
    """
    Split a pipfile or a lockfile section out by section name and test function
    
        :param dict input_file: A dictionary containing either a pipfile or lockfile
        :param str section_suffix: A string of the name of the section
        :param func test_function: A test function to test against the value in the key/value pair
    
    >>> split_section(my_lockfile, 'vcs', is_vcs)
    {
        'default': {
            "six": {
                "hashes": [
                    "sha256:832dc0e10feb1aa2c68dcc57dbb658f1c7e65b9b61af69048abc87a2db00a0eb",
                    "sha256:70e8a77beed4562e7f14fe23a786b54f6296e34344c23bc42f07b15018ff98e9"
                ],
                "version": "==1.11.0"
            }
        },
        'default-vcs': {
            "e1839a8": {
                "editable": true,
                "path": "."
            }
        }
    }
    """
    pipfile_sections = ('packages', 'dev-packages')
    lockfile_sections = ('default', 'develop')
    if any(section in input_file for section in pipfile_sections):
        sections = pipfile_sections
    elif any(section in input_file for section in lockfile_sections):
        sections = lockfile_sections
    else:
        # return the original file if we can't find any pipfile or lockfile sections
        return input_file

    for section in sections:
        split_dict = {}
        entries = input_file.get(section, {})
        for k in list(entries.keys()):
            if test_function(entries.get(k)):
                split_dict[k] = entries.pop(k)
        input_file['-'.join([section, section_suffix])] = split_dict
    return input_file


def split_file(file_dict):
    """Split VCS and editable dependencies out from file."""
    sections = {
        'vcs': is_vcs,
        'editable': lambda x: hasattr(x, 'keys') and x.get('editable')
    }
    for k, func in sections.items():
        file_dict = split_section(file_dict, k, func)
    return file_dict


def merge_deps(file_dict, project, dev=False, requirements=False, ignore_hashes=False, blocking=False, only=False):
    """
    Given a file_dict, merges dependencies and converts them to pip dependency lists.
        :param dict file_dict: The result of calling :func:`pipenv.utils.split_file`
        :param :class:`pipenv.project.Project` project: Pipenv project
        :param bool dev=False: Flag indicating whether dev dependencies are to be installed 
        :param bool requirements=False: Flag indicating whether to use a requirements file
        :param bool ignore_hashes=False:
        :param bool blocking=False:
        :param bool only=False:
        :return: Pip-converted 3-tuples of [deps, requirements_deps]
    """
    deps = []
    requirements_deps = []

    for section in list(file_dict.keys()):
        # Turn develop-vcs into ['develop', 'vcs']
        section_name, suffix = section.rsplit('-', 1) if '-' in section and not section == 'dev-packages' else (section, None)
        if not file_dict[section] or section_name not in ('dev-packages', 'packages', 'default', 'develop'):
            continue
        is_dev = section_name in ('dev-packages', 'develop')
        if is_dev and not dev:
            continue

        if ignore_hashes:
            for k, v in file_dict[section]:
                if 'hash' in v:
                    del v['hash']

        # Block and ignore hashes for all suffixed sections (vcs/editable)
        no_hashes = True if suffix else ignore_hashes
        block = True if suffix else blocking
        include_index = True if not suffix else False
        converted = convert_deps_to_pip(file_dict[section], project, r=False, include_index=include_index)
        deps.extend((d, no_hashes, block) for d in converted)
        if dev and is_dev and requirements:
            requirements_deps.extend((d, no_hashes, block) for d in converted)
    return deps, requirements_deps


def recase_file(file_dict):
    """Recase file before writing to output."""

    if 'packages' in file_dict or 'dev-packages' in file_dict:
        sections = ('packages', 'dev-packages')
    elif 'default' in file_dict or 'develop' in file_dict:
        sections = ('default', 'develop')

    for section in sections:
        file_section = file_dict.get(section, {})

        # Try to properly case each key if we can.
        for key in list(file_section.keys()):
            try:
                cased_key = proper_case(key)
            except IOError:
                cased_key = key
            file_section[cased_key] = file_section.pop(key)

    return file_dict


def get_windows_path(*args):
    """Sanitize a path for windows environments

    Accepts an arbitrary list of arguments and makes a clean windows path"""
    return os.path.normpath(os.path.join(*args))


def find_windows_executable(bin_path, exe_name):
    """Given an executable name, search the given location for an executable"""
    requested_path = get_windows_path(bin_path, exe_name)
    if os.path.exists(requested_path):
        return requested_path

    # Ensure we aren't adding two layers of file extensions
    exe_name = os.path.splitext(exe_name)[0]
    files = ['{0}.{1}'.format(exe_name, ext) for ext in ['', 'py', 'exe', 'bat']]
    exec_paths = [get_windows_path(bin_path, f) for f in files]
    exec_files = [filename for filename in exec_paths if os.path.isfile(filename)]
    if exec_files:
        return exec_files[0]
    return find_executable(exe_name)


def get_converted_relative_path(path, relative_to=os.curdir):
    """Given a vague relative path, return the path relative to the given location"""
    return os.path.join('.', os.path.relpath(path, start=relative_to))


def walk_up(bottom):
    """Mimic os.walk, but walk 'up' instead of down the directory tree.
    From: https://gist.github.com/zdavkeos/1098474
    """

    bottom = os.path.realpath(bottom)

    # Get files in current dir.
    try:
        names = os.listdir(bottom)
    except Exception:
        return

    dirs, nondirs = [], []
    for name in names:
        if os.path.isdir(os.path.join(bottom, name)):
            dirs.append(name)
        else:
            nondirs.append(name)

    yield bottom, dirs, nondirs

    new_path = os.path.realpath(os.path.join(bottom, '..'))

    # See if we are at the top.
    if new_path == bottom:
        return

    for x in walk_up(new_path):
        yield x


def find_requirements(max_depth=3):
    """Returns the path of a Pipfile in parent directories."""

    i = 0
    for c, d, f in walk_up(os.getcwd()):
        i += 1

        if i < max_depth:
            if 'requirements.txt':
                r = os.path.join(c, 'requirements.txt')
                if os.path.isfile(r):
                    return r
    raise RuntimeError('No requirements.txt found!')


# Borrowed from pew to avoid importing pew which imports psutil
# See https://github.com/berdario/pew/blob/master/pew/_utils.py#L82
@contextmanager
def temp_environ():
    """Allow the ability to set os.environ temporarily"""
    environ = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(environ)

def is_valid_url(url):
    """Checks if a given string is an url"""
    pieces = urlparse(url)
    return all([pieces.scheme, pieces.netloc])


def download_file(url, filename):
    """Downloads file from url to a path with filename"""
    r = requests.get(url, stream=True)
    if not r.ok:
        raise IOError('Unable to download file')

    with open(filename, 'wb') as f:
        f.write(r.content)


def need_update_check():
    """Determines whether we need to check for updates."""
    mkdir_p(PIPENV_CACHE_DIR)
    p = os.sep.join((PIPENV_CACHE_DIR, '.pipenv_update_check'))
    if not os.path.exists(p):
        return True
    out_of_date_time = time() - (24 * 60 * 60)
    if os.path.isfile(p) and os.path.getmtime(p) <= out_of_date_time:
        return True
    else:
        return False


def touch_update_stamp():
    """Touches PIPENV_CACHE_DIR/.pipenv_update_check"""
    mkdir_p(PIPENV_CACHE_DIR)
    p = os.sep.join((PIPENV_CACHE_DIR, '.pipenv_update_check'))
    try:
        os.utime(p, None)
    except OSError:
        with open(p, 'w') as fh:
            fh.write('')
