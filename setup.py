#!/usr/bin/env python
# -*- coding: utf-8 -*-

import codecs
import os
import sys
from shutil import rmtree

from setuptools import setup, Command

here = os.path.abspath(os.path.dirname(__file__))

with codecs.open(os.path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = '\n' + f.read()

about = {}
with open(os.path.join(here, "pipenv", "__version__.py")) as f:
    exec(f.read(), about)

if sys.argv[-1] == "publish":
    os.system("python setup.py sdist bdist_wheel upload")
    sys.exit()

required = [
    'virtualenv',
    'pew>=0.1.26',
    'pip',
    'pip-tools>=1.9.0',
    'setuptools>=36.3.0'
]

if sys.version_info < (2, 7):
    required.append('requests[security]')
    required.append('ordereddict')


class PublishCommand(Command):
    """Support setup.py publish."""

    description = 'Build and publish the package.'
    user_options = []

    @staticmethod
    def status(s):
        """Prints things in bold."""
        print('\033[1m{0}\033[0m'.format(s))

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        try:
            self.status('Removing previous builds…')
            rmtree(os.path.join(here, 'dist'))
        except FileNotFoundError:
            pass

        self.status('Building Source and Wheel (universal) distribution…')
        os.system('{0} setup.py sdist bdist_wheel --universal'.format(sys.executable))

        self.status('Uploading the package to PyPi via Twine…')
        os.system('twine upload dist/*')

        sys.exit()


setup(
    name='pipenv',
    version=about['__version__'],
    description='Sacred Marriage of Pipfile, Pip, & Virtualenv.',
    long_description=long_description,
    author='Kenneth Reitz',
    author_email='me@kennethreitz.org',
    url='https://github.com/kennethreitz/pipenv',
    packages=[
        'pipenv', 'pipenv.vendor',
        'pipenv.vendor.backports.shutil_get_terminal_size',
        'pipenv.vendor.blindspin', 'pipenv.vendor.click',
        'pipenv.vendor.colorama', 'pipenv.vendor.jinja2',
        'pipenv.vendor.markupsafe', 'pipenv.vendor.pexpect',
        'pipenv.vendor.pipfile', 'pipenv.vendor.psutil',
        'pipenv.vendor.ptyprocess', 'pipenv.vendor.requests',
        'pipenv.vendor.requests.packages',
        'pipenv.vendor.requests.packages.chardet',
        'pipenv.vendor.requests.packages.urllib3',
        'pipenv.vendor.requests.packages.urllib3.contrib',
        'pipenv.vendor.requests.packages.urllib3.packages',
        'pipenv.vendor.requests.packages.urllib3.packages.backports',
        'pipenv.vendor.requests.packages.urllib3.packages.ssl_match_hostname',
        'pipenv.vendor.requests.packages.idna', 'pipenv.vendor.requests.packages.urllib3.util',
        'pipenv.vendor.requirements', 'pipenv.vendor.shutilwhich'],
    entry_points={
        'console_scripts': ['pipenv=pipenv:cli'],
    },
    install_requires=required,
    include_package_data=True,
    license='MIT',
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy'
    ],
)
