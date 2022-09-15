#!/usr/bin/env python
import codecs
import os
import sys

from setuptools import find_packages, setup

here = os.path.abspath(os.path.dirname(__file__))

with codecs.open(os.path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = "\n" + f.read()

about = {}

with open(os.path.join(here, "pipenv", "__version__.py")) as f:
    exec(f.read(), about)

if sys.argv[-1] == "publish":
    os.system("python setup.py sdist bdist_wheel upload")
    sys.exit()

required = [
    "certifi",
    "setuptools>=36.2.1",
    "virtualenv-clone>=0.2.5",
    "virtualenv",
]
extras = {
    "dev": [
        "towncrier",
        "bs4",
        "sphinx",
        "flake8>=3.3.0,<4.0",
        "black;python_version>='3.7'",
        "parver",
        "invoke",
    ],
    "tests": ["pytest>=5.0", "pytest-timeout", "pytest-xdist", "flaky", "mock"],
}


setup(
    name="pipenv",
    version=about["__version__"],
    description="Python Development Workflow for Humans.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Pipenv maintainer team",
    author_email="distutils-sig@python.org",
    url="https://github.com/pypa/pipenv",
    packages=find_packages(exclude=["tests", "tests.*", "tasks", "tasks.*"]),
    entry_points={
        "console_scripts": [
            "pipenv=pipenv:cli",
            "pipenv-resolver=pipenv.resolver:main",
        ]
    },
    package_data={
        "": ["LICENSE", "NOTICES"],
        "pipenv.patched.pip._vendor.certifi": ["*.pem"],
        "pipenv.patched.pip._vendor.requests": ["*.pem"],
        "pipenv.patched.pip._vendor.distlib._backport": ["sysconfig.cfg"],
        "pipenv.patched.pip._vendor.distlib": [
            "t32.exe",
            "t64.exe",
            "w32.exe",
            "w64.exe",
        ],
    },
    python_requires=">=3.7",
    zip_safe=True,
    setup_requires=[],
    install_requires=required,
    extras_require=extras,
    include_package_data=True,
    license="MIT",
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
    ],
)
