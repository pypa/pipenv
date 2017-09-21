# -*- coding: utf-8 -*-
import os
import hashlib
import tempfile

import delegator
import pip
import parse
import requirements
import fuzzywuzzy.process
import requests
import six

from piptools.resolver import Resolver
from piptools.repositories.pypi import PyPIRepository
from piptools.scripts.compile import get_pip_command
from piptools import logging

from .environments import PIPENV_DONT_EAT_EDITABLES

# List of version control systems we support.
VCS_LIST = ('git', 'svn', 'hg', 'bzr')
FILE_LIST = ('http://', 'https://', 'ftp://', 'file:///')

requests = requests.Session()

# import requests
# from pyquery import PyQuery as pq
# r = requests.get('https://python3wos.appspot.com')
# d = pq(r.content)
# collected = []
# for td in [pq(t) for t in d('td')]:
#     if td('a').text():
#         collected.append(td('a').text().strip().split()[0])
# print(collected)

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
    'factory-boy', 'webtest', 'django-cors-headers', 'codeintel', 'suds',
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


def suggest_package(package):
    """Suggests a package name, given a package name."""
    THRESHOLD = 86

    # Bypass for speed.
    if package in packages:
        return package

    result = fuzzywuzzy.process.extractOne(package, packages)
    # print(result)
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
    return '"' + s.replace("'", "'\\''") + '"'


def clean_pkg_version(version):
    """Uses pip to prepare a package version string, from our internal version."""
    return six.u(pep440_version(str(version).replace('==', '')))


class HackedPythonVersion(object):
    """A Beautiful hack, which allows us to tell pip which version of Python we're using."""
    def __init__(self, python):
        self.python = python

    def __enter__(self):
        if self.python:
            os.environ['PIP_PYTHON_VERSION'] = str(self.python)

    def __exit__(self, *args):
        # Restore original Python version information.
        if self.python:
            del os.environ['PIP_PYTHON_VERSION']


def best_matches_from(path, which, which_pip, project):
    """Will attempt to resolve dependencies from a given source path."""
    def gen(setup_py_path, which):

        # Install the path into develop mode, since it's going to be used anyway...
        c = delegator.run('{0} {1} install -v -n'.format(which('python'), shellquote(setup_py_path)))
        output = c.out

        for line in output.split('\n'):
            if line.startswith('Searching for'):
                yield line.split('for')[1].strip()

    setup_py_path = os.path.abspath(os.sep.join([path, 'setup.py']))
    if os.path.isfile(setup_py_path) and not PIPENV_DONT_EAT_EDITABLES:
        return list(gen(setup_py_path, which))
    else:
        if not PIPENV_DONT_EAT_EDITABLES:
            destination = os.path.abspath(os.sep.join([project.virtualenv_location, 'src']))

            # Install the package into the virtualenvironment tree.
            c = delegator.run(
                '{0} install -e {1} --no-deps --src {2} -v'.format(
                    which_pip(),
                    path,
                    shellquote(destination)
                )
            )
            result = None
            for line in c.out.split('\n'):
                line = line.strip()
                if line.startswith('Installed'):
                    result = line[len('Installed '):].strip()

            setup_py_path = os.path.abspath(os.sep.join([(result or ''), 'setup.py']))

            return list(gen(setup_py_path, which))
        else:
            return []


def resolve_deps(deps, which, which_pip, project, sources=None, verbose=False, python=False, clear=False):
    """Given a list of dependencies, return a resolved list of dependencies,
    using pip-tools -- and their hashes, using the warehouse API / pip.
    """

    with HackedPythonVersion(python):

        class PipCommand(pip.basecommand.Command):
            """Needed for pip-tools."""
            name = 'PipCommand'

        constraints = []
        extra_constraints = []

        for dep in deps:
            t = tempfile.mkstemp(prefix='pipenv-', suffix='-requirement.txt')[1]
            with open(t, 'w') as f:
                f.write(dep)

            if dep.startswith('-e '):
                constraint = pip.req.InstallRequirement.from_editable(dep[len('-e '):])
                # Resolve extra constraints from -e packages (that rely on setuptools.)
                extra_constraints = best_matches_from(dep[len('-e '):], which=which, which_pip=which_pip, project=project)
                extra_constraints = [pip.req.InstallRequirement.from_line(c) for c in extra_constraints]
            else:
                constraint = [c for c in pip.req.parse_requirements(t, session=pip._vendor.requests)][0]
                extra_constraints = []

            constraints.append(constraint)
            constraints.extend(extra_constraints)

        pip_command = get_pip_command()

        pip_args = []

        if sources:
            pip_args.extend(['-i', sources[0]['url']])

        pip_options, _ = pip_command.parse_args(pip_args)

        pypi = PyPIRepository(pip_options=pip_options, session=requests)

        if verbose:
            logging.log.verbose = True

        resolver = Resolver(constraints=constraints, repository=pypi, clear_caches=clear)
        results = []

        # pre-resolve instead of iterating to avoid asking pypi for hashes of editable packages
        resolved_tree = resolver.resolve()

    for result in resolved_tree:
        name = pep423_name(result.name)
        version = clean_pkg_version(result.specifier)

        collected_hashes = []

        try:
            # Grab the hashes from the new warehouse API.
            r = requests.get('https://pypi.org/pypi/{0}/json'.format(name))
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

        except (ValueError, KeyError):
            pass

        results.append({'name': name, 'version': version, 'hashes': collected_hashes})

    return results


def format_toml(data):
    """Pretty-formats a given toml string."""

    data = data.split('\n')
    for i, line in enumerate(data):
        if i > 0:
            if line.startswith('['):
                data[i] = '\n{0}'.format(line)

    return '\n'.join(data)


def multi_split(s, split):
    """Splits on multiple given separators."""

    for r in split:
        s = s.replace(r, '|')

    return [i for i in s.split('|') if len(i) > 0]


def convert_deps_from_pip(dep):
    """"Converts a pip-formatted dependency to a Pipfile-formatted one."""

    dependency = {}

    req = [r for r in requirements.parse(dep)][0]

    # File installs.
    if (req.uri or (os.path.exists(req.path) if req.path else False)) and not req.vcs:

        # Assign a package name to the file, last 7 of it's sha256 hex digest.
        hashable_path = req.uri if req.uri else req.path
        req.name = hashlib.sha256(hashable_path.encode('utf-8')).hexdigest()
        req.name = req.name[len(req.name) - 7:]

        # {path: uri} TOML (spec 4 I guess...)
        dependency[req.name] = {'path': hashable_path}

        # Add --editable if applicable
        if req.editable:
            dependency[req.name].update({'editable': True})

    # VCS Installs.
    if req.vcs:
        if req.name is None:
            raise ValueError('pipenv requires an #egg fragment for version controlled '
                             'dependencies. Please install remote dependency '
                             'in the form {0}#egg=<package-name>.'.format(req.uri))

        # Extras: e.g. #egg=requests[security]
        if req.extras:
            dependency[req.name] = {'extras': req.extras}
        # Crop off the git+, etc part.
        dependency.setdefault(req.name, {}).update({req.vcs: req.uri[len(req.vcs) + 1:]})

        # Add --editable, if it's there.
        if req.editable:
            dependency[req.name].update({'editable': True})

        # Add subdirectory, if it's there
        if req.subdirectory:
            dependency[req.name].update({'subdirectory': req.subdirectory})

        # Add the specifier, if it was provided.
        if req.revision:
            dependency[req.name].update({'ref': req.revision})

    elif req.specs or req.extras:

        specs = None
        # Comparison operators: e.g. Django>1.10
        if req.specs:
            r = multi_split(dep, '!=<>')
            specs = dep[len(r[0]):]
            dependency[req.name] = specs

        # Extras: e.g. requests[socks]
        if req.extras:
            dependency[req.name] = {'extras': req.extras}

            if specs:
                dependency[req.name].update({'version': specs})

    # Bare dependencies: e.g. requests
    else:
        dependency[dep] = '*'

    return dependency


def convert_deps_to_pip(deps, r=True):
    """"Converts a Pipfile-formatted dependency to a pip-formatted one."""

    dependencies = []

    for dep in deps.keys():

        # Default (e.g. '>1.10').
        extra = deps[dep] if isinstance(deps[dep], six.string_types) else ''
        version = ''

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
            version = deps[dep]['version']

        # Support for version control
        maybe_vcs = [vcs for vcs in VCS_LIST if vcs in deps[dep]]
        vcs = maybe_vcs[0] if maybe_vcs else None

        # Support for files.
        if 'file' in deps[dep]:
            extra = deps[dep]['file']

            # Flag the file as editable if it is a local relative path
            if 'editable' in deps[dep]:
                dep = '-e '
            else:
                dep = ''

        # Support for paths.
        if 'path' in deps[dep]:
            extra = deps[dep]['path']

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

        dependencies.append('{0}{1}{2}{3}'.format(dep, extra, version, hash))

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
    return False


def is_file(package):
    """Determine if a package name is for a File dependency."""
    if os.path.exists(str(package)):
        return True

    for start in FILE_LIST:
        if str(package).startswith(start):
            return True

    return False


def pep440_version(version):
    """Normalize version to PEP 440 standards"""

    # Use pip built-in version parser.
    return str(pip.index.parse_version(version))


def pep423_name(name):
    """Normalize package name to PEP 423 style standard."""

    return name.lower().replace('_', '-')


def proper_case(package_name):
    """Properly case project name from pypi.org."""

    # Hit the simple API.
    r = requests.get('https://pypi.org/pypi/{0}/json'.format(package_name), timeout=0.3, stream=True)
    if not r.ok:
        raise IOError('Unable to find package {0} in PyPI repository.'.format(package_name))

    r = parse.parse('https://pypi.org/pypi/{name}/json', r.url)
    good_name = r['name']

    return good_name


def split_vcs(split_file):
    """Split VCS dependencies out from file."""

    if 'packages' in split_file or 'dev-packages' in split_file:
        sections = ('packages', 'dev-packages')
    elif 'default' in split_file or 'develop' in split_file:
        sections = ('default', 'develop')

    # For each vcs entry in a given section, move it to section-vcs.
    for section in sections:
        entries = split_file.get(section, {})
        vcs_dict = dict((k, entries.pop(k)) for k in list(entries.keys()) if is_vcs(entries[k]))
        split_file[section + '-vcs'] = vcs_dict

    return split_file


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
    clean_path = os.path.join(*args)
    return os.path.normpath(clean_path)


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
    return exec_files[0]


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
