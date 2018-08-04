# coding: utf-8
import os
import pprint
import sys

import pipenv

from .core import project
from .pep508checker import lookup
from .vendor import pythonfinder


def print_utf(line):
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("utf-8"))


def get_pipenv_diagnostics():
    print("<details><summary>$ pipenv --support</summary>")
    print("")
    print("Pipenv version: `{0!r}`".format(pipenv.__version__))
    print("")
    print("Pipenv location: `{0!r}`".format(os.path.dirname(pipenv.__file__)))
    print("")
    print("Python location: `{0!r}`".format(sys.executable))
    print("")
    print("Python installations found:")
    print("")

    finder = pythonfinder.Finder(system=False, global_search=True)
    python_paths = finder.find_all_python_versions()
    for python in python_paths:
        print("  - `{}`: `{}`".format(python.py_version.version, python.path))

    print("")
    print("PEP 508 Information:")
    print("")
    print("```")
    pprint.pprint(lookup)
    print("```")
    print("")
    print("System environment variables:")
    print("")
    for key in os.environ:
        print("  - `{0}`".format(key))
    print("")
    print_utf(u"Pipenv–specific environment variables:")
    print("")
    for key in os.environ:
        if key.startswith("PIPENV"):
            print(" - `{0}`: `{1}`".format(key, os.environ[key]))
    print("")
    print_utf(u"Debug–specific environment variables:")
    print("")
    for key in ("PATH", "SHELL", "EDITOR", "LANG", "PWD", "VIRTUAL_ENV"):
        if key in os.environ:
            print("  - `{0}`: `{1}`".format(key, os.environ[key]))
    print("")
    print("")
    print("---------------------------")
    print("")
    if project.pipfile_exists:
        print_utf(u"Contents of `Pipfile` ({0!r}):".format(project.pipfile_location))
        print("")
        print("```toml")
        with open(project.pipfile_location, "r") as f:
            print(f.read())
        print("```")
        print("")
    if project.lockfile_exists:
        print("")
        print_utf(
            u"Contents of `Pipfile.lock` ({0!r}):".format(project.lockfile_location)
        )
        print("")
        print("```json")
        with open(project.lockfile_location, "r") as f:
            print(f.read())
        print("```")
    print("</details>")


if __name__ == "__main__":
    get_pipenv_diagnostics()
