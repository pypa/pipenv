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



class TestEnsureProjectPythonVersionMismatch:
    """Tests for ensure_project detecting Python version mismatch (GitHub issue #6141).

    When --python is passed and an existing virtualenv uses a different Python
    version, ensure_project should call ensure_virtualenv so the virtualenv is
    recreated with the correct Python version.
    """

    def _make_project(self, monkeypatch):
        """Return a minimal mock project object."""
        project = mock.MagicMock()
        project.s.PIPENV_USE_SYSTEM = False
        project.s.PIPENV_YES = False
        project.virtualenv_exists = True
        project.pipfile_exists = True
        # required_python_version=None skips the version warning block
        project.required_python_version = None
        # python() must return a str for os.environ assignment
        project.python.return_value = "/usr/bin/python3"
        return project

    @pytest.mark.utils
    def test_python_version_mismatch_triggers_ensure_virtualenv(self, monkeypatch):
        """When --python 3.12 is given but the venv uses 3.10, ensure_virtualenv
        should be called so the venv is recreated."""
        project = self._make_project(monkeypatch)
        project._which.return_value = "/fake/venv/bin/python"

        monkeypatch.setattr(
            "pipenv.utils.project.python_version",
            lambda path: "3.10.5",
        )
        monkeypatch.setattr(
            "pipenv.utils.project.find_a_system_python",
            lambda x: None,
        )
        ensure_virtualenv_calls = []
        monkeypatch.setattr(
            "pipenv.utils.project.ensure_virtualenv",
            lambda *a, **kw: ensure_virtualenv_calls.append((a, kw)),
        )
        monkeypatch.setattr(
            "pipenv.utils.project.ensure_pipfile",
            lambda *a, **kw: None,
        )

        from pipenv.utils.project import ensure_project

        ensure_project(project, python="3.12", system=False)

        assert len(ensure_virtualenv_calls) == 1, (
            "ensure_virtualenv should be called when Python version mismatches"
        )

    @pytest.mark.utils
    def test_python_version_match_skips_ensure_virtualenv(self, monkeypatch):
        """When --python 3.10 is given and the venv already uses 3.10, ensure_virtualenv
        should NOT be called (no recreation needed)."""
        project = self._make_project(monkeypatch)
        project._which.return_value = "/fake/venv/bin/python"

        monkeypatch.setattr(
            "pipenv.utils.project.python_version",
            lambda path: "3.10.5",
        )
        monkeypatch.setattr(
            "pipenv.utils.project.find_a_system_python",
            lambda x: None,
        )
        ensure_virtualenv_calls = []
        monkeypatch.setattr(
            "pipenv.utils.project.ensure_virtualenv",
            lambda *a, **kw: ensure_virtualenv_calls.append((a, kw)),
        )
        monkeypatch.setattr(
            "pipenv.utils.project.ensure_pipfile",
            lambda *a, **kw: None,
        )

        from pipenv.utils.project import ensure_project

        ensure_project(project, python="3.10", system=False)

        assert len(ensure_virtualenv_calls) == 0, (
            "ensure_virtualenv should NOT be called when Python version already matches"
        )

    @pytest.mark.utils
    def test_no_python_arg_skips_version_check(self, monkeypatch):
        """When --python is not specified, no version-mismatch check should be done."""
        project = self._make_project(monkeypatch)

        ensure_virtualenv_calls = []
        monkeypatch.setattr(
            "pipenv.utils.project.ensure_virtualenv",
            lambda *a, **kw: ensure_virtualenv_calls.append((a, kw)),
        )
        monkeypatch.setattr(
            "pipenv.utils.project.ensure_pipfile",
            lambda *a, **kw: None,
        )

        from pipenv.utils.project import ensure_project

        ensure_project(project, python=None, system=False)

        assert len(ensure_virtualenv_calls) == 0, (
            "ensure_virtualenv should not be called when no --python is given and venv exists"
        )


class TestPythonVersionMatchesRequired:
    """Tests for _python_version_matches_required.

    Regression coverage for https://github.com/pypa/pipenv/issues/6514:
    the old `not in` substring check incorrectly accepted e.g. actual="3.13.11"
    when required="3.11", because "3.11" is a substring of "3.13.11".
    """

    @pytest.mark.parametrize(
        "actual, required, expected",
        [
            # --- python_version (major.minor) cases ---
            # Exact major.minor match with a patch suffix on actual
            ("3.11.0", "3.11", True),
            ("3.11.5", "3.11", True),
            # The substring-false-positive that triggered the bug report:
            # "3.11" is a substring of "3.13.11" but they are NOT compatible.
            ("3.13.11", "3.11", False),
            # Additional substring traps
            ("3.9.1", "3.9", True),
            ("3.9.10", "3.9", True),
            ("3.10.0", "3.1", False),   # "3.1" would match "3.1x.y" as substring
            ("3.13.1", "3.1", False),
            ("3.11.0", "3.1", False),
            # Major version mismatch
            ("2.7.18", "3.7", False),
            ("3.7.0", "2.7", False),
            # Same major, different minor
            ("3.10.0", "3.11", False),
            ("3.12.0", "3.11", False),
            # --- python_full_version (major.minor.patch) cases ---
            ("3.11.0", "3.11.0", True),
            ("3.11.0", "3.11.1", False),
            ("3.13.11", "3.11.0", False),
            ("3.11.10", "3.11.1", False),  # "3.11.1" is substring of "3.11.10"
            # --- Edge / guard cases ---
            ("", "3.11", False),
            ("3.11.0", "", False),
            ("", "", False),
        ],
    )
    def test_version_match(self, actual, required, expected):
        from pipenv.utils.project import _python_version_matches_required

        assert _python_version_matches_required(actual, required) is expected



class TestPipfileVenvInProject:
    """Tests for the [pipenv] venv_in_project Pipfile directive."""

    def _make_project_with_pipfile(self, tmp_path, monkeypatch, pipfile_content, env_var=None):
        """Create a Project mock with parsed_pipfile from the given content."""
        from pipenv.environments import Setting
        from pipenv.vendor import tomlkit

        if env_var is True:
            monkeypatch.setenv("PIPENV_VENV_IN_PROJECT", "1")
        elif env_var is False:
            monkeypatch.setenv("PIPENV_VENV_IN_PROJECT", "0")
        else:
            monkeypatch.delenv("PIPENV_VENV_IN_PROJECT", raising=False)

        parsed = tomlkit.parse(pipfile_content)
        project = mock.MagicMock()
        project.s = Setting()
        project.parsed_pipfile = parsed
        project.pipfile_exists = True
        project.project_directory = str(tmp_path)

        # Bind real methods to the mock
        from pipenv.project import Project

        project._pipfile_venv_in_project = Project._pipfile_venv_in_project.__get__(project)
        project.is_venv_in_project = Project.is_venv_in_project.__get__(project)

        return project

    @pytest.mark.utils
    def test_pipfile_venv_in_project_true(self, tmp_path, monkeypatch):
        """When [pipenv] venv_in_project = true in Pipfile, is_venv_in_project returns True."""
        pipfile = '[pipenv]\nvenv_in_project = true\n\n[packages]\n\n[dev-packages]\n'
        project = self._make_project_with_pipfile(tmp_path, monkeypatch, pipfile)
        assert project._pipfile_venv_in_project() is True
        assert project.is_venv_in_project() is True

    @pytest.mark.utils
    def test_pipfile_venv_in_project_false(self, tmp_path, monkeypatch):
        """When [pipenv] venv_in_project = false in Pipfile, is_venv_in_project returns False."""
        pipfile = '[pipenv]\nvenv_in_project = false\n\n[packages]\n\n[dev-packages]\n'
        project = self._make_project_with_pipfile(tmp_path, monkeypatch, pipfile)
        assert project._pipfile_venv_in_project() is False
        assert project.is_venv_in_project() is False

    @pytest.mark.utils
    def test_pipfile_venv_in_project_not_set(self, tmp_path, monkeypatch):
        """When [pipenv] section has no venv_in_project, _pipfile_venv_in_project returns None."""
        pipfile = '[packages]\n\n[dev-packages]\n'
        project = self._make_project_with_pipfile(tmp_path, monkeypatch, pipfile)
        assert project._pipfile_venv_in_project() is None

    @pytest.mark.utils
    def test_env_var_true_overrides_pipfile_false(self, tmp_path, monkeypatch):
        """Environment variable PIPENV_VENV_IN_PROJECT=1 overrides Pipfile venv_in_project=false."""
        pipfile = '[pipenv]\nvenv_in_project = false\n\n[packages]\n\n[dev-packages]\n'
        project = self._make_project_with_pipfile(tmp_path, monkeypatch, pipfile, env_var=True)
        assert project.is_venv_in_project() is True

    @pytest.mark.utils
    def test_env_var_false_overrides_pipfile_true(self, tmp_path, monkeypatch):
        """Environment variable PIPENV_VENV_IN_PROJECT=0 overrides Pipfile venv_in_project=true."""
        pipfile = '[pipenv]\nvenv_in_project = true\n\n[packages]\n\n[dev-packages]\n'
        project = self._make_project_with_pipfile(tmp_path, monkeypatch, pipfile, env_var=False)
        assert project.is_venv_in_project() is False



class TestPipfilePythonOverride:
    """Tests for _get_pipfile_python_override and _patched_marker_environment.

    See https://github.com/pypa/pipenv/issues/5908
    """

    def _make_project(self, monkeypatch, requires):
        """Create a mock project with the given [requires] section."""
        proj = mock.MagicMock()
        proj.pipfile_exists = True
        proj.parsed_pipfile = {"requires": requires} if requires else {}
        return proj

    @pytest.mark.utils
    def test_override_python_version_only(self, monkeypatch):
        """python_version = '3.11' should produce python_full_version = '3.11.0'."""
        from pipenv.utils.resolver import _get_pipfile_python_override

        proj = self._make_project(monkeypatch, {"python_version": "3.11"})
        override = _get_pipfile_python_override(proj)
        assert override is not None
        assert override["python_version"] == "3.11"
        assert override["python_full_version"] == "3.11.0"

    @pytest.mark.utils
    def test_override_python_full_version(self, monkeypatch):
        """python_full_version = '3.11.2' should be used as-is."""
        from pipenv.utils.resolver import _get_pipfile_python_override

        proj = self._make_project(monkeypatch, {"python_full_version": "3.11.2"})
        override = _get_pipfile_python_override(proj)
        assert override is not None
        assert override["python_version"] == "3.11"
        assert override["python_full_version"] == "3.11.2"

    @pytest.mark.utils
    def test_override_wildcard_returns_none(self, monkeypatch):
        """python_version = '*' should not produce an override."""
        from pipenv.utils.resolver import _get_pipfile_python_override

        proj = self._make_project(monkeypatch, {"python_version": "*"})
        override = _get_pipfile_python_override(proj)
        assert override is None

    @pytest.mark.utils
    def test_override_no_requires_returns_none(self, monkeypatch):
        """No [requires] section should not produce an override."""
        from pipenv.utils.resolver import _get_pipfile_python_override

        proj = self._make_project(monkeypatch, None)
        override = _get_pipfile_python_override(proj)
        assert override is None

    @pytest.mark.utils
    def test_override_no_pipfile_returns_none(self, monkeypatch):
        """No Pipfile should not produce an override."""
        from pipenv.utils.resolver import _get_pipfile_python_override

        proj = mock.MagicMock()
        proj.pipfile_exists = False
        override = _get_pipfile_python_override(proj)
        assert override is None

    @pytest.mark.utils
    def test_patched_marker_environment_overrides_python(self):
        """_patched_marker_environment should override python_version and
        python_full_version in default_environment."""
        import pipenv.patched.pip._vendor.packaging.markers as pip_markers
        from pipenv.utils.resolver import _patched_marker_environment

        override = {"python_version": "3.11", "python_full_version": "3.11.0"}
        with _patched_marker_environment(override):
            env = pip_markers.default_environment()
            assert env["python_version"] == "3.11"
            assert env["python_full_version"] == "3.11.0"

        # After exit, original values should be restored.
        env_after = pip_markers.default_environment()
        assert env_after["python_version"] != "3.11" or sys.version_info[:2] == (3, 11)

    @pytest.mark.utils
    def test_patched_marker_environment_none_is_noop(self):
        """_patched_marker_environment(None) should be a no-op."""
        import pipenv.patched.pip._vendor.packaging.markers as pip_markers
        from pipenv.utils.resolver import _patched_marker_environment

        env_before = pip_markers.default_environment()
        with _patched_marker_environment(None):
            env_during = pip_markers.default_environment()
        assert env_before["python_full_version"] == env_during["python_full_version"]

    @pytest.mark.utils
    def test_marker_evaluation_uses_override(self):
        """Markers should evaluate against the overridden Python version."""
        from pipenv.patched.pip._vendor.packaging.markers import Marker
        from pipenv.utils.resolver import _patched_marker_environment

        marker = Marker('python_full_version <= "3.11.2"')
        override = {"python_version": "3.11", "python_full_version": "3.11.0"}
        with _patched_marker_environment(override):
            # 3.11.0 <= 3.11.2 → True
            assert marker.evaluate() is True

        override_high = {"python_version": "3.11", "python_full_version": "3.11.5"}
        with _patched_marker_environment(override_high):
            # 3.11.5 <= 3.11.2 → False
            assert marker.evaluate() is False


class TestFormatRequirementForLockfile:
    """Tests for format_requirement_for_lockfile in pipenv.utils.locking."""

    def _make_install_req(self, name, link_url=None, specifier=None, extras=None, markers=None):
        """Create a mock InstallRequirement for testing."""
        from pipenv.patched.pip._internal.models.link import Link

        req = mock.MagicMock()
        req.name = name
        req.extras = extras or []
        req.markers = markers

        if link_url:
            req.link = Link(link_url)
        else:
            req.link = None

        if specifier:
            req.req = mock.MagicMock()
            req.req.specifier = specifier
            req.specifier = specifier
        else:
            req.req = mock.MagicMock()
            req.req.specifier = None
            req.specifier = None

        return req

    @pytest.mark.utils
    def test_https_direct_url_stored_in_lockfile(self):
        """Direct HTTPS URL dependencies (PEP 508) should have their URL stored in the lockfile."""
        from pipenv.utils.locking import format_requirement_for_lockfile

        url = "https://my-private-artifactory.com/api/pypi/repo/my-package/1.0.0/my_package-1.0.0-py3-none-any.whl"
        req = self._make_install_req("my-package", link_url=url, specifier="==1.0.0")

        name, entry = format_requirement_for_lockfile(
            req=req,
            markers_lookup={},
            index_lookup={},
            original_deps={},
            pipfile_entries={},
        )

        assert name == "my-package"
        assert entry.get("file") == url
        # version and index should be removed for direct URL deps
        assert "version" not in entry
        assert "index" not in entry

    @pytest.mark.utils
    def test_http_direct_url_stored_in_lockfile(self):
        """Direct HTTP URL dependencies should also be stored in the lockfile."""
        from pipenv.utils.locking import format_requirement_for_lockfile

        url = "http://internal-server.local/packages/my_package-2.0.0.tar.gz"
        req = self._make_install_req("my-package", link_url=url, specifier="==2.0.0")

        name, entry = format_requirement_for_lockfile(
            req=req,
            markers_lookup={},
            index_lookup={},
            original_deps={},
            pipfile_entries={},
        )

        assert name == "my-package"
        assert entry.get("file") == url
        assert "version" not in entry
        assert "index" not in entry

    @pytest.mark.utils
    def test_file_url_still_works(self):
        """Local file:// URLs declared as a file dependency in the Pipfile
        should continue to be stored in the lockfile.
        """
        from pipenv.utils.locking import format_requirement_for_lockfile

        url = "file:///tmp/my_package-1.0.0-py3-none-any.whl"
        req = self._make_install_req("my-package", link_url=url)

        name, entry = format_requirement_for_lockfile(
            req=req,
            markers_lookup={},
            index_lookup={},
            original_deps={},
            # Simulate a Pipfile that explicitly declares this as a file dep
            pipfile_entries={"my-package": {"file": url}},
        )

        assert name == "my-package"
        assert entry.get("file") == url

    @pytest.mark.utils
    def test_cached_wheel_not_stored_in_lockfile(self):
        """Index-resolved packages whose wheel pip cached locally must NOT have
        their cache path written as 'file' in the lockfile.  This was the root
        cause of broken Windows CI: a win32-only package (e.g. atomicwrites)
        locked on Linux was resolved via the local pip cache, and the cache path
        was committed into Pipfile.lock, breaking every machine without that
        exact cache directory.
        """
        from pipenv.utils.locking import format_requirement_for_lockfile

        cache_path = (
            "file:///home/user/.cache/pip/wheels/ab/cd/ef/"
            "atomicwrites-1.4.1-py3-none-any.whl"
        )
        req = self._make_install_req(
            "atomicwrites", link_url=cache_path, specifier="==1.4.1"
        )
        # Index-resolved packages have no req.req.url (no PEP 508 @ URL);
        # explicitly set to None so the PEP 508 file:// branch is not triggered.
        req.req.url = None

        name, entry = format_requirement_for_lockfile(
            req=req,
            markers_lookup={},
            index_lookup={},
            original_deps={},
            # No file/path in the Pipfile entry -> this is an index package
            pipfile_entries={},
        )

        assert name == "atomicwrites"
        assert "file" not in entry, (
            "Local pip cache paths must not bleed into the lockfile"
        )
        assert entry.get("version") == "==1.4.1"

    @pytest.mark.utils
    def test_transitive_pep508_file_url_stored_in_lockfile(self):
        """Transitive dependencies declared via PEP 508 ``pkg @ file:///...``
        in upstream package metadata must have their ``file`` URL recorded in
        the lockfile.

        Regression test for https://github.com/pypa/pipenv/issues/6521.

        When a top-level package depends on ``local-child-pkg @
        file:///vendor/local-child-pkg``, pipenv used to write an empty entry
        ``"local-child-pkg": {}`` because the package was not in the Pipfile
        and the file:// path was silently dropped.  On the next ``pipenv
        install`` pip then tried to satisfy ``local-child-pkg`` from PyPI and
        failed with "No matching distribution found".
        """
        from pipenv.utils.locking import format_requirement_for_lockfile

        file_url = "file:///home/user/my-project/vendor/local-child-pkg"
        req = self._make_install_req("local-child-pkg", link_url=file_url)
        # Simulate a PEP 508 direct URL reference: req.req.url is set to the
        # file:// URL (as pip sets it when the requirement is ``pkg @ file://...``).
        req.req.url = file_url

        name, entry = format_requirement_for_lockfile(
            req=req,
            markers_lookup={},
            index_lookup={},
            original_deps={},
            # Transitive dep: not in the Pipfile, so pipfile_entries is empty.
            pipfile_entries={},
        )

        assert name == "local-child-pkg"
        assert entry.get("file") == file_url, (
            "PEP 508 file:// transitive deps must have their URL recorded in the lockfile"
        )
        # version and index should be removed (same as https:// direct URL deps)
        assert "version" not in entry
        assert "index" not in entry

    @pytest.mark.utils
    def test_regular_pypi_package_no_file_key(self):
        """Regular PyPI packages (no link) should not have a 'file' key."""
        from pipenv.utils.locking import format_requirement_for_lockfile

        req = self._make_install_req("requests", specifier="==2.28.1")

        name, entry = format_requirement_for_lockfile(
            req=req,
            markers_lookup={},
            index_lookup={},
            original_deps={},
            pipfile_entries={},
        )

        assert name == "requests"
        assert "file" not in entry
        assert entry.get("version") == "==2.28.1"

    @pytest.mark.utils
    def test_https_url_with_hash_fragment(self):
        """HTTPS URLs with hash fragments (common in PEP 508) should be stored correctly."""
        from pipenv.utils.locking import format_requirement_for_lockfile

        url = "https://private-repo.com/packages/my_dep-13.6.0-py3-none-any.whl#sha256=abcdef1234567890"
        req = self._make_install_req("my-dep", link_url=url)

        name, entry = format_requirement_for_lockfile(
            req=req,
            markers_lookup={},
            index_lookup={},
            original_deps={},
            pipfile_entries={},
        )

        assert name == "my-dep"
        assert entry.get("file") == url

    @pytest.mark.utils
    def test_https_url_removes_index_from_lookup(self):
        """When a direct URL is used, any index from index_lookup should be overridden."""
        from pipenv.utils.locking import format_requirement_for_lockfile

        url = "https://private-repo.com/packages/my_dep-1.0.0.whl"
        req = self._make_install_req("my-dep", link_url=url, specifier="==1.0.0")

        name, entry = format_requirement_for_lockfile(
            req=req,
            markers_lookup={},
            index_lookup={"my-dep": "my-private-index"},
            original_deps={},
            pipfile_entries={},
        )

        assert entry.get("file") == url
        # The direct URL handling removes index, but then index_lookup re-adds it.
        # This is acceptable because the file key takes precedence during install.
        # The important thing is that the file URL IS stored.
        assert "file" in entry


class TestIsDownloadStatusLine:
    """Tests for _is_download_status_line (issue #5718).

    pip emits download progress lines to stderr during dependency resolution.
    These should always be shown to users so they know pipenv isn't frozen
    while a large package is being fetched.
    """

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "line",
        [
            "  Downloading torch-2.0.0-cp311-cp311-linux_x86_64.whl (726.8 MB)",
            "Downloading torch-2.0.0-cp311-cp311-linux_x86_64.whl (726.8 MB)",
            "  Downloading requests-2.31.0-py3-none-any.whl (62.6 kB)",
            "  Downloading numpy-1.25.0-cp311-cp311-manylinux_2_17_x86_64.whl (17.3 MB)",
            "  Downloading model-2.0.tar.gz (1.2 GB)",
            "  Downloading small_pkg-0.1.0-py3-none-any.whl (512 KB)",
        ],
    )
    def test_recognises_download_lines(self, line):
        from pipenv.utils.resolver import _is_download_status_line

        assert _is_download_status_line(line) is True

    @pytest.mark.utils
    @pytest.mark.parametrize(
        "line",
        [
            # Resolution / collection messages – not downloads
            "Collecting torch",
            "  Using cached torch-2.0.0-cp311-cp311-linux_x86_64.whl (726.8 MB)",
            "Downloading",  # bare keyword, no size
            "Downloading torch-2.0.0.whl",  # no parenthesised size
            "Successfully installed torch-2.0.0",
            "Building wheels for collected packages: torch",
            "",
            "   ",
        ],
    )
    def test_ignores_non_download_lines(self, line):
        from pipenv.utils.resolver import _is_download_status_line

        assert _is_download_status_line(line) is False


# ---------------------------------------------------------------------------
# Tests for create_pipfile Python-version consistency (GitHub issue #6571)
# ---------------------------------------------------------------------------


class TestCreatePipfileVersionConsistency:
    """Regression tests for GH-6571.

    When ``pipenv install`` creates both the virtualenv and the Pipfile in the
    same invocation, ``create_pipfile`` must record the Python version that is
    actually *inside the virtualenv*, not the version discovered by scanning
    PATH (which may differ when pyenv, asdf, or similar managers are in use).

    The bug was that:
    1. ``ensure_virtualenv`` called ``find_all_python_versions()`` and picked
       the highest installed interpreter (e.g. CPython 3.14).
    2. ``create_pipfile`` subsequently called ``self.which("python")`` which
       resolved ``python`` via PATH / pyenv shims and found the pyenv *global*
       interpreter (e.g. CPython 3.13).
    3. The Pipfile was written with ``python_version = "3.13"`` while the
       virtualenv contained CPython 3.14 — every subsequent pipenv invocation
       printed a spurious "Pipfile requires 3.13 but you are using 3.14" warning.

    The fix: when the virtualenv already exists, ``create_pipfile`` uses
    ``self._which("python")`` (looks directly in the venv's scripts dir)
    instead of ``self.which("python")`` (searches PATH globally).
    """

    @staticmethod
    def _make_project(tmp_path, venv_python_version, global_python_version):
        """Return a (mock_project, fake_python_version_fn) pair.

        mock_project has:
        * ``_which("python")`` → venv interpreter path
        * ``which("python")`` → PATH/pyenv-shim interpreter path
        * ``virtualenv_exists`` set to True by default (tests can override)

        fake_python_version_fn maps each path to its version string.
        """
        from unittest.mock import MagicMock

        venv_python_path = str(tmp_path / "bin" / "python")
        global_python_path = f"/usr/bin/python{global_python_version}"

        settings = MagicMock()
        settings.PIPENV_DEFAULT_PYTHON_VERSION = None

        project = MagicMock()
        project.s = settings
        project._which.return_value = venv_python_path
        project.which.return_value = global_python_path
        project.virtualenv_exists = True
        project.default_source = {
            "url": "https://pypi.org/simple",
            "verify_ssl": True,
            "name": "pypi",
        }
        project.write_toml = MagicMock()

        def _fake_python_version(path):
            if path == venv_python_path:
                return venv_python_version
            if path == global_python_path:
                return global_python_version
            return None

        return project, _fake_python_version

    def _call_create_pipfile(self, project, python, fake_pv):
        """Invoke the real create_pipfile on *project* with all side-effects patched."""
        from unittest.mock import MagicMock, patch

        from pipenv.project import Project

        # InstallCommand instantiation pulls in pip internals we don't want in unit tests.
        fake_cmd = MagicMock()
        fake_cmd.cmd_opts.get_option.return_value.default = []

        written_data = {}

        def capture_write_toml(data):
            written_data.update(data)

        project.write_toml.side_effect = capture_write_toml

        with patch("pipenv.project.python_version", side_effect=fake_pv), \
             patch("pipenv.project.InstallCommand", return_value=fake_cmd):
            Project.create_pipfile(project, python=python)

        return written_data

    def test_uses_venv_python_when_venv_exists(self, tmp_path):
        """create_pipfile must record the venv's Python, not the PATH one."""
        venv_ver = "3.14.3"
        global_ver = "3.13.12"

        project, fake_pv = self._make_project(tmp_path, venv_ver, global_ver)
        written_data = self._call_create_pipfile(project, python=None, fake_pv=fake_pv)

        requires = written_data.get("requires", {})
        assert requires.get("python_version") == "3.14", (
            f"Expected '3.14' (venv) but got {requires.get('python_version')!r}; "
            "create_pipfile is resolving the PATH Python instead of the venv's interpreter."
        )

    def test_no_venv_falls_back_to_which(self, tmp_path):
        """When no venv exists, which('python') is used as the pre-fix fallback."""
        project, fake_pv = self._make_project(tmp_path, "3.14.3", "3.13.12")
        project.virtualenv_exists = False  # No venv yet.

        written_data = self._call_create_pipfile(project, python=None, fake_pv=fake_pv)

        requires = written_data.get("requires", {})
        # Falls back to which() → global/PATH Python.
        assert requires.get("python_version") == "3.13", (
            f"Expected '3.13' (PATH fallback) but got {requires.get('python_version')!r}"
        )

    def test_explicit_python_argument_always_wins(self, tmp_path):
        """An explicit python= path overrides both venv and PATH discovery."""
        explicit_ver = "3.12.10"
        explicit_path = f"/opt/python{explicit_ver}/bin/python"

        project, _ = self._make_project(tmp_path, "3.14.3", "3.13.12")

        def fake_pv(path):
            return explicit_ver if path == explicit_path else None

        written_data = self._call_create_pipfile(project, python=explicit_path, fake_pv=fake_pv)

        requires = written_data.get("requires", {})
        assert requires.get("python_version") == "3.12"
        # python_full_version is only written when an explicit path is provided.
        assert requires.get("python_full_version") == "3.12.10"


class TestAddPipfileEntryPreservesVersionSpecifiers:
    """Regression tests for https://github.com/pypa/pipenv/issues/5865.

    Installing a failing/nonexistent package must not strip version specifiers
    from unrelated entries already present in the Pipfile.
    """

    @pytest.mark.utils
    def test_convert_toml_preserves_inline_table_version(self):
        """convert_toml_outline_tables must not drop the 'version' key from an
        existing inline-table package entry when rewriting the Pipfile.
        """
        import textwrap
        from unittest.mock import MagicMock

        from pipenv.utils.toml import convert_toml_outline_tables
        from pipenv.vendor import tomlkit

        pipfile_content = textwrap.dedent("""\
            [[source]]
            url = "https://pypi.org/simple"
            verify_ssl = true
            name = "pypi"

            [packages]
            pydantic = {extras = ["email"], version = "<2.0"}

            [dev-packages]

            [requires]
            python_version = "3.11"
        """)

        parsed = tomlkit.parse(pipfile_content)
        # Simulate adding a new dev package (as add_pipfile_entry_to_pipfile does)
        parsed["dev-packages"]["some-random-package"] = "*"

        project = MagicMock()
        project.get_package_categories.return_value = ["packages", "dev-packages"]

        result = convert_toml_outline_tables(parsed, project)

        pydantic_entry = result.get("packages", {}).get("pydantic")
        assert pydantic_entry is not None, "pydantic entry was removed entirely"
        assert "version" in pydantic_entry, (
            "version key was stripped from pydantic entry after convert_toml_outline_tables"
        )
        assert str(pydantic_entry["version"]) == "<2.0", (
            f"version specifier corrupted: expected '<2.0', got {pydantic_entry['version']!r}"
        )
        assert "extras" in pydantic_entry, "extras key was stripped from pydantic entry"

    @pytest.mark.utils
    def test_add_dev_package_preserves_packages_version_specifier(self, tmp_path, monkeypatch):
        """add_pipfile_entry_to_pipfile must not corrupt version specifiers in
        unrelated sections (e.g. adding to [dev-packages] must leave [packages] intact).
        """
        import textwrap

        from pipenv.project import Project
        from pipenv.vendor import tomlkit

        pipfile_content = textwrap.dedent("""\
            [[source]]
            url = "https://pypi.org/simple"
            verify_ssl = true
            name = "pypi"

            [packages]
            pydantic = {extras = ["email"], version = "<2.0"}

            [dev-packages]

            [requires]
            python_version = "3.11"
        """)

        pipfile_path = tmp_path / "Pipfile"
        pipfile_path.write_text(pipfile_content)

        monkeypatch.chdir(tmp_path)

        project = Project(chdir=False)

        # Add an unrelated dev package
        project.add_pipfile_entry_to_pipfile(
            "some-random-package",
            "some-random-package",
            "*",
            category="dev-packages",
        )

        # Read back what was written
        result = tomlkit.parse(pipfile_path.read_text())
        pydantic_entry = result.get("packages", {}).get("pydantic")

        assert pydantic_entry is not None, "pydantic entry was removed from [packages]"
        assert "version" in pydantic_entry, (
            "version key '<2.0' was stripped from pydantic when adding an unrelated dev package "
            "(regression of https://github.com/pypa/pipenv/issues/5865)"
        )
        assert str(pydantic_entry["version"]) == "<2.0", (
            f"version specifier corrupted: expected '<2.0', got {pydantic_entry['version']!r}"
        )
        assert "extras" in pydantic_entry, "extras key was stripped from pydantic entry"


class TestCreateBuiltinVenvCmd:
    """Tests for _create_builtin_venv_cmd (issue #5601).

    When virtualenv fails for an alternative interpreter (e.g. RustPython),
    pipenv should fall back to the interpreter's own built-in ``venv`` module.
    The command produced must invoke the *target* interpreter, not sys.executable.
    """

    def _make_project(self, tmp_path):
        """Return a minimal project-like object sufficient for cmd-building tests."""
        project = mock.MagicMock()
        project.name = "myproject"
        project.s.PIPENV_VIRTUALENV_CREATOR = ""
        project.s.PIPENV_VIRTUALENV_COPIES = False
        venv_dest = str(tmp_path / "myproject-venv")
        project.get_location_for_virtualenv.return_value = venv_dest
        return project, venv_dest

    @pytest.mark.utils
    def test_uses_target_interpreter_not_sys_executable(self, tmp_path):
        """The first element of the command must be the *target* python, not sys.executable."""
        from pipenv.utils.virtualenv import _create_builtin_venv_cmd

        project, _ = self._make_project(tmp_path)
        python = "/home/user/rustpython/target/release/rustpython"
        cmd = _create_builtin_venv_cmd(project, python)
        assert cmd[0] == python, (
            f"Expected target interpreter {python!r} as first arg, got {cmd[0]!r}"
        )

    @pytest.mark.utils
    def test_invokes_venv_module(self, tmp_path):
        """The command must use ``-m venv``, not ``-m virtualenv``."""
        from pipenv.utils.virtualenv import _create_builtin_venv_cmd

        project, _ = self._make_project(tmp_path)
        cmd = _create_builtin_venv_cmd(project, "/usr/bin/python3")
        assert "-m" in cmd
        assert "venv" in cmd
        assert "virtualenv" not in cmd

    @pytest.mark.utils
    def test_includes_prompt(self, tmp_path):
        """The --prompt flag should be set to the project name."""
        from pipenv.utils.virtualenv import _create_builtin_venv_cmd

        project, _ = self._make_project(tmp_path)
        cmd = _create_builtin_venv_cmd(project, "/usr/bin/python3")
        assert any("--prompt=myproject" == arg for arg in cmd)

    @pytest.mark.utils
    def test_destination_path_appended(self, tmp_path):
        """The virtualenv destination directory must be the last argument."""
        from pipenv.utils.virtualenv import _create_builtin_venv_cmd

        project, venv_dest = self._make_project(tmp_path)
        cmd = _create_builtin_venv_cmd(project, "/usr/bin/python3")
        assert cmd[-1] == venv_dest

    @pytest.mark.utils
    def test_system_site_packages_flag(self, tmp_path):
        """--system-site-packages is included only when site_packages=True."""
        from pipenv.utils.virtualenv import _create_builtin_venv_cmd

        project, _ = self._make_project(tmp_path)
        cmd_no = _create_builtin_venv_cmd(project, "/usr/bin/python3", site_packages=False)
        cmd_yes = _create_builtin_venv_cmd(project, "/usr/bin/python3", site_packages=True)
        assert "--system-site-packages" not in cmd_no
        assert "--system-site-packages" in cmd_yes


class TestDoCreateVirtualenvFallback:
    """Tests for the venv fallback logic in do_create_virtualenv (issue #5601).

    When ``virtualenv`` exits with a non-zero code and the user has not set
    PIPENV_VIRTUALENV_CREATOR, pipenv should automatically retry using the
    target interpreter's built-in ``venv`` module.
    """

    def _make_project(self, tmp_path):
        project = mock.MagicMock()
        project.name = "myproject"
        project.pipfile_location = str(tmp_path / "Pipfile")
        project.virtualenv_location = str(tmp_path / "venv")
        project.project_directory = str(tmp_path)
        project.get_location_for_virtualenv.return_value = str(tmp_path / "venv")
        project.pipfile_sources.return_value = []
        project.parsed_pipfile = {}
        project.s.PIPENV_SPINNER = "dots"
        project.s.PIPENV_VIRTUALENV_CREATOR = ""
        project.s.PIPENV_VIRTUALENV_COPIES = False
        project.s.is_verbose.return_value = False
        # Create the virtualenv dir so .project file write succeeds
        (tmp_path / "venv").mkdir(parents=True, exist_ok=True)
        return project

    @pytest.mark.utils
    def test_fallback_to_builtin_venv_on_virtualenv_failure(self, tmp_path, monkeypatch):
        """When virtualenv fails, do_create_virtualenv retries with python -m venv."""
        from pipenv.utils import virtualenv as venv_mod

        project = self._make_project(tmp_path)

        fail_result = mock.MagicMock()
        fail_result.returncode = 1
        fail_result.stdout = ""
        fail_result.stderr = "TypeError: 'NoneType' object is not callable"

        success_result = mock.MagicMock()
        success_result.returncode = 0
        success_result.stdout = ""
        success_result.stderr = ""

        call_count = {"n": 0}

        def fake_subprocess_run(cmd, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return fail_result  # virtualenv attempt
            return success_result  # venv fallback

        monkeypatch.setattr(venv_mod, "subprocess_run", fake_subprocess_run)
        monkeypatch.setattr(venv_mod, "create_tracked_tempdir", lambda: str(tmp_path))
        monkeypatch.setattr(venv_mod, "python_version", lambda p: "3.10.0")
        monkeypatch.setattr(venv_mod, "do_where", lambda *a, **kw: None)
        # Environment is imported lazily inside do_create_virtualenv; patch at source.
        monkeypatch.setattr("pipenv.environment.Environment.__init__", lambda *a, **kw: None)

        # Should not raise — the fallback succeeded
        venv_mod.do_create_virtualenv(project, python="/usr/bin/python3")
        assert call_count["n"] == 2, "Expected two subprocess calls (virtualenv + venv fallback)"

    @pytest.mark.utils
    def test_raises_if_both_virtualenv_and_venv_fail(self, tmp_path, monkeypatch):
        """If both virtualenv and the venv fallback fail, VirtualenvCreationException is raised."""
        from pipenv.exceptions import VirtualenvCreationException
        from pipenv.utils import virtualenv as venv_mod

        project = self._make_project(tmp_path)

        bad_result = mock.MagicMock()
        bad_result.returncode = 1
        bad_result.stdout = ""
        bad_result.stderr = "something went wrong"

        monkeypatch.setattr(venv_mod, "subprocess_run", lambda cmd, **kw: bad_result)
        monkeypatch.setattr(venv_mod, "create_tracked_tempdir", lambda: str(tmp_path))
        monkeypatch.setattr(venv_mod, "python_version", lambda p: "3.10.0")

        with pytest.raises(VirtualenvCreationException):
            venv_mod.do_create_virtualenv(project, python="/usr/bin/python3")

    @pytest.mark.utils
    def test_no_fallback_when_creator_explicitly_set(self, tmp_path, monkeypatch):
        """When PIPENV_VIRTUALENV_CREATOR is set, the fallback must NOT be attempted."""
        from pipenv.exceptions import VirtualenvCreationException
        from pipenv.utils import virtualenv as venv_mod

        project = self._make_project(tmp_path)
        project.s.PIPENV_VIRTUALENV_CREATOR = "builtin"  # user chose explicitly

        bad_result = mock.MagicMock()
        bad_result.returncode = 1
        bad_result.stdout = ""
        bad_result.stderr = "virtualenv error"

        call_count = {"n": 0}

        def fake_subprocess_run(cmd, **kwargs):
            call_count["n"] += 1
            return bad_result

        monkeypatch.setattr(venv_mod, "subprocess_run", fake_subprocess_run)
        monkeypatch.setattr(venv_mod, "create_tracked_tempdir", lambda: str(tmp_path))
        monkeypatch.setattr(venv_mod, "python_version", lambda p: "3.10.0")

        with pytest.raises(VirtualenvCreationException):
            venv_mod.do_create_virtualenv(project, python="/usr/bin/python3")

        assert call_count["n"] == 1, "Fallback must not be attempted when creator is explicit"
