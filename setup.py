#!/usr/bin/env python
# -*- coding: utf-8 -*-

import codecs
import os
import sys

from setuptools import setup

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
    'crayons',
    'toml',
    'click>=6.7',
    'click-completion',
    'pip',
    'parse',
    'psutil',
    'virtualenv',
    'delegator.py>=0.0.6',
    'requirements-parser',
    'pexpect',
    'pipfile==0.0.1',
    'requests>=2.4.0',
    'pew>=0.1.26',
    'blindspin>=2.0.1'
]

# Backport required for earlier versions of Python.
if sys.version_info < (3, 3):
    required.append('backports.shutil_get_terminal_size')

if sys.version_info < (2, 7):
    required.append('requests[security]')
    required.append('ordereddict')

setup(
    name='pipenv',
    version=about['__version__'],
    description='Sacred Marriage of Pipfile, Pip, & Virtualenv.',
    long_description=long_description,
    author='Kenneth Reitz',
    author_email='me@kennethreitz.org',
    url='https://github.com/kennethreitz/pipenv',
    packages=['pipenv'],
    entry_points={
        'console_scripts': ['pipenv=pipenv:cli'],
    },
    install_requires=required,
    license='MIT',
    classifiers=[
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
