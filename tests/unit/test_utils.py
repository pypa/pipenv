import os
import sys
from unittest import mock

import pytest

from pipenv.exceptions import PipenvUsageError
from pipenv.utils import dependencies, indexes, internet, shell, toml, virtualenv

# Pipfile format <-> requirements.txt format.
DEP_PIP_PAIRS = [
    ({"django": ">1.10"}, {"django": "django>1.10"}),
    ({"Django": ">1.10"}, {"Django": "Django>1.10"}),
    (
        {"requests": {"extras": ["socks"], "version": ">1.10"}},
        {"requests": "requests[socks]>1.10"},
    ),
    (
        {"requests": {"extras": ["socks"], "version": "==1.10"}},
        {"requests": "requests[socks]==1.10"},
    ),
    (
        {
            "dataclasses-json": {
                "git": "https://github.com/lidatong/dataclasses-json.git",
                "ref": "v0.5.7",
                "editable": True,
            }
        },
        {
            "dataclasses-json": "dataclasses-json @ git+https://github.com/lidatong/dataclasses-json.git@v0.5.7"
        },
    ),
    (
        {
            "dataclasses-json": {
                "git": "https://github.com/lidatong/dataclasses-json.git",
                "ref": "v0.5.7",
            }
        },
        {
            "dataclasses-json": "dataclasses-json @ git+https://github.com/lidatong/dataclasses-json.git@v0.5.7"
        },
    ),
    (
        # Extras in url
        {
            "dparse": {
                "file": "https://github.com/oz123/dparse/archive/refs/heads/master.zip",
                "extras": ["pipenv"],
            }
        },
        {
            "dparse": "dparse[pipenv] @ https://github.com/oz123/dparse/archive/refs/heads/master.zip"
        },
    ),
    (
        {
            "requests": {
                "git": "https://github.com/requests/requests.git",
                "ref": "main",
                "extras": ["security"],
                "editable": False,
            }
        },
        {
            "requests": "requests[security] @ git+https://github.com/requests/requests.git@main"
        },
    ),
]


def mock_unpack(
    link,
    source_dir,
    download_dir,
    only_download=False,
    session=None,
    hashes=None,
    progress_bar="off",
):
    return


@pytest.mark.utils
@pytest.mark.parametrize("deps, expected", DEP_PIP_PAIRS)
@pytest.mark.needs_internet
def test_convert_deps_to_pip(deps, expected):
    assert dependencies.convert_deps_to_pip(deps) == expected


@pytest.mark.utils
@pytest.mark.needs_internet
def test_convert_deps_to_pip_star_specifier():
    deps = {"uvicorn": "*"}
    expected = {"uvicorn": "uvicorn"}
    assert dependencies.convert_deps_to_pip(deps) == expected


@pytest.mark.utils
@pytest.mark.needs_internet
def test_convert_deps_to_pip_extras_no_version():
    deps = {"uvicorn": {"extras": ["standard"], "version": "*"}}
    expected = {"uvicorn": "uvicorn[standard]"}
    assert dependencies.convert_deps_to_pip(deps) == expected


@pytest.mark.utils
@pytest.mark.parametrize(
    "deps, expected",
    [
        # Hash value should be passed into the result.
        (
            {
                "FooProject": {
                    "version": "==1.2",
                    "hashes": ["sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"],
                }
            },
            {
                "FooProject": "FooProject==1.2  --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
            },
        ),
        (
            {
                "FooProject": {
                    "version": "==1.2",
                    "extras": ["stuff"],
                    "hashes": ["sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"],
                }
            },
            {
                "FooProject": "FooProject[stuff]==1.2  --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
            },
        ),
        (
            {
                "uvicorn": {
                    "git": "https://github.com/encode/uvicorn.git",
                    "ref": "master",
                    "extras": ["standard"],
                }
            },
            {
                "uvicorn": "uvicorn[standard] @ git+https://github.com/encode/uvicorn.git@master"
            },
        ),
    ],
)
def test_convert_deps_to_pip_one_way(deps, expected):
    assert dependencies.convert_deps_to_pip(deps) == expected


@pytest.mark.utils
def test_convert_deps_to_pip_one_way_uvicorn():
    deps = {"uvicorn": {}}
    expected = {"uvicorn": "uvicorn"}
    assert dependencies.convert_deps_to_pip(deps) == expected


@pytest.mark.utils
def test_convert_deps_to_pip_vcs_with_markers():
    """Test that VCS dependencies with markers work correctly.

    PEP 508 format (remote VCS) should include markers inline.
    Legacy format (local file:// editable) cannot have inline markers.
    """
    # Remote VCS with markers - PEP 508 format supports inline markers
    deps = {
        "requests": {
            "git": "https://github.com/psf/requests.git",
            "ref": "v2.28.0",
            "markers": "python_version >= '3.6'",
        }
    }
    result = dependencies.convert_deps_to_pip(deps)
    assert "requests" in result
    assert "python_version >= '3.6'" in result["requests"]
    assert "git+https://github.com/psf/requests.git@v2.28.0" in result["requests"]

    # Local file:// editable VCS - legacy format cannot have inline markers
    # Markers will be preserved separately in the lockfile via pipfile_entries
    deps_local = {
        "six": {
            "git": "file:///tmp/git/six",
            "editable": True,
            "markers": "python_version >= '2.7'",
        }
    }
    result_local = dependencies.convert_deps_to_pip(deps_local)
    assert "six" in result_local
    # Legacy -e format should NOT have inline markers (they're handled separately)
    assert "python_version" not in result_local["six"]
    assert "-e git+file:///tmp/git/six#egg=six" == result_local["six"]


@pytest.mark.utils
@pytest.mark.parametrize(
    "deps, expected",
    [
        ({"uvicorn": {}}, {"uvicorn"}),
        ({"FooProject": {"path": ".", "editable": "true"}}, set()),
        ({"FooProject": {"version": "==1.2"}}, {"fooproject==1.2"}),
        ({"uvicorn": {"extras": ["standard"]}}, {"uvicorn"}),
        ({"uvicorn": {"extras": []}}, {"uvicorn"}),
        ({"extras": {}}, {"extras"}),
    ],
)
def test_get_constraints_from_deps(deps, expected):
    assert dependencies.get_constraints_from_deps(deps) == expected


@pytest.mark.parametrize(
    "line,result",
    [
        (
            "-i https://example.com/simple/",
            ("https://example.com/simple/", None, None, []),
        ),
        (
            "--extra-index-url=https://example.com/simple/",
            (None, "https://example.com/simple/", None, []),
        ),
        ("--trusted-host=example.com", (None, None, "example.com", [])),
        ("# -i https://example.com/simple/", (None, None, None, [])),
        ("requests # -i https://example.com/simple/", (None, None, None, ["requests"])),
    ],
)
@pytest.mark.utils
def test_parse_indexes(line, result):
    assert indexes.parse_indexes(line) == result


@pytest.mark.parametrize(
    "line",
    [
        "-i https://example.com/simple/ --extra-index-url=https://extra.com/simple/",
        "--extra-index-url https://example.com/simple/ --trusted-host=example.com",
        "requests -i https://example.com/simple/",
    ],
)
@pytest.mark.utils
def test_parse_indexes_individual_lines(line):
    with pytest.raises(ValueError):
        indexes.parse_indexes(line, strict=True)


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
        assert dependencies.is_required_version(version, specified_ver) is expected

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
        from pipenv.utils.requirementslib import is_vcs

        assert is_vcs(entry) is expected

    @pytest.mark.utils
    def test_python_version_from_bad_path(self):
        assert dependencies.python_version("/fake/path") is None

    @pytest.mark.utils
    def test_python_version_from_non_python(self):
        assert dependencies.python_version("/dev/null") is None

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "version_output, version",
        [
            ("Python 3.6.2", "3.6.2"),
            ("Python 3.6.2 :: Continuum Analytics, Inc.", "3.6.2"),
            ("Python 3.6.20 :: Continuum Analytics, Inc.", "3.6.20"),
            (
                "Python 3.5.3 (3f6eaa010fce78cc7973bdc1dfdb95970f08fed2, "
                "Jan 13 2018, 18:14:01)\n[PyPy 5.10.1 with GCC 4.2.1 Compatible Apple LLVM 9.0.0 (clang-900.0.39.2)]",
                "3.5.3",
            ),
        ],
    )
    def test_python_version_output_variants(self, monkeypatch, version_output, version):
        def mock_version(path):
            return version_output.split()[1]

        monkeypatch.setattr(
            "pipenv.vendor.pythonfinder.utils.get_python_version", mock_version
        )
        assert dependencies.python_version("some/path") == version

    @pytest.mark.utils
    def test_is_valid_url(self):
        url = "https://github.com/psf/requests.git"
        not_url = "something_else"
        assert internet.is_valid_url(url)
        assert internet.is_valid_url(not_url) is False

    @pytest.mark.utils
    def test_download_file(self, tmp_path):
        url = "https://example.com/test.md"
        output = tmp_path / "test_download.md"
        expected_content = b"# Test Content\n"

        # Mock the requests session to avoid external network calls
        mock_response = mock.MagicMock()
        mock_response.ok = True
        mock_response.content = expected_content

        mock_session = mock.MagicMock()
        mock_session.get.return_value = mock_response

        with mock.patch.object(internet, "get_requests_session", return_value=mock_session):
            internet.download_file(url, str(output))

        assert output.exists()
        assert output.read_bytes() == expected_content

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "line, expected",
        [
            ("python", True),
            ("python3.7", True),
            ("python2.7", True),
            ("python2", True),
            ("python3", True),
            ("pypy3", True),
            ("anaconda3-5.3.0", True),
            ("which", False),
            ("vim", False),
            ("miniconda", True),
            ("micropython", True),
            ("ironpython", True),
            ("jython3.5", True),
            ("2", True),
            ("2.7", True),
            ("3.7", True),
            ("3", True),
        ],
    )
    def test_is_python_command(self, line, expected):
        assert shell.is_python_command(line) == expected

    @pytest.mark.utils
    def test_new_line_end_of_toml_file(this):
        # toml file that needs clean up
        toml_data = """
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
        new_toml = toml.cleanup_toml(toml_data)
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
        assert shell.normalize_drive(input_path) == expected

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
        assert shell.normalize_drive(input_path) == expected

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
                [{"url": "https://test.example.com:12345/simple", "verify_ssl": False}],
                [
                    "-i",
                    "https://test.example.com:12345/simple",
                    "--trusted-host",
                    "test.example.com:12345",
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
                        "url": "https://custom.example.com:12345/simple",
                        "verify_ssl": False,
                    },
                ],
                [
                    "-i",
                    "https://pypi.org/simple",
                    "--extra-index-url",
                    "https://custom.example.com:12345/simple",
                    "--trusted-host",
                    "custom.example.com:12345",
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
        assert indexes.prepare_pip_source_args(sources, pip_args=None) == expected_args

    @pytest.mark.utils
    def test_invalid_prepare_pip_source_args(self):
        sources = [{}]
        with pytest.raises(PipenvUsageError):
            indexes.prepare_pip_source_args(sources, pip_args=None)

    @pytest.mark.utils
    def test_project_python_tries_python3_before_python_if_system_is_true(self):
        def mock_shutil_which(command, path=None):
            if command != "python3":
                return f"/usr/bin/{command}"
            return "/usr/local/bin/python3"

        with mock.patch("pipenv.utils.shell.shutil.which", wraps=mock_shutil_which):
            # Setting project to None as system=True doesn't use it
            project = None
            python = shell.project_python(project, system=True)

        assert python == "/usr/local/bin/python3"

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "val, expected",
        (
            (True, True),
            (False, False),
            ("true", True),
            ("1", True),
            ("off", False),
            ("0", False),
        ),
    )
    def test_env_to_bool(self, val, expected):
        actual = shell.env_to_bool(val)
        assert actual == expected

    @pytest.mark.utils
    def test_is_env_truthy_exists_true(self, monkeypatch):
        name = "ZZZ"
        monkeypatch.setenv(name, "1")
        assert shell.is_env_truthy(name) is True

    @pytest.mark.utils
    def test_is_env_truthy_exists_false(self, monkeypatch):
        name = "ZZZ"
        monkeypatch.setenv(name, "0")
        assert shell.is_env_truthy(name) is False

    @pytest.mark.utils
    def test_is_env_truthy_does_not_exisxt(self, monkeypatch):
        name = "ZZZ"
        monkeypatch.delenv(name, raising=False)
        assert shell.is_env_truthy(name) is False

    @pytest.mark.utils
    # substring search in version handles special-case of MSYS2 MinGW CPython
    # https://github.com/msys2/MINGW-packages/blob/master/mingw-w64-python/0017-sysconfig-treat-MINGW-builds-as-POSIX-builds.patch#L24
    @pytest.mark.skipif(os.name != "nt" or "GCC" in sys.version, reason="Windows test only")
    def test_virtualenv_scripts_dir_nt(self):
        """
        """
        assert str(virtualenv.virtualenv_scripts_dir('foobar')) == 'foobar\\Scripts'

    @pytest.mark.utils
    @pytest.mark.skipif(os.name == "nt" and "GCC" not in sys.version, reason="POSIX test only")
    def test_virtualenv_scripts_dir_posix(self):
        assert str(virtualenv.virtualenv_scripts_dir('foobar')) == 'foobar/bin'

    @pytest.mark.utils
    def test_find_package_name_from_directory_ignores_subdirectory_setup(self, tmp_path):
        """Test that find_package_name_from_directory ignores setup() calls in subdirectories.

        This tests the fix for issue #6409 where a test file containing setup(name='foo')
        in a subdirectory would incorrectly be used as the package name instead of the
        actual setup.py in the root directory.
        """
        # Create a package directory structure
        package_dir = tmp_path / "mypackage"
        package_dir.mkdir()

        # Create a proper setup.py in the root with a parseable name
        setup_py = package_dir / "setup.py"
        setup_py.write_text(
            "from setuptools import setup\nsetup(name='mypackage', version='1.0')\n"
        )

        # Create a tests subdirectory with a file that has a setup() call
        tests_dir = package_dir / "mypackage" / "tests"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_setup.py"
        test_file.write_text(
            "import unittest\n"
            "class TestNothing(unittest.TestCase):\n"
            "    def test_nada(self):\n"
            "        # This setup call should NOT be picked up as the package name\n"
            "        setup(name='wrongname')\n"
        )

        # The function should return 'mypackage' from the root setup.py
        # and NOT 'wrongname' from the test file
        result = dependencies.find_package_name_from_directory(str(package_dir))
        assert result == "mypackage"

    @pytest.mark.utils
    def test_find_package_name_from_directory_finds_egg_info_metadata(self, tmp_path):
        """Test that find_package_name_from_directory can find package name from .egg-info."""
        # Create a package directory structure
        package_dir = tmp_path / "mypackage"
        package_dir.mkdir()

        # Create a .egg-info directory with PKG-INFO
        egg_info_dir = package_dir / "mypackage.egg-info"
        egg_info_dir.mkdir()
        pkg_info = egg_info_dir / "PKG-INFO"
        pkg_info.write_text("Metadata-Version: 1.0\nName: mypackage\nVersion: 1.0\n")

        result = dependencies.find_package_name_from_directory(str(package_dir))
        assert result == "mypackage"


@pytest.mark.utils
class TestPipConfigurationParsing:
    """Test pip configuration parsing in Project class.

    These tests verify that pipenv correctly reads index-url from pip
    configuration files (pip.conf) after the pip 25.3 update which changed
    the Configuration.items() return format.
    """

    def test_pip_configuration_dictionary_format(self):
        """Test that pip Configuration._dictionary returns the expected format.

        In pip 25.3+, _dictionary is a dict of {filename: config_dict} pairs where
        config_dict contains the actual key-value pairs like {"global.index-url": "..."}.
        """
        from pipenv.patched.pip._internal.configuration import Configuration

        conf = Configuration(isolated=False, load_only=None)
        conf.load()

        # Verify the structure of _dictionary
        assert isinstance(conf._dictionary, dict), "_dictionary should be a dict"
        for filename, config_dict in conf._dictionary.items():
            assert isinstance(filename, str), "Key should be filename string"
            assert isinstance(config_dict, dict), "Value should be config dict"

    def test_project_parses_pip_conf_index_url(self, monkeypatch, tmp_path):
        """Test that Project correctly parses index-url from pip configuration.

        This is a regression test for issue #6478 where index-url in pip.conf
        was not being honored after the pip 25.3 update.
        """
        # Create a mock configuration that returns index-url
        mock_index_url = "https://my-private-pypi.example.com/simple"

        class MockConfiguration:
            def __init__(self, *args, **kwargs):
                pass

            def load(self):
                pass

            @property
            def _dictionary(self):
                # Simulate pip 25.3+ format: {filename: config_dict} dict
                return {
                    "/etc/pip.conf": {"global.index-url": mock_index_url},
                }

            def get_value(self, key):
                from pipenv.patched.pip._internal.exceptions import ConfigurationError

                raise ConfigurationError(f"No such key - {key}")

        # Patch the Configuration class
        monkeypatch.setattr(
            "pipenv.project.Configuration",
            MockConfiguration,
        )

        # Change to temp directory to avoid affecting real Pipfile
        original_dir = os.getcwd()
        os.chdir(tmp_path)
        try:
            from pipenv.project import Project

            project = Project(chdir=False)

            # Verify that the default_source was set from pip.conf
            assert project.default_source is not None
            assert project.default_source["url"] == mock_index_url
            assert "pip_conf_index_global" in project.default_source["name"]
        finally:
            os.chdir(original_dir)

    def test_project_parses_multiple_pip_conf_indexes(self, monkeypatch, tmp_path):
        """Test that Project correctly parses multiple index-urls from pip configuration."""
        primary_index = "https://primary-pypi.example.com/simple"
        extra_index = "https://extra-pypi.example.com/simple"

        class MockConfiguration:
            def __init__(self, *args, **kwargs):
                pass

            def load(self):
                pass

            @property
            def _dictionary(self):
                # Simulate multiple configuration files with different indexes
                return {
                    "/etc/pip.conf": {"global.index-url": primary_index},
                    "~/.pip/pip.conf": {"global.index-url": extra_index},
                }

            def get_value(self, key):
                from pipenv.patched.pip._internal.exceptions import ConfigurationError

                raise ConfigurationError(f"No such key - {key}")

        monkeypatch.setattr(
            "pipenv.project.Configuration",
            MockConfiguration,
        )

        original_dir = os.getcwd()
        os.chdir(tmp_path)
        try:
            from pipenv.project import Project

            project = Project(chdir=False)

            # Verify that at least one index was picked up
            assert project.default_source is not None
            assert project.default_source["url"] in [primary_index, extra_index]
        finally:
            os.chdir(original_dir)
