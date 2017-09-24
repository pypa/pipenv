# -*- coding: utf-8 -*-

# (The MIT License)
#
# Copyright (c) 2014 Kura
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the 'Software'), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


try:
    import simplejson as json
except ImportError:
    import json
from collections import namedtuple
import re

from .release import Release


class Package(object):
    """
    A PyPI package.

    :param pypi_dict: A dictionary retrieved from the PyPI server.
    """

    def __init__(self, pypi_dict):
        self._package = pypi_dict['info']
        self._releases = pypi_dict['releases']

    def __repr__(self):
        return "<Package {0}>".format(self.name)

    @property
    def name(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.name
            u'yarg'
        """
        return self._package['name']

    @property
    def pypi_url(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.url
            u'https://pypi.python.org/pypi/yarg'
        """
        return self._package['package_url']

    @property
    def summary(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.summary
            u'Some random summary stuff'
        """
        return self._package['summary']

    @property
    def description(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.description
            u'A super long description, usually uploaded from the README'
        """
        return self._package['description']

    @property
    def homepage(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.homepage
            u'https://kura.io/yarg/'
        """
        if ('home_page' not in self._package or
           self._package['home_page'] == ""):
            return None
        return self._package['home_page']

    @property
    def bugtracker(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.bugtracker
            u'https://github.com/kura/yarg/issues'
        """
        if ('bugtrack_url' not in self._package or
           self._package['bugtrack_url'] == ""):
            return None
        return self._package['bugtrack_url']

    @property
    def docs(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.docs
            u'https://yarg.readthedocs.org/en/latest'
        """
        if ('docs_url' not in self._package or
           self._package['docs_url'] == ""):
            return None
        return self._package['docs_url']

    @property
    def author(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.author
            Author(name=u'Kura', email=u'kura@kura.io')
        """
        author = namedtuple('Author', 'name email')
        return author(name=self._package['author'],
                      email=self._package['author_email'])

    @property
    def maintainer(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.maintainer
            Maintainer(name=u'Kura', email=u'kura@kura.io')
        """
        maintainer = namedtuple('Maintainer', 'name email')
        return maintainer(name=self._package['maintainer'],
                          email=self._package['maintainer_email'])

    @property
    def license(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.license
            u'MIT'
        """
        return self._package['license']

    @property
    def license_from_classifiers(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.license_from_classifiers
            u'MIT License'
        """
        if len(self.classifiers) > 0:
            for c in self.classifiers:
                if c.startswith("License"):
                    return c.split(" :: ")[-1]

    @property
    def downloads(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.downloads
            Downloads(day=50100, week=367941, month=1601938)  # I wish
        """
        _downloads = self._package['downloads']
        downloads = namedtuple('Downloads', 'day week month')
        return downloads(day=_downloads['last_day'],
                         week=_downloads['last_week'],
                         month=_downloads['last_month'])

    @property
    def classifiers(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.classifiers
            [u'License :: OSI Approved :: MIT License',
             u'Programming Language :: Python :: 2.7',
             u'Programming Language :: Python :: 3.4']
        """
        return self._package['classifiers']

    @property
    def python_versions(self):
        """
        Returns a list of Python version strings that
        the package has listed in :attr:`yarg.Release.classifiers`.

            >>> package = yarg.get('yarg')
            >>> package.python_versions
            [u'2.6', u'2.7', u'3.3', u'3.4']
        """
        version_re = re.compile(r"""Programming Language \:\: """
                                """Python \:\: \d\.\d""")
        return [c.split(' :: ')[-1] for c in self.classifiers
                if version_re.match(c)]

    @property
    def python_implementations(self):
        """
        Returns a list of Python implementation strings that
        the package has listed in :attr:`yarg.Release.classifiers`.

            >>> package = yarg.get('yarg')
            >>> package.python_implementations
            [u'CPython', u'PyPy']
        """
        return [c.split(' :: ')[-1] for c in self.classifiers
                if c.startswith("""Programming Language :: """
                                """Python :: Implementation""")]

    @property
    def latest_release_id(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.latest_release_id
            u'0.1.0'
        """
        return self._package['version']

    @property
    def latest_release(self):
        """
        A list of :class:`yarg.release.Release` objects for each file in the
        latest release.

            >>> package = yarg.get('yarg')
            >>> package.latest_release
            [<Release 0.1.0>, <Release 0.1.0>]
        """
        release_id = self.latest_release_id
        return self.release(release_id)

    @property
    def has_wheel(self):
        """
        Returns `True` if one of the :class:`yarg.release.Release` objects
        in the latest set of release files is `wheel` format. Returns
        `False` if not.

            >>> package = yarg.get('yarg')
            >>> package.has_wheel
            True
        """
        for release in self.latest_release:
            if release.package_type in ('wheel', 'bdist_wheel'):
                return True
        return False

    @property
    def has_egg(self):
        """
        Returns `True` if one of the :class:`yarg.release.Release` objects
        in the latest set of release files is `egg` format. Returns
        `False` if not.

            >>> package = yarg.get('yarg')
            >>> package.has_egg
            False
        """
        for release in self.latest_release:
            if release.package_type in ('egg', 'bdist_egg'):
                return True
        return False

    @property
    def has_source(self):
        """
        Returns `True` if one of the :class:`yarg.release.Release` objects
        in the latest set of release files is `source` format. Returns
        `False` if not.

            >>> package = yarg.get('yarg')
            >>> package.has_source
            True
        """
        for release in self.latest_release:
            if release.package_type in ('source', 'sdist'):
                return True
        return False

    @property
    def release_ids(self):
        """
            >>> package = yarg.get('yarg')
            >>> package.release_ids
            [u'0.0.1', u'0.0.5', u'0.1.0']
        """
        r = [(k, self._releases[k][0]['upload_time'])
             for k in self._releases.keys()
             if len(self._releases[k]) > 0]
        return [k[0] for k in sorted(r, key=lambda k: k[1])]

    def release(self, release_id):
        """
        A list of :class:`yarg.release.Release` objects for each file in a
        release.

        :param release_id: A pypi release id.

            >>> package = yarg.get('yarg')
            >>> last_release = yarg.releases[-1]
            >>> package.release(last_release)
            [<Release 0.1.0>, <Release 0.1.0>]
        """
        if release_id not in self.release_ids:
            return None
        return [Release(release_id, r) for r in self._releases[release_id]]


def json2package(json_content):
    """
    Returns a :class:`yarg.release.Release` object from JSON content from the
    PyPI server.

    :param json_content: JSON encoded content from the PyPI server.
    """
    return Package(json.loads(json_content))
