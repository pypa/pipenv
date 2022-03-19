import os
import pprint
import sys

import pipenv
from pipenv.pep508checker import lookup
from pipenv.vendor import pythonfinder


def print_utf(line):
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("utf-8"))


def get_pipenv_diagnostics(project):
    print("<details><summary>$ pipenv --support</summary>")
    print("")
    print(f"Pipenv version: `{pipenv.__version__!r}`")
    print("")
    print(f"Pipenv location: `{os.path.dirname(pipenv.__file__)!r}`")
    print("")
    print(f"Python location: `{sys.executable!r}`")
    print("")
    print("Python installations found:")
    print("")

    finder = pythonfinder.Finder(system=False, global_search=True)
    python_paths = finder.find_all_python_versions()
    for python in python_paths:
        print(f"  - `{python.py_version.version}`: `{python.path}`")

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
        print(f"  - `{key}`")
    print("")
    print_utf("Pipenv–specific environment variables:")
    print("")
    for key in os.environ:
        if key.startswith("PIPENV"):
            print(f" - `{key}`: `{os.environ[key]}`")
    print("")
    print_utf("Debug–specific environment variables:")
    print("")
    for key in ("PATH", "SHELL", "EDITOR", "LANG", "PWD", "VIRTUAL_ENV"):
        if key in os.environ:
            print(f"  - `{key}`: `{os.environ[key]}`")
    print("")
    print("")
    print("---------------------------")
    print("")
    if project.pipfile_exists:
        print_utf(f"Contents of `Pipfile` ({project.pipfile_location!r}):")
        print("")
        print("```toml")
        with open(project.pipfile_location) as f:
            print(f.read())
        print("```")
        print("")
    if project.lockfile_exists:
        print("")
        print_utf(f"Contents of `Pipfile.lock` ({project.lockfile_location!r}):")
        print("")
        print("```json")
        with open(project.lockfile_location) as f:
            print(f.read())
        print("```")
    print("</details>")


if __name__ == "__main__":
    from pipenv.project import Project

    get_pipenv_diagnostics(Project())
