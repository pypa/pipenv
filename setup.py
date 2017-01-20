#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import codecs

from setuptools import setup

try:
    # Python 3
    from os import dirname
except ImportError:
    # Python 2
    from os.path import dirname

here = os.path.abspath(dirname(__file__))

with codecs.open(os.path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = '\n' + f.read()


if sys.argv[-1] == "publish":
    os.system("python setup.py sdist bdist_wheel upload")
    sys.exit()

required = [
    'crayons',
    'toml',
    'click',
    'pip',
    'virtualenv'
]

setup(
    name='pipenv',
    version='0.1.2',
    description='Sacred Marriage of Pipfile, Pip, & Virtualenv.',
    long_description=long_description,
    author='Kenneth Reitz',
    author_email='me@kennethreitz.com',
    url='https://github.com/kennethreitz/pipenv',
    packages=['pipenv'],
    entry_points={
        'console_scripts': ['pipenv=pipenv:cli'],
    },
    install_requires=required,
    license='MIT',
    classifiers=(

    ),
)
