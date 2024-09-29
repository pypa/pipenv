from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, TypeAlias

    from typing_extensions import NotRequired, Protocol, TypedDict

    class Source(TypedDict):
        name: str
        url: str
        verify_ssl: bool

    class Pipenv(TypedDict):
        allow_prereleases: bool
        disable_pip_input: bool

    class DevPackageClass(TypedDict):
        sys_platform: NotRequired[str]
        version: NotRequired[str]
        extras: NotRequired[list[str]]
        editable: NotRequired[bool]
        path: NotRequired[str]
        git: NotRequired[str]
        ref: NotRequired[str]
        markers: NotRequired[str]

    class PipfileRequires(TypedDict):
        python_version: str

    PackageDeclaration: TypeAlias = str | DevPackageClass

    Pipfile = TypedDict(
        "Pipfile",
        {
            "source": list[Source],
            "dev-packages": dict[str, PackageDeclaration],
            "packages": dict[str, PackageDeclaration],
            "pipenv": Pipenv,
            "scripts": dict[str, str],
            "requires": PipfileRequires,
        },
    )

    class SourceDict(TypedDict):
        name: str
        url: str
        verify_ssl: bool

    class ValuesOpts(Protocol):
        help: None
        debug_mode: bool
        isolated_mode: bool
        require_venv: bool
        python: None
        verbose: int
        version: None
        quiet: int
        log: None
        no_input: int
        keyring_provider: str
        proxy: str
        retries: int
        timeout: int
        exists_action: list[Any]
        trusted_hosts: list[Any]
        cert: None
        client_cert: None
        cache_dir: str
        disable_pip_version_check: int
        no_color: bool
        no_python_version_warning: bool
        features_enabled: list[Any]
        deprecated_features_enabled: list[Any]
        requirements: list[Any]
        constraints: list[Any]
        ignore_dependencies: bool
        pre: bool | None
        editables: list[Any]
        dry_run: bool
        target_dir: None
        platforms: None
        python_version: None
        implementation: None
        abis: None
        use_user_site: None
        root_path: None
        prefix_path: None
        src_dir: str
        upgrade: None
        upgrade_strategy: str
        force_reinstall: None
        ignore_installed: None
        ignore_requires_python: bool | None
        build_isolation: bool
        use_pep517: None
        check_build_deps: bool
        override_externally_managed: None
        config_settings: None
        global_options: None
        compile: bool
        warn_script_location: bool
        warn_about_conflicts: bool
        format_control: str
        prefer_binary: bool
        require_hashes: bool
        progress_bar: str
        root_user_action: str
        index_url: str
        extra_index_urls: list[Any]
        no_index: bool
        find_links: list[Any]
        json_report_file: None
        no_clean: bool

    class ResultDepElement(TypedDict):
        version: str
        hashes: list[str]
        name: str
        index: str
        markers: str
