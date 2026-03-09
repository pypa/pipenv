from unittest import mock

import pytest


class TestParseRequirementsLines:
    """Tests for pipenv.uv.parse_requirements_lines."""

    def test_basic_package(self):
        from pipenv.uv import parse_requirements_lines

        lines = ["requests==2.31.0"]
        packages, index, _ = parse_requirements_lines(lines)
        assert "requests" in packages
        assert packages["requests"]["version"] == "==2.31.0"
        assert index == ""

    def test_package_with_hashes(self):
        from pipenv.uv import parse_requirements_lines

        lines = [
            "requests==2.31.0 \\",
            "    --hash=sha256:abc123 \\",
            "    --hash=sha256:def456",
        ]
        packages, index, _ = parse_requirements_lines(lines)
        assert "requests" in packages
        assert packages["requests"]["version"] == "==2.31.0"
        assert packages["requests"]["hashes"] == [
            "sha256:abc123",
            "sha256:def456",
        ]

    def test_package_with_extras(self):
        from pipenv.uv import parse_requirements_lines

        lines = ["requests[socks]==2.31.0"]
        packages, index, _ = parse_requirements_lines(lines)
        assert "requests" in packages
        assert packages["requests"]["extras"] == ["socks"]
        assert packages["requests"]["version"] == "==2.31.0"

    def test_package_with_markers(self):
        from pipenv.uv import parse_requirements_lines

        lines = ['requests==2.31.0 ; python_version >= "3.8"']
        packages, index, _ = parse_requirements_lines(lines)
        assert "requests" in packages
        assert packages["requests"]["markers"] == 'python_version >= "3.8"'

    def test_index_url_parsed(self):
        from pipenv.uv import parse_requirements_lines

        lines = [
            "-i https://pypi.org/simple",
            "requests==2.31.0",
        ]
        packages, index, _ = parse_requirements_lines(lines)
        assert index == "https://pypi.org/simple"
        assert "requests" in packages

    def test_comments_and_blanks_skipped(self):
        from pipenv.uv import parse_requirements_lines

        lines = [
            "# This is a comment",
            "",
            "   ",
            "requests==2.31.0",
        ]
        packages, index, _ = parse_requirements_lines(lines)
        assert len(packages) == 1
        assert "requests" in packages

    def test_git_package(self):
        from pipenv.uv import parse_requirements_lines

        lines = ["mypackage@git+https://github.com/user/repo.git@v1.0.0"]
        packages, index, _ = parse_requirements_lines(lines)
        assert "mypackage" in packages
        assert packages["mypackage"]["git"] == "https://github.com/user/repo.git"
        assert packages["mypackage"]["ref"] == "v1.0.0"

    def test_git_package_uv_format(self):
        """Test git package in 'name @ git+URL@ref' format output by uv pip compile."""
        from pipenv.uv import parse_requirements_lines

        lines = ["gunicorn @ git+https://github.com/benoitc/gunicorn@411986d6191114dd1d1bbb9c72c948dbf0ef0425"]
        packages, index, _ = parse_requirements_lines(lines)
        assert "gunicorn" in packages
        assert packages["gunicorn"]["git"] == "https://github.com/benoitc/gunicorn"
        assert packages["gunicorn"]["ref"] == "411986d6191114dd1d1bbb9c72c948dbf0ef0425"

    def test_editable_package(self, tmp_path):
        from pipenv.uv import parse_requirements_lines

        lines = [f"-e {tmp_path}"]
        packages, index, _ = parse_requirements_lines(lines)
        assert tmp_path.name in packages
        assert packages[tmp_path.name]["editable"] is True

    def test_multiple_packages(self):
        from pipenv.uv import parse_requirements_lines

        lines = [
            "requests==2.31.0",
            "flask==3.0.0",
            "click==8.1.7",
        ]
        packages, index, _ = parse_requirements_lines(lines)
        assert len(packages) == 3
        assert all(name in packages for name in ("requests", "flask", "click"))

    def test_direct_url_package(self):
        from pipenv.uv import parse_requirements_lines

        lines = [
            "dataclasses-json @ https://files.pythonhosted.org/packages/85/94/1b30216f84c48b9e0646833f6f2dd75f1169cc04dc45c48fe39e644c89d5/dataclasses-json-0.5.7.tar.gz \\",
            "    --hash=sha256:c2c11bc8214fbf709ffc369d11446ff6945254a7f09128154a7620613d8fda90",
        ]
        packages, index, _ = parse_requirements_lines(lines)
        assert "dataclasses-json" in packages
        pkg = packages["dataclasses-json"]
        assert "file" in pkg
        assert (
            pkg["file"]
            == "https://files.pythonhosted.org/packages/85/94/1b30216f84c48b9e0646833f6f2dd75f1169cc04dc45c48fe39e644c89d5/dataclasses-json-0.5.7.tar.gz"
        )
        assert pkg["hashes"] == ["sha256:c2c11bc8214fbf709ffc369d11446ff6945254a7f09128154a7620613d8fda90"]
        assert "version" not in pkg

    def test_direct_url_package_with_extras(self):
        from pipenv.uv import parse_requirements_lines

        lines = [
            "mypackage[extra1,extra2] @ https://example.com/mypackage-1.0.tar.gz",
        ]
        packages, index, _ = parse_requirements_lines(lines)
        assert "mypackage" in packages
        pkg = packages["mypackage"]
        assert pkg["file"] == "https://example.com/mypackage-1.0.tar.gz"
        assert pkg["extras"] == ["extra1", "extra2"]
        assert "version" not in pkg

    def test_direct_url_package_with_markers(self):
        from pipenv.uv import parse_requirements_lines

        lines = [
            'mypackage @ https://example.com/mypackage-1.0.tar.gz ; python_version >= "3.8"',
        ]
        packages, index, _ = parse_requirements_lines(lines)
        assert "mypackage" in packages
        pkg = packages["mypackage"]
        assert pkg["file"] == "https://example.com/mypackage-1.0.tar.gz"
        assert pkg["markers"] == 'python_version >= "3.8"'
        assert "version" not in pkg

    def test_empty_input(self):
        from pipenv.uv import parse_requirements_lines

        packages, index, _ = parse_requirements_lines([])
        assert packages == {}
        assert index == ""

    def test_index_annotation_parsing(self):
        """Test that ``# from <url>`` annotations are captured per-package."""
        from pipenv.uv import parse_requirements_lines

        lines = [
            "certifi==2026.2.25 \\",
            "    --hash=sha256:abc123",
            "    # from https://pypi.org/simple",
            "six==1.17.0 \\",
            "    --hash=sha256:def456",
            "    # from http://localhost:8080/simple",
        ]
        packages, _index, annotations = parse_requirements_lines(lines)
        assert "certifi" in packages
        assert "six" in packages
        assert annotations == {
            "certifi": "https://pypi.org/simple",
            "six": "http://localhost:8080/simple",
        }

    def test_index_annotation_empty_when_not_present(self):
        """Index annotations dict is empty when no ``# from`` comments."""
        from pipenv.uv import parse_requirements_lines

        lines = ["requests==2.31.0"]
        packages, _index, annotations = parse_requirements_lines(lines)
        assert "requests" in packages
        assert annotations == {}

    def test_index_annotation_mixed(self):
        """Only packages with ``# from`` annotations get entries."""
        from pipenv.uv import parse_requirements_lines

        lines = [
            "certifi==2026.2.25 \\",
            "    --hash=sha256:abc123",
            "    # from https://pypi.org/simple",
            "requests==2.31.0",
        ]
        packages, _index, annotations = parse_requirements_lines(lines)
        assert len(packages) == 2
        assert annotations == {"certifi": "https://pypi.org/simple"}


class TestFindUvBin:
    """Tests for pipenv.uv.find_uv_bin."""

    def test_finds_via_uv_package(self):
        from pipenv.uv import find_uv_bin

        with mock.patch("pipenv.uv.find_uv_bin.__module__", "pipenv.uv"):
            # Mock the uv package import path
            fake_module = mock.MagicMock()
            fake_module.find_uv_bin.return_value = "/fake/path/uv"
            with mock.patch.dict(
                "sys.modules",
                {"uv": mock.MagicMock(), "uv._find_uv": fake_module},
            ):
                result = find_uv_bin()
                assert result == "/fake/path/uv"

    def test_falls_back_to_path(self):
        from pipenv.uv import find_uv_bin

        # Remove uv package from sys.modules to force ImportError
        with mock.patch.dict("sys.modules", {"uv": None, "uv._find_uv": None}):
            with mock.patch("shutil.which", return_value="/usr/local/bin/uv"):
                result = find_uv_bin()
                assert result == "/usr/local/bin/uv"

    def test_raises_when_not_found(self):
        from pipenv.uv import find_uv_bin

        with mock.patch.dict("sys.modules", {"uv": None, "uv._find_uv": None}):
            with mock.patch("shutil.which", return_value=None):
                with pytest.raises(FileNotFoundError, match="uv binary not found"):
                    find_uv_bin()


class TestShouldFallBackToPip:
    """Tests for pipenv.uv._should_fall_back_to_pip."""

    def test_detects_editable_vcs_in_requirements_file(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        req_file = tmp_path / "reqs.txt"
        req_file.write_text("-e git+https://github.com/user/repo@v1.0#egg=repo\n")
        assert _should_fall_back_to_pip(["-r", str(req_file)]) is True

    def test_no_editable_vcs_in_requirements_file(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        req_file = tmp_path / "reqs.txt"
        req_file.write_text("requests==2.31.0\nflask==3.0.0\n")
        assert _should_fall_back_to_pip(["-r", str(req_file)]) is False

    def test_editable_local_dir_flagged(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        req_file = tmp_path / "reqs.txt"
        req_file.write_text("-e /path/to/local/package\n")
        assert _should_fall_back_to_pip(["-r", str(req_file)]) is True

    def test_no_requirements_file_in_args(self):
        from pipenv.uv import _should_fall_back_to_pip

        assert _should_fall_back_to_pip(["--upgrade", "--no-deps"]) is False

    def test_missing_requirements_file(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        assert _should_fall_back_to_pip(["-r", str(tmp_path / "nonexistent.txt")]) is False

    def test_mixed_deps_with_editable_vcs(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        req_file = tmp_path / "reqs.txt"
        req_file.write_text("requests==2.31.0\n-e git+https://github.com/benoitc/gunicorn@23.0.0#egg=gunicorn\nflask==3.0.0\n")
        assert _should_fall_back_to_pip(["-r", str(req_file)]) is True

    def test_concatenated_r_flag(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        req_file = tmp_path / "reqs.txt"
        req_file.write_text("-e git+https://github.com/user/repo@main#egg=repo\n")
        # -r<file> with no space
        assert _should_fall_back_to_pip([f"-r{req_file}"]) is True

    def test_detects_file_uri(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        req_file = tmp_path / "reqs.txt"
        req_file.write_text("file:///home/user/packages/mylib-1.0.tar.gz\n")
        assert _should_fall_back_to_pip(["-r", str(req_file)]) is True

    def test_detects_dot_path(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        req_file = tmp_path / "reqs.txt"
        req_file.write_text(".\n")
        assert _should_fall_back_to_pip(["-r", str(req_file)]) is True

    def test_detects_relative_path(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        req_file = tmp_path / "reqs.txt"
        req_file.write_text("./libs/mypackage\n")
        assert _should_fall_back_to_pip(["-r", str(req_file)]) is True

    def test_detects_absolute_path(self, tmp_path):
        from pipenv.uv import _should_fall_back_to_pip

        req_file = tmp_path / "reqs.txt"
        req_file.write_text("/home/user/mypackage\n")
        assert _should_fall_back_to_pip(["-r", str(req_file)]) is True


class TestIsLocalPathOrFileUri:
    """Tests for pipenv.uv._is_local_path_or_file_uri."""

    def test_dot_path(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri(".") is True

    def test_relative_path(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri("./mypackage") is True

    def test_parent_path(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri("../mypackage") is True

    def test_absolute_path(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri("/home/user/mypackage") is True

    def test_file_uri(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri("file:///home/user/pkg.tar.gz") is True

    def test_editable_local(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri("-e ./mypackage") is True

    def test_normal_package(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri("requests==2.31.0") is False

    def test_url_package(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri("mylib @ https://example.com/mylib.tar.gz") is False

    def test_empty_string(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri("") is False

    def test_comment(self):
        from pipenv.uv import _is_local_path_or_file_uri

        assert _is_local_path_or_file_uri("# comment") is False


class TestHasLocalPathConstraint:
    """Tests for pipenv.uv._has_local_path_constraint."""

    def test_detects_dot_path(self):
        from pipenv.uv import _has_local_path_constraint

        assert _has_local_path_constraint({"mylib": "."}) is True

    def test_detects_file_uri(self):
        from pipenv.uv import _has_local_path_constraint

        assert _has_local_path_constraint({"mylib": "file:///path/to/pkg.tar.gz"}) is True

    def test_no_local_paths(self):
        from pipenv.uv import _has_local_path_constraint

        assert _has_local_path_constraint({"six": "six==1.16.0", "requests": "requests>=2.0"}) is False


class TestHasEnvVarInConstraints:
    """Tests for pipenv.uv._has_env_var_in_constraints."""

    def test_detects_dollar_brace(self):
        from pipenv.uv import _has_env_var_in_constraints

        assert _has_env_var_in_constraints({"six": "git+https://${GIT_HOST}/user/six@1.0"}) is True

    def test_detects_dollar_name(self):
        from pipenv.uv import _has_env_var_in_constraints

        assert _has_env_var_in_constraints({"six": "git+https://$GIT_HOST/user/six@1.0"}) is True

    def test_no_env_vars(self):
        from pipenv.uv import _has_env_var_in_constraints

        assert _has_env_var_in_constraints({"six": "six==1.16.0"}) is False
