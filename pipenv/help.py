import os
import pprint
import sys

import pipenv
from pipenv.pep508checker import lookup
from pipenv.vendor import pythonfinder


def get_pipenv_diagnostics(project):
    print("<details><summary>$ pipenv --support</summary>")
    print("")
    print(f"Pipenv version: `{pipenv.__version__!r}`")
    print("")
    print(f"Pipenv location: `{os.path.dirname(pipenv.__file__)!r}`")
    print("")
    print(f"Python location: `{sys.executable!r}`")
    print("")
    print(f"OS Name: `{os.name!r}`")
    print("")

    try:
        import pip

        print(f"User pip version: `{pip.__version__!r}`")
        print("")
    except ImportError:
        pass

    # uv integration status
    uv_enabled = os.environ.get("PIPENV_UV", "")
    if uv_enabled:
        print(f"uv integration: `enabled` (PIPENV_UV={uv_enabled!r})")
        try:
            from pipenv.uv import find_uv_bin

            uv_bin = find_uv_bin()
            import subprocess

            uv_version_result = subprocess.run(
                [uv_bin, "--version"], capture_output=True, text=True, check=False
            )
            uv_version = uv_version_result.stdout.strip() or "unknown"
            print(f"uv binary: `{uv_bin!r}`")
            print(f"uv version: `{uv_version!r}`")
        except FileNotFoundError:
            print("uv binary: `not found`")
    else:
        print("uv integration: `disabled` (set PIPENV_UV=1 to enable)")
    print("")

    print("user Python installations found:")
    print("")
    finder = pythonfinder.Finder(system=False, global_search=True)
    python_paths = finder.find_all_python_versions()
    for python in python_paths:
        print(f"  - `{python.version_str}`: `{python.path}`")

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
    print("Pipenv–specific environment variables:")
    print("")
    for key in os.environ:
        if key.startswith("PIPENV"):
            print(f" - `{key}`: `{os.environ[key]}`")
    print("")
    print("Debug–specific environment variables:")
    print("")
    for key in ("PATH", "SHELL", "EDITOR", "LANG", "PWD", "VIRTUAL_ENV"):
        if key in os.environ:
            print(f"  - `{key}`: `{os.environ[key]}`")
    print("")
    print("")
    print("---------------------------")
    print("")
    if project.pipfile_exists:
        print(f"Contents of `Pipfile` ({project.pipfile_location!r}):")
        print("")
        print("```toml")
        with open(project.pipfile_location) as f:
            print(f.read())
        print("```")
        print("")
    if project.lockfile_exists:
        print("")
        print(f"Contents of `Pipfile.lock` ({project.lockfile_location!r}):")
        print("")
        print("```json")
        with open(project.lockfile_location) as f:
            print(f.read())
        print("```")
    print("</details>")


if __name__ == "__main__":
    from pipenv.project import Project

    get_pipenv_diagnostics(Project())
