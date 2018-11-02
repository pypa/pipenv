# -*- coding: utf-8 -*-
import os
import pytest
from mock import patch, Mock
from first import first
import pipenv.utils
import pythonfinder.utils


# Pipfile format <-> requirements.txt format.
DEP_PIP_PAIRS = [
    ({"requests": "*"}, "requests"),
    ({"requests": {"extras": ["socks"], "version": "*"}}, "requests[socks]"),
    ({"django": ">1.10"}, "django>1.10"),
    ({"Django": ">1.10"}, "Django>1.10"),
    ({"requests": {"extras": ["socks"], "version": ">1.10"}}, "requests[socks]>1.10"),
    ({"requests": {"extras": ["socks"], "version": "==1.10"}}, "requests[socks]==1.10"),
    (
        {
            "pinax": {
                "git": "git://github.com/pinax/pinax.git",
                "ref": "1.4",
                "editable": True,
            }
        },
        "-e git+git://github.com/pinax/pinax.git@1.4#egg=pinax",
    ),
    (
        {"pinax": {"git": "git://github.com/pinax/pinax.git", "ref": "1.4"}},
        "git+git://github.com/pinax/pinax.git@1.4#egg=pinax",
    ),
    (  # Mercurial.
        {
            "MyProject": {
                "hg": "http://hg.myproject.org/MyProject",
                "ref": "da39a3ee5e6b",
            }
        },
        "hg+http://hg.myproject.org/MyProject@da39a3ee5e6b#egg=MyProject",
    ),
    (  # SVN.
        {
            "MyProject": {
                "svn": "svn://svn.myproject.org/svn/MyProject",
                "editable": True,
            }
        },
        "-e svn+svn://svn.myproject.org/svn/MyProject#egg=MyProject",
    ),
    (
        # Extras in url
        {
            "discord.py": {
                "file": "https://github.com/Rapptz/discord.py/archive/rewrite.zip",
                "extras": ["voice"],
            }
        },
        "https://github.com/Rapptz/discord.py/archive/rewrite.zip#egg=discord.py[voice]",
    ),
    (
        {
            "requests": {
                "git": "https://github.com/requests/requests.git",
                "ref": "master",
                "extras": ["security"],
                "editable": False,
            }
        },
        "git+https://github.com/requests/requests.git@master#egg=requests[security]",
    ),
]


@pytest.mark.utils
@pytest.mark.parametrize("deps, expected", DEP_PIP_PAIRS)
def test_convert_deps_to_pip(deps, expected):
    if expected.startswith("Django"):
        expected = expected.lower()
    assert pipenv.utils.convert_deps_to_pip(deps, r=False) == [expected]


@pytest.mark.utils
@pytest.mark.parametrize(
    "deps, expected",
    [
        # This one should be collapsed and treated as {'requests': '*'}.
        ({"requests": {}}, "requests"),
        # Hash value should be passed into the result.
        (
            {
                "FooProject": {
                    "version": "==1.2",
                    "hash": "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                }
            },
            "FooProject==1.2 --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        ),
        (
            {
                "FooProject": {
                    "version": "==1.2",
                    "extras": ["stuff"],
                    "hash": "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                }
            },
            "FooProject[stuff]==1.2 --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        ),
        (
            {
                "requests": {
                    "git": "https://github.com/requests/requests.git",
                    "ref": "master",
                    "extras": ["security"],
                }
            },
            "git+https://github.com/requests/requests.git@master#egg=requests[security]",
        ),
    ],
)
def test_convert_deps_to_pip_one_way(deps, expected):
    assert pipenv.utils.convert_deps_to_pip(deps, r=False) == [expected.lower()]


@pytest.mark.skipif(isinstance(u"", str), reason="don't need to test if unicode is str")
@pytest.mark.utils
def test_convert_deps_to_pip_unicode():
    deps = {u"django": u"==1.10"}
    deps = pipenv.utils.convert_deps_to_pip(deps, r=False)
    assert deps[0] == "django==1.10"


class TestUtils:
    """Test utility functions in pipenv"""

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "version, specified_ver, expected",
        [
            ("*", "*", True),
            ("2.1.6", "==2.1.4", False),
            ("20160913", ">=20140815", True),
            (
                "1.4",
                {"svn": "svn://svn.myproj.org/svn/MyProj", "version": "==1.4"},
                True,
            ),
            ("2.13.0", {"extras": ["socks"], "version": "==2.12.4"}, False),
        ],
    )
    def test_is_required_version(self, version, specified_ver, expected):
        assert pipenv.utils.is_required_version(version, specified_ver) is expected

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "entry, expected",
        [
            ({"git": "package.git", "ref": "v0.0.1"}, True),
            ({"hg": "https://package.com/package", "ref": "v1.2.3"}, True),
            ("*", False),
            ({"some_value": 5, "other_value": object()}, False),
            ("package", False),
            ("git+https://github.com/requests/requests.git#egg=requests", True),
            ("git+git@github.com:requests/requests.git#egg=requests", True),
            ("gitdb2", False),
        ],
    )
    @pytest.mark.vcs
    def test_is_vcs(self, entry, expected):
        from pipenv.vendor.requirementslib.utils import is_vcs
        assert is_vcs(entry) is expected

    @pytest.mark.utils
    def test_split_file(self):
        pipfile_dict = {
            "packages": {
                "requests": {"git": "https://github.com/kennethreitz/requests.git"},
                "Flask": "*",
                "tablib": {"path": ".", "editable": True},
            },
            "dev-packages": {
                "Django": "==1.10",
                "click": {"svn": "https://svn.notareal.com/click"},
                "crayons": {"hg": "https://hg.alsonotreal.com/crayons"},
            },
        }
        split_dict = pipenv.utils.split_file(pipfile_dict)
        assert list(split_dict["packages"].keys()) == ["Flask"]
        assert split_dict["packages-vcs"] == {
            "requests": {"git": "https://github.com/kennethreitz/requests.git"}
        }
        assert split_dict["packages-editable"] == {
            "tablib": {"path": ".", "editable": True}
        }
        assert list(split_dict["dev-packages"].keys()) == ["Django"]
        assert "click" in split_dict["dev-packages-vcs"]
        assert "crayons" in split_dict["dev-packages-vcs"]

    @pytest.mark.utils
    def test_python_version_from_bad_path(self):
        assert pipenv.utils.python_version("/fake/path") is None

    @pytest.mark.utils
    def test_python_version_from_non_python(self):
        assert pipenv.utils.python_version("/dev/null") is None

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "version_output, version",
        [
            ("Python 3.6.2", "3.6.2"),
            ("Python 3.6.2 :: Continuum Analytics, Inc.", "3.6.2"),
            ("Python 3.6.20 :: Continuum Analytics, Inc.", "3.6.20"),
            (
                "Python 3.5.3 (3f6eaa010fce78cc7973bdc1dfdb95970f08fed2, Jan 13 2018, 18:14:01)\n[PyPy 5.10.1 with GCC 4.2.1 Compatible Apple LLVM 9.0.0 (clang-900.0.39.2)]",
                "3.5.3",
            ),
        ],
    )
    # @patch(".vendor.pythonfinder.utils.get_python_version")
    def test_python_version_output_variants(
        self, monkeypatch, version_output, version
    ):
        def mock_version(path):
            return version_output.split()[1]
        monkeypatch.setattr("pipenv.vendor.pythonfinder.utils.get_python_version", mock_version)
        assert pipenv.utils.python_version("some/path") == version

    @pytest.mark.utils
    @pytest.mark.windows
    @pytest.mark.skipif(os.name != "nt", reason="Windows test only")
    def test_windows_shellquote(self):
        test_path = "C:\Program Files\Python36\python.exe"
        expected_path = '"C:\\\\Program Files\\\\Python36\\\\python.exe"'
        assert pipenv.utils.escape_grouped_arguments(test_path) == expected_path

    @pytest.mark.utils
    def test_is_valid_url(self):
        url = "https://github.com/kennethreitz/requests.git"
        not_url = "something_else"
        assert pipenv.utils.is_valid_url(url)
        assert pipenv.utils.is_valid_url(not_url) is False

    @pytest.mark.utils
    def test_download_file(self):
        url = "https://github.com/kennethreitz/pipenv/blob/master/README.md"
        output = "test_download.md"
        pipenv.utils.download_file(url, output)
        assert os.path.exists(output)
        os.remove(output)

    @pytest.mark.utils
    def test_new_line_end_of_toml_file(this):
        # toml file that needs clean up
        toml = """
[dev-packages]

"flake8" = ">=3.3.0,<4"
pytest = "*"
mock = "*"
sphinx = "<=1.5.5"
"-e ." = "*"
twine = "*"
"sphinx-click" = "*"
"pytest-xdist" = "*"
        """
        new_toml = pipenv.utils.cleanup_toml(toml)
        # testing if the end of the generated file contains a newline
        assert new_toml[-1] == "\n"

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "input_path, expected",
        [
            (
                "c:\\Program Files\\Python36\\python.exe",
                "C:\\Program Files\\Python36\\python.exe",
            ),
            (
                "C:\\Program Files\\Python36\\python.exe",
                "C:\\Program Files\\Python36\\python.exe",
            ),
            ("\\\\host\\share\\file.zip", "\\\\host\\share\\file.zip"),
            ("artifacts\\file.zip", "artifacts\\file.zip"),
            (".\\artifacts\\file.zip", ".\\artifacts\\file.zip"),
            ("..\\otherproject\\file.zip", "..\\otherproject\\file.zip"),
        ],
    )
    @pytest.mark.skipif(os.name != "nt", reason="Windows file paths tested")
    def test_win_normalize_drive(self, input_path, expected):
        assert pipenv.utils.normalize_drive(input_path) == expected

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "input_path, expected",
        [
            ("/usr/local/bin/python", "/usr/local/bin/python"),
            ("artifacts/file.zip", "artifacts/file.zip"),
            ("./artifacts/file.zip", "./artifacts/file.zip"),
            ("../otherproject/file.zip", "../otherproject/file.zip"),
        ],
    )
    @pytest.mark.skipif(os.name == "nt", reason="*nix file paths tested")
    def test_nix_normalize_drive(self, input_path, expected):
        assert pipenv.utils.normalize_drive(input_path) == expected

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "sources, expected_args",
        [
            (
                [{"url": "https://test.example.com/simple", "verify_ssl": True}],
                ["-i", "https://test.example.com/simple"],
            ),
            (
                [{"url": "https://test.example.com/simple", "verify_ssl": False}],
                [
                    "-i",
                    "https://test.example.com/simple",
                    "--trusted-host",
                    "test.example.com",
                ],
            ),
            (
                [
                    {"url": "https://pypi.org/simple"},
                    {"url": "https://custom.example.com/simple"},
                ],
                [
                    "-i",
                    "https://pypi.org/simple",
                    "--extra-index-url",
                    "https://custom.example.com/simple",
                ],
            ),
            (
                [
                    {"url": "https://pypi.org/simple"},
                    {"url": "https://custom.example.com/simple", "verify_ssl": False},
                ],
                [
                    "-i",
                    "https://pypi.org/simple",
                    "--extra-index-url",
                    "https://custom.example.com/simple",
                    "--trusted-host",
                    "custom.example.com",
                ],
            ),
            (
                [
                    {"url": "https://pypi.org/simple"},
                    {
                        "url": "https://user:password@custom.example.com/simple",
                        "verify_ssl": False,
                    },
                ],
                [
                    "-i",
                    "https://pypi.org/simple",
                    "--extra-index-url",
                    "https://user:password@custom.example.com/simple",
                    "--trusted-host",
                    "custom.example.com",
                ],
            ),
            (
                [
                    {"url": "https://pypi.org/simple"},
                    {"url": "https://user:password@custom.example.com/simple"},
                ],
                [
                    "-i",
                    "https://pypi.org/simple",
                    "--extra-index-url",
                    "https://user:password@custom.example.com/simple",
                ],
            ),
            (
                [
                    {
                        "url": "https://user:password@custom.example.com/simple",
                        "verify_ssl": False,
                    },
                ],
                [
                    "-i",
                    "https://user:password@custom.example.com/simple",
                    "--trusted-host",
                    "custom.example.com",
                ],
            ),
        ],
    )
    def test_prepare_pip_source_args(self, sources, expected_args):
        assert (
            pipenv.utils.prepare_pip_source_args(sources, pip_args=None)
            == expected_args
        )

    @pytest.mark.utils
    def test_parse_python_version(self):
        ver = pipenv.utils.parse_python_version("Python 3.6.5\n")
        assert ver == {"major": "3", "minor": "6", "micro": "5"}

    @pytest.mark.utils
    def test_parse_python_version_suffix(self):
        ver = pipenv.utils.parse_python_version("Python 3.6.5rc1\n")
        assert ver == {"major": "3", "minor": "6", "micro": "5"}

    @pytest.mark.utils
    def test_parse_python_version_270(self):
        ver = pipenv.utils.parse_python_version("Python 2.7\n")
        assert ver == {"major": "2", "minor": "7", "micro": "0"}

    @pytest.mark.utils
    def test_parse_python_version_270_garbage(self):
        ver = pipenv.utils.parse_python_version("Python 2.7+\n")
        assert ver == {"major": "2", "minor": "7", "micro": "0"}
