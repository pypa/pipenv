import json
import os
import re
import sys
from pathlib import Path

import pytest

from pipenv.utils.processes import subprocess_run
from pipenv.utils.shell import normalize_drive


@pytest.mark.cli
def test_pipenv_where(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("--where")
        assert c.returncode == 0
        assert normalize_drive(p.path) in c.stdout


@pytest.mark.cli
def test_pipenv_venv(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install dataclasses-json")
        assert c.returncode == 0
        c = p.pipenv("--venv")
        assert c.returncode == 0
        venv_path = c.stdout.strip()
        assert os.path.isdir(venv_path)


@pytest.mark.cli
@pytest.mark.skipif(
    sys.version_info[:2] == (3, 8) and os.name == "nt",
    reason="Python 3.8 on Windows is not supported",
)
def test_pipenv_py(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("--python python")
        assert c.returncode == 0
        c = p.pipenv("--py")
        assert c.returncode == 0
        python = c.stdout.strip()
        assert os.path.basename(python).startswith("python")


@pytest.mark.cli
@pytest.mark.skipif(
    os.name == "nt" and sys.version_info[:2] == (3, 8),
    reason="Test issue with windows 3.8 CIs",
)
def test_pipenv_site_packages(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("--python python --site-packages")
        assert c.returncode == 0
        assert "Making site-packages available" in c.stderr

        # no-global-site-packages.txt under stdlib dir should not exist.
        c = p.pipenv(
            "run python -c \"import sysconfig; print(sysconfig.get_path('stdlib'))\""
        )
        assert c.returncode == 0
        stdlib_path = c.stdout.strip()
        assert not os.path.isfile(
            os.path.join(stdlib_path, "no-global-site-packages.txt")
        )


@pytest.mark.cli
def test_pipenv_support(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("--support")
        assert c.returncode == 0
        assert c.stdout


@pytest.mark.cli
def test_pipenv_rm(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("--python python")
        assert c.returncode == 0
        c = p.pipenv("--venv")
        assert c.returncode == 0
        venv_path = c.stdout.strip()
        assert os.path.isdir(venv_path)

        c = p.pipenv("--rm")
        assert c.returncode == 0
        assert c.stdout
        assert not os.path.isdir(venv_path)


@pytest.mark.cli
def test_pipenv_graph(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("install tablib")
        assert c.returncode == 0
        graph = p.pipenv("graph")
        assert graph.returncode == 0
        assert "tablib" in graph.stdout
        graph_json = p.pipenv("graph --json")
        assert graph_json.returncode == 0
        assert "tablib" in graph_json.stdout
        graph_json_tree = p.pipenv("graph --json-tree")
        assert graph_json_tree.returncode == 0
        assert "tablib" in graph_json_tree.stdout


@pytest.mark.cli
def test_pipenv_graph_reverse(pipenv_instance_private_pypi):
    from pipenv.cli import cli
    from pipenv.vendor.click.testing import CliRunner

    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install tablib==0.13.0")
        assert c.returncode == 0

        cli_runner = CliRunner(mix_stderr=False)
        c = cli_runner.invoke(cli, "graph --reverse --json-tree")
        assert c.exit_code == 0

        output = c.stdout
        try:
            json_output = json.loads(output)
        except json.JSONDecodeError:
            pytest.fail(f"Failed to parse JSON from output:\n{output}")

        # Define the expected dependencies and their structure
        expected_dependencies = {
            "backports.csv": ["tablib"],
            "et_xmlfile": ["openpyxl"],
            "jdcal": ["openpyxl"],
            "odfpy": ["tablib"],
            "PyYAML": ["tablib"],
            "xlrd": ["tablib"],
            "xlwt": ["tablib"],
        }

        # Helper function to find a dependency in the JSON tree
        def find_dependency(package_name, tree):
            for dep in tree:
                if dep["package_name"] == package_name:
                    return dep
                if dep["dependencies"]:
                    found = find_dependency(package_name, dep["dependencies"])
                    if found:
                        return found
            return None

        # Check each expected dependency in the JSON output
        for dep_name, sub_deps in expected_dependencies.items():
            dep = find_dependency(dep_name, json_output)
            assert dep is not None, f"{dep_name} not found in JSON output:\n{json_output}"

            # Check for sub-dependencies if any
            for sub_dep in sub_deps:
                sub_dep_found = find_dependency(sub_dep, dep.get("dependencies", []))
                assert sub_dep_found is not None, f"{sub_dep} not found under {dep_name} in JSON output:\n{json_output}"


@pytest.mark.skip(
    reason="There is a disputed vulnerability about pip 24.0 messing up this test."
)
@pytest.mark.cli
@pytest.mark.needs_internet(reason="required by check")
def test_pipenv_check(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        c = p.pipenv("install pyyaml")
        assert c.returncode == 0
        c = p.pipenv("check --use-installed")
        assert c.returncode != 0
        assert "pyyaml" in c.stdout
        c = p.pipenv("uninstall pyyaml")
        assert c.returncode == 0
        c = p.pipenv("install six")
        assert c.returncode == 0
        c = p.pipenv("run python -m pip install --upgrade pip")
        assert c.returncode == 0
        # Note: added
        # 51457: py <=1.11.0 resolved (1.11.0 installed)!
        # this is installed via pytest, and causes a false positive
        # https://github.com/pytest-dev/py/issues/287
        # the issue above is still not resolved.
        # added also 51499
        # https://github.com/pypa/wheel/issues/481
        c = p.pipenv("check --use-installed --ignore 35015 -i 51457 -i 51499")
        assert c.returncode == 0
        assert "Ignoring" in c.stderr


@pytest.mark.cli
@pytest.mark.needs_internet(reason="required by check")
@pytest.mark.parametrize("category", ["CVE", "packages"])
def test_pipenv_check_check_lockfile_categories(pipenv_instance_pypi, category):
    with pipenv_instance_pypi() as p:
        c = p.pipenv(f"install wheel==0.37.1 --categories={category}")
        assert c.returncode == 0
        c = p.pipenv(f"check --categories={category}")
        assert c.returncode != 0
        assert "wheel" in c.stdout


@pytest.mark.cli
@pytest.mark.skipif(
    sys.version_info[:2] == (3, 8) and os.name == "nt",
    reason="This test is not working om Windows Python 3. 8",
)
def test_pipenv_clean(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open("setup.py", "w") as f:
            f.write('from setuptools import setup; setup(name="empty")')
        c = p.pipenv("install -e .")
        assert c.returncode == 0
        c = p.pipenv(f"run pip install -i {p.index_url} six")
        assert c.returncode == 0
        c = p.pipenv("clean")
        assert c.returncode == 0
        assert "six" in c.stdout, f"{c.stdout} -- STDERR: {c.stderr}"


@pytest.mark.cli
def test_venv_envs(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        assert p.pipenv("--envs").stdout


@pytest.mark.cli
def test_bare_output(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        assert p.pipenv("").stdout


@pytest.mark.cli
def test_scripts(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[scripts]
pyver = "which python"
            """.strip()
            f.write(contents)
        c = p.pipenv("scripts")
        assert "pyver" in c.stdout
        assert "which python" in c.stdout


@pytest.mark.cli
def test_help(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        assert p.pipenv("--help").stdout


@pytest.mark.cli
def test_man(pipenv_instance_pypi):
    with pipenv_instance_pypi():
        c = subprocess_run(["pipenv", "--man"])
        assert c.returncode == 0, c.stderr


@pytest.mark.cli
def test_install_parse_error(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        # Make sure unparsable packages don't wind up in the pipfile
        # Escape $ for shell input
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]

[dev-packages]
            """.strip()
            f.write(contents)
        c = p.pipenv("install requests u/\\/p@r\\$34b13+pkg")
        assert c.returncode != 0
        assert "u/\\/p@r$34b13+pkg" not in p.pipfile["packages"]


@pytest.mark.skip(reason="This test clears the cache that other tests may be using.")
@pytest.mark.cli
def test_pipenv_clear(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("--clear")
        assert c.returncode == 0
        assert "Clearing caches" in c.stdout


@pytest.mark.outdated
def test_pipenv_outdated_prerelease(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
sqlalchemy = "<=1.2.3"
            """.strip()
            f.write(contents)
        c = p.pipenv("update --pre --outdated")
        assert c.returncode == 0


@pytest.mark.cli
def test_pipenv_verify_without_pipfile(pipenv_instance_pypi):
    with pipenv_instance_pypi(pipfile=False) as p:
        c = p.pipenv("verify")
        assert c.returncode == 1
        assert "No Pipfile present at project home." in c.stderr


@pytest.mark.cli
def test_pipenv_verify_without_pipfile_lock(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        c = p.pipenv("verify")
        assert c.returncode == 1
        assert "Pipfile.lock is out-of-date." in c.stderr


@pytest.mark.cli
def test_pipenv_verify_locked_passing(pipenv_instance_pypi):
    with pipenv_instance_pypi() as p:
        p.pipenv("lock")
        c = p.pipenv("verify")
        assert c.returncode == 0
        assert "Pipfile.lock is up-to-date." in c.stdout


@pytest.mark.cli
def test_pipenv_verify_locked_outdated_failing(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        p.pipenv("lock")

        # modify the Pipfile
        pf = Path(p.path).joinpath("Pipfile")
        pf_data = pf.read_text()
        pf_new = re.sub(r"\[packages\]", '[packages]\nrequests = "*"', pf_data)
        pf.write_text(pf_new)

        c = p.pipenv("verify")
        assert c.returncode == 1
        assert "Pipfile.lock is out-of-date." in c.stderr
