import pytest


@pytest.mark.upgrade
def test_category_sorted_alphabetically_with_directive(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[pipenv]
sort_pipfile = true

[packages]
zipp = "*"
six = 1.11
colorama = "*"
atomicwrites = "*"
            """.strip()
            f.write(contents)

        package_name = "six"
        c = p.pipenv(f"upgrade {package_name}")
        assert c.returncode == 0
        assert list(p.pipfile["packages"].keys()) == [
            "atomicwrites",
            "colorama",
            "six",
            "zipp",
        ]


@pytest.mark.upgrade
def test_category_not_sorted_without_directive(pipenv_instance_private_pypi):
    with pipenv_instance_private_pypi() as p:
        with open(p.pipfile_path, "w") as f:
            contents = """
[packages]
zipp = "*"
six = 1.11
colorama = "*"
atomicwrites = "*"
            """.strip()
            f.write(contents)

        package_name = "six"
        c = p.pipenv(f"upgrade {package_name}")
        assert c.returncode == 0
        assert list(p.pipfile["packages"].keys()) == [
            "zipp",
            "colorama",
            "atomicwrites",
            "six",
        ]
