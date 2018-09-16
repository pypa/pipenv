from setuptools import setup, find_packages, Command
import codecs
import os
import re
import sys
from shutil import rmtree

with open("pytest_pypi/version.py") as f:
    code = compile(f.read(), "pytest_pypi/version.py", 'exec')
    exec(code)

here = os.path.abspath(os.path.dirname(__file__))

# Get the long description from the relevant file
with codecs.open(os.path.join(here, 'DESCRIPTION.rst'), encoding='utf-8') as f:
    long_description = f.read()

class UploadCommand(Command):
    """Support setup.py upload."""

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
        except OSError:
            pass

        self.status('Building Source and Wheel (universal) distribution…')
        os.system('{0} setup.py sdist bdist_wheel --universal'.format(sys.executable))

        self.status('Uploading the package to PyPI via Twine…')
        os.system('twine upload dist/*')

        self.status('Pushing git tags…')
        os.system('git tag v{0}'.format(__version__))
        os.system('git push --tags')

        sys.exit()

setup(
    name="pytest-pypi",

    # There are various approaches to referencing the version. For a discussion,
    # see http://packaging.python.org/en/latest/tutorial.html#version
    version=__version__,

    description="Easily test your HTTP library against a local copy of pypi",
    long_description=long_description,

    # The project URL.
    url='https://github.com/kennethreitz/pytest-pypi',

    # Author details
    author='Kenneth Reitz',
    author_email='me@kennethreitz.org',

    # Choose your license
    license='MIT',

    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Testing',
        'Topic :: Software Development :: Libraries',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],

    # What does your project relate to?
    keywords='pytest-pypi testing pytest pypi',
    packages=find_packages(exclude=["contrib", "docs", "tests*"]),
    include_package_data = True, # include files listed in MANIFEST.in
    install_requires = ['Flask', 'six'],

    # the following makes a plugin available to pytest
    entry_points = {
        'pytest11': [
            'pypi = pytest_pypi.plugin',
        ]
    },
    cmdclass={
        'upload': UploadCommand,
    },
)
