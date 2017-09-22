# -*- coding: utf-8 -*-
from setuptools import setup, find_packages


setup(
    name='pipenv_hello',
    license='MIT',
    version='1.0.0',
    description='Example plugin to pipenv',
    author='Bruno Rocha',
    author_email='rochacbruno@gmail.com',
    url='https://github.com/rochacbruno/pipenv_hello',
    packages=find_packages(),
    install_requires=['pipenv'],
    entry_points={
        'pipenv.extension': [
            'hello = pipenv_hello:main',
        ],
    },
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
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
