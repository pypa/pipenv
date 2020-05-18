import os

from setuptools import find_packages, setup

thisdir = os.path.abspath(os.path.dirname(__file__))
version = "1.0.0"

testing_extras = ["coverage", "flaky"]

setup(
    name="sibling_package",
    version=version,
    description="The Backend HTTP Server",
    long_description="This is a package",
    install_requires=[
        "toml",
        "urllib3"
    ],
    tests_require=testing_extras,
    package_dir={"": "src"},
    packages=["sibling_package"],
    include_package_data=True,
    zip_safe=True,
)
