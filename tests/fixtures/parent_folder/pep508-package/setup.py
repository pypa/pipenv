import os

from setuptools import find_packages, setup

thisdir = os.path.abspath(os.path.dirname(__file__))
version = "1.0.0"

setup(
    name="pep508_package",
    version=version,
    description="The Backend HTTP Server",
    long_description="This is a package",
    install_requires=[
        "six",
        "sibling_package @ {0}",
    ],
    extras_require={"testing": ["coverage", "flaky"], "dev": ["parver", "invoke", "wheel"]},
    package_dir={"": "src"},
    packages=["pep508_package"],
    include_package_data=True,
    zip_safe=True,
)
