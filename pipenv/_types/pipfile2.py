from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import collections.abc
    from pathlib import Path
    from typing import Any, TypeVar

    from typing_extensions import NotRequired, Protocol, TypedDict

    class TSource(TypedDict):
        name: str
        url: str
        verify_ssl: bool

    class TPackageSpec(TypedDict):
        editable: NotRequired[bool]
        version: NotRequired[str]
        extras: NotRequired[list[str]]

    class TRequires(TypedDict):
        python_version: NotRequired[str]
        python_full_version: NotRequired[str]

    class TPipenv(TypedDict):
        allow_prereleases: NotRequired[bool]
        disable_pip_input: NotRequired[bool]

    PipfileSchema = TypedDict(
        "PipfileSchema",
        {
            "source": list[TSource],
            "packages": dict[str, TPackageSpec | str],  # type: ignore[misc]
            "dev-packages": dict[str, TPackageSpec | str],  # type: ignore[misc]
            "requires": TRequires,
            "scripts": dict[str, str],
            "pipenv": TPipenv,
            # "pipfile": PipfileSection,
        },
    )

    ##############################################
    class THash(TypedDict):
        name: NotRequired[str]
        md5: NotRequired[str]
        sha256: NotRequired[str]
        digest: NotRequired[str]

    TMeta = TypedDict(
        "TMeta",
        {
            "hash": THash,
            "pipfile-spec": int,
            "requires": TRequires,
            "sources": list[TSource],
        },
    )

    class LockfileSchema(TypedDict):
        _meta: TMeta
        default: dict[str, TPackageSpec]
        develop: dict[str, TPackageSpec]

    MutableMappingT = TypeVar("MutableMappingT", bound=collections.abc.MutableMapping)  # type: ignore[type-arg]

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

    class DepNode(TypedDict):
        package_name: str
        installed_version: str
        required_version: str
        parent: NotRequired[tuple[str, str]]

    class DistPackageDict(TypedDict):
        package_name: str
        installed_version: str
        key: str

    class DistPackageDictPlus(DistPackageDict):
        required_version: str
        dependencies: list[DistPackageDictPlus]

    class BasePaths(TypedDict):
        PATH: str
        PYTHONPATH: str
        data: str
        include: str
        libdir: Path
        platinclude: str
        platlib: Path
        platstdlib: str
        prefix: str
        purelib: Path
        scripts: str
        stdlib: str
        libdirs: list[Path]
