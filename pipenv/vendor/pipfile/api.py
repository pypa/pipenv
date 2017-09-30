import toml

import codecs
import json
import hashlib
import platform
import sys
import os


def format_full_version(info):
    version = '{0.major}.{0.minor}.{0.micro}'.format(info)
    kind = info.releaselevel
    if kind != 'final':
        version += kind[0] + str(info.serial)
    return version



class PipfileParser(object):
    def __init__(self, filename='Pipfile'):
        self.filename = filename
        self.sources = []
        self.groups = {
            'default': [],
            'develop': []
        }
        self.group_stack = ['default']
        self.requirements = []

    def __repr__(self):
        return '<PipfileParser path={0!r}'.format(self.filename)

    def parse(self):
        # Open the Pipfile.
        with open(self.filename) as f:
            content = f.read()

        # Load the default configuration.
        default_config = {
            u'source': [{u'url': u'https://pypi.python.org/simple', u'verify_ssl': True, 'name': "pypi"}],
            u'packages': {},
            u'requires': {},
            u'dev-packages': {}
        }

        config = {}
        config.update(default_config)

        # Load the Pipfile's configuration.
        config.update(toml.loads(content))

        # Structure the data for output.
        data = {
            '_meta': {
                'sources': config['source'],
                'requires': config['requires']
            },
        }

        # TODO: Validate given data here.
        self.groups['default'] = config['packages']
        self.groups['develop'] = config['dev-packages']

        # Update the data structure with group information.
        data.update(self.groups)
        return data


class Pipfile(object):
    def __init__(self, filename):
        super(Pipfile, self).__init__()
        self.filename = filename
        self.data = None

    @staticmethod
    def find(max_depth=3):
        """Returns the path of a Pipfile in parent directories."""
        i = 0
        for c, d, f in os.walk(os.getcwd(), topdown=False):
            if i > max_depth:
                raise RuntimeError('No Pipfile found!')
            elif 'Pipfile' in f:
                return os.path.join(c, 'Pipfile')
            i += 1

    @classmethod
    def load(klass, filename):
        """Load a Pipfile from a given filename."""
        p = PipfileParser(filename=filename)
        pipfile = klass(filename=filename)
        pipfile.data = p.parse()
        return pipfile

    @property
    def hash(self):
        """Returns the SHA256 of the pipfile's data."""
        content = json.dumps(self.data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf8")).hexdigest()

    @property
    def contents(self):
        """Returns the contents of the pipfile."""
        with codecs.open(self.filename, 'r', 'utf-8') as f:
            return f.read()

    def lock(self):
        """Returns a JSON representation of the Pipfile."""
        data = self.data
        data['_meta']['hash'] = {"sha256": self.hash}
        data['_meta']['pipfile-spec'] = 6
        return json.dumps(data, indent=4, separators=(',', ': '))

    def assert_requirements(self):
        """"Asserts PEP 508 specifiers."""

        # Support for 508's implementation_version.
        if hasattr(sys, 'implementation'):
            implementation_version = format_full_version(sys.implementation.version)
        else:
            implementation_version = "0"

        # Default to cpython for 2.7.
        if hasattr(sys, 'implementation'):
            implementation_name = sys.implementation.name
        else:
            implementation_name = 'cpython'

        lookup = {
            'os_name': os.name,
            'sys_platform': sys.platform,
            'platform_machine': platform.machine(),
            'platform_python_implementation': platform.python_implementation(),
            'platform_release': platform.release(),
            'platform_system': platform.system(),
            'platform_version': platform.version(),
            'python_version': platform.python_version()[:3],
            'python_full_version': platform.python_version(),
            'implementation_name': implementation_name,
            'implementation_version': implementation_version
        }

        # Assert each specified requirement.
        for marker, specifier in self.data['_meta']['requires'].items():

            if marker in lookup:
                try:
                    assert lookup[marker] == specifier
                except AssertionError:
                    raise AssertionError('Specifier {!r} does not match {!r}.'.format(marker, specifier))


def load(pipfile_path=None):
    """Loads a pipfile from a given path.
    If none is provided, one will try to be found.
    """

    if pipfile_path is None:
        pipfile_path = Pipfile.find()

    return Pipfile.load(filename=pipfile_path)
