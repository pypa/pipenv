# -*- coding=utf-8 -*-
from __future__ import absolute_import

import atexit
import contextlib
import functools
import inspect
import os
import sys
import types

import six
from packaging import specifiers
from vistir.compat import TemporaryDirectory

from .environment import MYPY_RUNNING
from .utils import (
    call_function_with_correct_args,
    get_method_args,
    nullcontext,
    suppress_setattr,
)

if six.PY3:
    from contextlib import ExitStack
else:
    from contextlib2 import ExitStack


if MYPY_RUNNING:
    from optparse import Values
    from requests import Session
    from typing import (
        Any,
        Callable,
        Dict,
        Generator,
        Generic,
        Iterator,
        List,
        Optional,
        Tuple,
        Type,
        TypeVar,
        Union,
    )
    from .utils import TShimmedPath, TShim, TShimmedFunc

    TFinder = TypeVar("TFinder")
    TResolver = TypeVar("TResolver")
    TReqTracker = TypeVar("TReqTracker")
    TLink = TypeVar("TLink")
    TSession = TypeVar("TSession", bound=Session)
    TCommand = TypeVar("TCommand", covariant=True)
    TCommandInstance = TypeVar("TCommandInstance")
    TCmdDict = Dict[str, Union[Tuple[str, str, str], TCommandInstance]]
    TInstallRequirement = TypeVar("TInstallRequirement")
    TShimmedCmdDict = Union[TShim, TCmdDict]
    TWheelCache = TypeVar("TWheelCache")
    TPreparer = TypeVar("TPreparer")


class SearchScope(object):
    def __init__(self, find_links=None, index_urls=None):
        self.index_urls = index_urls if index_urls else []
        self.find_links = find_links

    @classmethod
    def create(cls, find_links=None, index_urls=None):
        if not index_urls:
            index_urls = ["https://pypi.org/simple"]
        return cls(find_links=find_links, index_urls=index_urls)


class SelectionPreferences(object):
    def __init__(
        self,
        allow_yanked=True,
        allow_all_prereleases=False,
        format_control=None,
        prefer_binary=False,
        ignore_requires_python=False,
    ):
        self.allow_yanked = allow_yanked
        self.allow_all_prereleases = allow_all_prereleases
        self.format_control = format_control
        self.prefer_binary = prefer_binary
        self.ignore_requires_python = ignore_requires_python


class TargetPython(object):
    fallback_get_tags = None  # type: Optional[TShimmedFunc]

    def __init__(
        self,
        platform=None,  # type: Optional[str]
        py_version_info=None,  # type: Optional[Tuple[int, ...]]
        abi=None,  # type: Optional[str]
        implementation=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self._given_py_version_info = py_version_info
        if py_version_info is None:
            py_version_info = sys.version_info[:3]
        elif len(py_version_info) < 3:
            py_version_info += (3 - len(py_version_info)) * (0,)
        else:
            py_version_info = py_version_info[:3]
        py_version = ".".join(map(str, py_version_info[:2]))
        self.abi = abi
        self.implementation = implementation
        self.platform = platform
        self.py_version = py_version
        self.py_version_info = py_version_info
        self._valid_tags = None

    def get_tags(self):
        if self._valid_tags is None and self.fallback_get_tags:
            fallback_func = resolve_possible_shim(self.fallback_get_tags)
            versions = None
            if self._given_py_version_info:
                versions = ["".join(map(str, self._given_py_version_info[:2]))]
            self._valid_tags = fallback_func(
                versions=versions,
                platform=self.platform,
                abi=self.abi,
                impl=self.implementation,
            )
        return self._valid_tags


class CandidatePreferences(object):
    def __init__(self, prefer_binary=False, allow_all_prereleases=False):
        self.prefer_binary = prefer_binary
        self.allow_all_prereleases = allow_all_prereleases


class LinkCollector(object):
    def __init__(self, session=None, search_scope=None):
        self.session = session
        self.search_scope = search_scope


class CandidateEvaluator(object):
    @classmethod
    def create(
        cls,
        project_name,  # type: str
        target_python=None,  # type: Optional[TargetPython]
        prefer_binary=False,  # type: bool
        allow_all_prereleases=False,  # type: bool
        specifier=None,  # type: Optional[specifiers.BaseSpecifier]
        hashes=None,  # type: Optional[Any]
    ):
        if target_python is None:
            target_python = TargetPython()
        if specifier is None:
            specifier = specifiers.SpecifierSet()

        supported_tags = target_python.get_tags()

        return cls(
            project_name=project_name,
            supported_tags=supported_tags,
            specifier=specifier,
            prefer_binary=prefer_binary,
            allow_all_prereleases=allow_all_prereleases,
            hashes=hashes,
        )

    def __init__(
        self,
        project_name,  # type: str
        supported_tags,  # type: List[Any]
        specifier,  # type: specifiers.BaseSpecifier
        prefer_binary=False,  # type: bool
        allow_all_prereleases=False,  # type: bool
        hashes=None,  # type: Optional[Any]
    ):
        self._allow_all_prereleases = allow_all_prereleases
        self._hashes = hashes
        self._prefer_binary = prefer_binary
        self._project_name = project_name
        self._specifier = specifier
        self._supported_tags = supported_tags


class LinkEvaluator(object):
    def __init__(
        self,
        allow_yanked,
        project_name,
        canonical_name,
        formats,
        target_python,
        ignore_requires_python=False,
        ignore_compatibility=True,
    ):
        self._allow_yanked = allow_yanked
        self._canonical_name = canonical_name
        self._ignore_requires_python = ignore_requires_python
        self._formats = formats
        self._target_python = target_python
        self._ignore_compatibility = ignore_compatibility

        self.project_name = project_name


def resolve_possible_shim(target):
    # type: (TShimmedFunc) -> Optional[Union[Type, Callable]]
    if target is None:
        return target
    if getattr(target, "shim", None) and isinstance(
        target.shim, (types.MethodType, types.FunctionType)
    ):
        return target.shim()
    return target


@contextlib.contextmanager
def temp_environ():
    """Allow the ability to set os.environ temporarily"""
    environ = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(environ)


@contextlib.contextmanager
def get_requirement_tracker(req_tracker_creator=None):
    # type: (Optional[Callable]) -> Generator[Optional[TReqTracker], None, None]
    root = os.environ.get("PIP_REQ_TRACKER")
    if not req_tracker_creator:
        yield None
    else:
        req_tracker_args = []
        _, required_args = get_method_args(req_tracker_creator.__init__)  # type: ignore
        with ExitStack() as ctx:
            if root is None:
                root = ctx.enter_context(TemporaryDirectory(prefix="req-tracker")).name
                if root:
                    root = str(root)
                    ctx.enter_context(temp_environ())
                    os.environ["PIP_REQ_TRACKER"] = root
            if required_args is not None and "root" in required_args:
                req_tracker_args.append(root)
            with req_tracker_creator(*req_tracker_args) as tracker:
                yield tracker


@contextlib.contextmanager
def ensure_resolution_dirs(**kwargs):
    # type: (Any) -> Iterator[Dict[str, Any]]
    """
    Ensures that the proper directories are scaffolded and present in the provided kwargs
    for performing dependency resolution via pip.

    :return: A new kwargs dictionary with scaffolded directories for **build_dir**, **src_dir**,
        **download_dir**, and **wheel_download_dir** added to the key value pairs.
    :rtype: Dict[str, Any]
    """
    keys = ("build_dir", "src_dir", "download_dir", "wheel_download_dir")
    if not any(kwargs.get(key) is None for key in keys):
        yield kwargs
    else:
        with TemporaryDirectory(prefix="pip-shims-") as base_dir:
            for key in keys:
                if kwargs.get(key) is not None:
                    continue
                target = os.path.join(base_dir.name, key)
                os.makedirs(target)
                kwargs[key] = target
            yield kwargs


def partial_command(shimmed_path, cmd_mapping=None):
    # type: (Type, Optional[TShimmedCmdDict]) -> Union[Type[TCommandInstance], functools.partial]
    """
    Maps a default set of arguments across all members of a
    :class:`~pip_shims.models.ShimmedPath` instance, specifically for
    :class:`~pip._internal.command.Command` instances which need
    `summary` and `name` arguments.

    :param :class:`~pip_shims.models.ShimmedPath` shimmed_path:  A
        :class:`~pip_shims.models.ShimmedCollection` instance
    :param Any cmd_mapping: A reference to use for mapping against, e.g. an
        import that depends on pip also
    :return: A dictionary mapping new arguments to their default values
    :rtype: Dict[str, str]
    """
    basecls = shimmed_path.shim()
    resolved_cmd_mapping = None  # type: Optional[Dict[str, Any]]
    cmd_mapping = resolve_possible_shim(cmd_mapping)
    if cmd_mapping is not None and isinstance(cmd_mapping, dict):
        resolved_cmd_mapping = cmd_mapping.copy()
    base_args = []  # type: List[str]
    for root_cls in basecls.mro():
        if root_cls.__name__ == "Command":
            _, root_init_args = get_method_args(root_cls.__init__)
            if root_init_args is not None:
                base_args = root_init_args.args
    needs_name_and_summary = any(arg in base_args for arg in ("name", "summary"))
    if not needs_name_and_summary:
        basecls.name = shimmed_path.name
        return basecls
    elif (
        not resolved_cmd_mapping
        and needs_name_and_summary
        and getattr(functools, "partialmethod", None)
    ):
        new_init = functools.partial(
            basecls.__init__, name=shimmed_path.name, summary="Summary"
        )
        basecls.__init__ = new_init
    result = basecls
    assert resolved_cmd_mapping is not None
    for command_name, command_info in resolved_cmd_mapping.items():
        if getattr(command_info, "class_name", None) == shimmed_path.name:
            summary = getattr(command_info, "summary", "Command summary")
            result = functools.partial(basecls, command_name, summary)
            break
    return result


def get_session(
    install_cmd_provider=None,  # type: Optional[TShimmedFunc]
    install_cmd=None,  # type: TCommandInstance
    options=None,  # type: Optional[Values]
):
    # type: (...) -> TSession
    session = None  # type: Optional[TSession]
    if install_cmd is None:
        assert install_cmd_provider is not None
        install_cmd_provider = resolve_possible_shim(install_cmd_provider)
        assert isinstance(install_cmd_provider, (type, functools.partial))
        install_cmd = install_cmd_provider()
    if options is None:
        options = install_cmd.parser.parse_args([])  # type: ignore
    session = install_cmd._build_session(options)  # type: ignore
    assert session is not None
    atexit.register(session.close)
    return session


def populate_options(
    install_command=None,  # type: TCommandInstance
    options=None,  # type: Optional[Values]
    **kwargs  # type: Any
):
    # (...) -> Tuple[Dict[str, Any], Values]
    results = {}
    if install_command is None and options is None:
        raise TypeError("Must pass either options or InstallCommand to populate options")
    if options is None and install_command is not None:
        options, _ = install_command.parser.parse_args([])  # type: ignore
    options_dict = options.__dict__
    for provided_key, provided_value in kwargs.items():
        if provided_key == "isolated":
            options_key = "isolated_mode"
        elif provided_key == "source_dir":
            options_key = "src_dir"
        else:
            options_key = provided_key
        if provided_key in options_dict and provided_value is not None:
            setattr(options, options_key, provided_value)
            results[provided_key] = provided_value
        elif getattr(options, options_key, None) is not None:
            results[provided_key] = getattr(options, options_key)
        else:
            results[provided_key] = provided_value
    return results, options


def get_requirement_set(
    install_command=None,  # type: Optional[TCommandInstance]
    req_set_provider=None,  # type: Optional[TShimmedFunc]
    build_dir=None,  # type: Optional[str]
    src_dir=None,  # type: Optional[str]
    download_dir=None,  # type: Optional[str]
    wheel_download_dir=None,  # type: Optional[str]
    session=None,  # type: Optional[TSession]
    wheel_cache=None,  # type: Optional[TWheelCache]
    upgrade=False,  # type: bool
    upgrade_strategy=None,  # type: Optional[str]
    ignore_installed=False,  # type: bool
    ignore_dependencies=False,  # type: bool
    force_reinstall=False,  # type: bool
    use_user_site=False,  # type: bool
    isolated=False,  # type: bool
    ignore_requires_python=False,  # type: bool
    require_hashes=None,  # type: bool
    cache_dir=None,  # type: Optional[str]
    options=None,  # type: Optional[Values]
    install_cmd_provider=None,  # type: Optional[TShimmedFunc]
):
    # (...) -> TRequirementSet
    """
    Creates a requirement set from the supplied parameters.

    Not all parameters are passed through for all pip versions, but any
    invalid parameters will be ignored if they are not needed to generate a
    requirement set on the current pip version.

    :param install_command: A :class:`~pip._internal.commands.install.InstallCommand`
        instance which is used to generate the finder.
    :param :class:`~pip_shims.models.ShimmedPathCollection` req_set_provider: A provider
        to build requirement set instances.
    :param str build_dir: The directory to build requirements in. Removed in pip 10,
        defeaults to None
    :param str source_dir: The directory to use for source requirements. Removed in
        pip 10, defaults to None
    :param str download_dir: The directory to download requirement artifacts to. Removed
        in pip 10, defaults to None
    :param str wheel_download_dir: The directory to download wheels to. Removed in pip
        10, defaults ot None
    :param :class:`~requests.Session` session: The pip session to use. Removed in pip 10,
        defaults to None
    :param WheelCache wheel_cache: The pip WheelCache instance to use for caching wheels.
        Removed in pip 10, defaults to None
    :param bool upgrade: Whether to try to upgrade existing requirements. Removed in pip
        10, defaults to False.
    :param str upgrade_strategy: The upgrade strategy to use, e.g. "only-if-needed".
        Removed in pip 10, defaults to None.
    :param bool ignore_installed: Whether to ignore installed packages when resolving.
        Removed in pip 10, defaults to False.
    :param bool ignore_dependencies: Whether to ignore dependencies of requirements
        when resolving. Removed in pip 10, defaults to False.
    :param bool force_reinstall: Whether to force reinstall of packages when resolving.
        Removed in pip 10, defaults to False.
    :param bool use_user_site: Whether to use user site packages when resolving. Removed
        in pip 10, defaults to False.
    :param bool isolated: Whether to resolve in isolation. Removed in pip 10, defaults
        to False.
    :param bool ignore_requires_python: Removed in pip 10, defaults to False.
    :param bool require_hashes: Whether to require hashes when resolving. Defaults to
        False.
    :param Values options: An :class:`~optparse.Values` instance from an install cmd
    :param install_cmd_provider: A shim for providing new install command instances.
    :type install_cmd_provider: :class:`~pip_shims.models.ShimmedPathCollection`
    :return: A new requirement set instance
    :rtype: :class:`~pip._internal.req.req_set.RequirementSet`
    """
    req_set_provider = resolve_possible_shim(req_set_provider)
    if install_command is None:
        install_cmd_provider = resolve_possible_shim(install_cmd_provider)
        assert isinstance(install_cmd_provider, (type, functools.partial))
        install_command = install_cmd_provider()
    required_args = inspect.getargs(
        req_set_provider.__init__.__code__
    ).args  # type: ignore
    results, options = populate_options(
        install_command,
        options,
        build_dir=build_dir,
        src_dir=src_dir,
        download_dir=download_dir,
        upgrade=upgrade,
        upgrade_strategy=upgrade_strategy,
        ignore_installed=ignore_installed,
        ignore_dependencies=ignore_dependencies,
        force_reinstall=force_reinstall,
        use_user_site=use_user_site,
        isolated=isolated,
        ignore_requires_python=ignore_requires_python,
        require_hashes=require_hashes,
        cache_dir=cache_dir,
    )
    if session is None and "session" in required_args:
        session = get_session(install_cmd=install_command, options=options)
    results["wheel_cache"] = wheel_cache
    results["session"] = session
    results["wheel_download_dir"] = wheel_download_dir
    return call_function_with_correct_args(req_set_provider, **results)


def get_package_finder(
    install_cmd=None,  # type: Optional[TCommand]
    options=None,  # type: Optional[Values]
    session=None,  # type: Optional[TSession]
    platform=None,  # type: Optional[str]
    python_versions=None,  # type: Optional[Tuple[str, ...]]
    abi=None,  # type: Optional[str]
    implementation=None,  # type: Optional[str]
    target_python=None,  # type: Optional[Any]
    ignore_requires_python=None,  # type: Optional[bool]
    target_python_builder=None,  # type: Optional[TShimmedFunc]
    install_cmd_provider=None,  # type: Optional[TShimmedFunc]
):
    # type: (...) -> TFinder
    """Shim for compatibility to generate package finders.

    Build and return a :class:`~pip._internal.index.package_finder.PackageFinder`
    instance using the :class:`~pip._internal.commands.install.InstallCommand` helper
    method to construct the finder, shimmed with backports as needed for compatibility.

    :param install_cmd_provider: A shim for providing new install command instances.
    :type install_cmd_provider: :class:`~pip_shims.models.ShimmedPathCollection`
    :param install_cmd: A :class:`~pip._internal.commands.install.InstallCommand`
        instance which is used to generate the finder.
    :param optparse.Values options: An optional :class:`optparse.Values` instance
        generated by calling `install_cmd.parser.parse_args()` typically.
    :param session: An optional session instance, can be created by the `install_cmd`.
    :param Optional[str] platform: An optional platform string, e.g. linux_x86_64
    :param Optional[Tuple[str, ...]] python_versions: A tuple of 2-digit strings
        representing python versions, e.g. ("27", "35", "36", "37"...)
    :param Optional[str] abi: The target abi to support, e.g. "cp38"
    :param Optional[str] implementation: An optional implementation string for limiting
        searches to a specific implementation, e.g. "cp" or "py"
    :param target_python: A :class:`~pip._internal.models.target_python.TargetPython`
        instance (will be translated to alternate arguments if necessary on incompatible
        pip versions).
    :param Optional[bool] ignore_requires_python: Whether to ignore `requires_python`
        on resulting candidates, only valid after pip version 19.3.1
    :param target_python_builder: A 'TargetPython' builder (e.g. the class itself,
        uninstantiated)
    :return: A :class:`pip._internal.index.package_finder.PackageFinder` instance
    :rtype: :class:`pip._internal.index.package_finder.PackageFinder`

    :Example:

    >>> from pip_shims.shims import InstallCommand, get_package_finder
    >>> install_cmd = InstallCommand()
    >>> finder = get_package_finder(
    ...     install_cmd, python_versions=("27", "35", "36", "37", "38"), implementation="
    cp"
    ... )
    >>> candidates = finder.find_all_candidates("requests")
    >>> requests_222 = next(iter(c for c in candidates if c.version.public == "2.22.0"))
    >>> requests_222
    <InstallationCandidate('requests', <Version('2.22.0')>, <Link https://files.pythonhos
    ted.org/packages/51/bd/23c926cd341ea6b7dd0b2a00aba99ae0f828be89d72b2190f27c11d4b7fb/r
    equests-2.22.0-py2.py3-none-any.whl#sha256=9cf5292fcd0f598c671cfc1e0d7d1a7f13bb8085e9
    a590f48c010551dc6c4b31 (from https://pypi.org/simple/requests/) (requires-python:>=2.
    7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*)>)>
    """
    if install_cmd is None:
        install_cmd_provider = resolve_possible_shim(install_cmd_provider)
        assert isinstance(install_cmd_provider, (type, functools.partial))
        install_cmd = install_cmd_provider()
    if options is None:
        options, _ = install_cmd.parser.parse_args([])  # type: ignore
    if session is None:
        session = get_session(install_cmd=install_cmd, options=options)  # type: ignore
    builder_args = inspect.getargs(
        install_cmd._build_package_finder.__code__
    )  # type: ignore
    build_kwargs = {"options": options, "session": session}
    expects_targetpython = "target_python" in builder_args.args
    received_python = any(arg for arg in [platform, python_versions, abi, implementation])
    if expects_targetpython and received_python and not target_python:
        if target_python_builder is None:
            target_python_builder = TargetPython
        py_version_info = None
        if python_versions:
            py_version_info_python = max(python_versions)
            py_version_info = tuple([int(part) for part in py_version_info_python])
        target_python = target_python_builder(
            platform=platform,
            abi=abi,
            implementation=implementation,
            py_version_info=py_version_info,
        )
        build_kwargs["target_python"] = target_python
    elif any(
        arg in builder_args.args
        for arg in ["platform", "python_versions", "abi", "implementation"]
    ):
        if target_python and not received_python:
            tags = target_python.get_tags()
            version_impl = set([t[0] for t in tags])
            # impls = set([v[:2] for v in version_impl])
            # impls.remove("py")
            # impl = next(iter(impls), "py") if not target_python
            versions = set([v[2:] for v in version_impl])
            build_kwargs.update(
                {
                    "platform": target_python.platform,
                    "python_versions": versions,
                    "abi": target_python.abi,
                    "implementation": target_python.implementation,
                }
            )
    if (
        ignore_requires_python is not None
        and "ignore_requires_python" in builder_args.args
    ):
        build_kwargs["ignore_requires_python"] = ignore_requires_python
    return install_cmd._build_package_finder(**build_kwargs)  # type: ignore


def shim_unpack(
    unpack_fn,  # type: TShimmedFunc
    download_dir,  # type str
    ireq=None,  # type: Optional[Any]
    link=None,  # type: Optional[Any]
    location=None,  # type Optional[str],
    hashes=None,  # type: Optional[Any]
    progress_bar="off",  # type: str
    only_download=None,  # type: Optional[bool]
    session=None,  # type: Optional[Any]
):
    # (...) -> None
    """
    Accepts all parameters that have been valid to pass
    to :func:`pip._internal.download.unpack_url` and selects or
    drops parameters as needed before invoking the provided
    callable.

    :param unpack_fn: A callable or shim referring to the pip implementation
    :type unpack_fn: Callable
    :param str download_dir: The directory to download the file to
    :param Optional[:class:`~pip._internal.req.req_install.InstallRequirement`] ireq:
        an Install Requirement instance, defaults to None
    :param Optional[:class:`~pip._internal.models.link.Link`] link: A Link instance,
        defaults to None.
    :param Optional[str] location: A location or source directory if the target is
        a VCS url, defaults to None.
    :param Optional[Any] hashes: A Hashes instance, defaults to None
    :param str progress_bar: Indicates progress par usage during download, defatuls to
        off.
    :param Optional[bool] only_download: Whether to skip install, defaults to None.
    :param Optional[`~requests.Session`] session: A PipSession instance, defaults to
        None.
    :return: The result of unpacking the url.
    :rtype: None
    """
    unpack_fn = resolve_possible_shim(unpack_fn)
    required_args = inspect.getargs(unpack_fn.__code__).args  # type: ignore
    unpack_kwargs = {"download_dir": download_dir}
    if ireq:
        if not link and ireq.link:
            link = ireq.link
        if only_download is None:
            only_download = ireq.is_wheel
        if hashes is None:
            hashes = ireq.hashes(True)
        if location is None and getattr(ireq, "source_dir", None):
            location = ireq.source_dir
    unpack_kwargs.update({"link": link, "location": location})
    if hashes is not None and "hashes" in required_args:
        unpack_kwargs["hashes"] = hashes
    if "progress_bar" in required_args:
        unpack_kwargs["progress_bar"] = progress_bar
    if only_download is not None and "only_download" in required_args:
        unpack_kwargs["only_download"] = only_download
    if session is not None and "session" in required_args:
        unpack_kwargs["session"] = session
    return unpack_fn(**unpack_kwargs)  # type: ignore


@contextlib.contextmanager
def make_preparer(
    preparer_fn,  # type: TShimmedFunc
    req_tracker_fn=None,  # type: Optional[TShimmedFunc]
    build_dir=None,  # type: Optional[str]
    src_dir=None,  # type: Optional[str]
    download_dir=None,  # type: Optional[str]
    wheel_download_dir=None,  # type: Optional[str]
    progress_bar="off",  # type: str
    build_isolation=False,  # type: bool
    session=None,  # type: Optional[TSession]
    finder=None,  # type: Optional[TFinder]
    options=None,  # type: Optional[Values]
    require_hashes=None,  # type: Optional[bool]
    use_user_site=None,  # type: Optional[bool]
    req_tracker=None,  # type: Optional[Union[TReqTracker, TShimmedFunc]]
    install_cmd_provider=None,  # type: Optional[TShimmedFunc]
    install_cmd=None,  # type: Optional[TCommandInstance]
):
    # (...) -> ContextManager
    """
    Creates a requirement preparer for preparing pip requirements.

    Provides a compatibilty shim that accepts all previously valid arguments and
    discards any that are no longer used.

    :raises TypeError: No requirement tracker provided and one cannot be generated
    :raises TypeError: No valid sessions provided and one cannot be generated
    :raises TypeError: No valid finders provided and one cannot be generated
    :param TShimmedFunc preparer_fn: Callable or shim for generating preparers.
    :param Optional[TShimmedFunc] req_tracker_fn: Callable or shim for generating
        requirement trackers, defualts to None
    :param Optional[str] build_dir: Directory for building packages and wheels,
        defaults to None
    :param Optional[str] src_dir: Directory to find or extract source files, defaults
        to None
    :param Optional[str] download_dir: Target directory to download files, defaults to
        None
    :param Optional[str] wheel_download_dir: Target directoryto download wheels, defaults
        to None
    :param str progress_bar: Whether to display a progress bar, defaults to off
    :param bool build_isolation: Whether to build requirements in isolation, defaults
        to False
    :param Optional[TSession] session: Existing session to use for getting requirements,
        defaults to None
    :param Optional[TFinder] finder: The package finder to use during resolution,
        defaults to None
    :param Optional[Values] options: Pip options to use if needed, defaults to None
    :param Optional[bool] require_hashes: Whether to require hashes for preparation
    :param Optional[bool] use_user_site: Whether to use the user site directory for
        preparing requirements
    :param Optional[Union[TReqTracker, TShimmedFunc]] req_tracker: The requirement
        tracker to use for building packages, defaults to None
    :param Optional[TCommandInstance] install_cmd: The install command used to create
        the finder, session, and options if needed, defaults to None
    :yield: A new requirement preparer instance
    :rtype: ContextManager[:class:`~pip._internal.operations.prepare.RequirementPreparer`]

    :Example:

    >>> from pip_shims.shims import (
    ...     InstallCommand, get_package_finder, make_preparer, get_requirement_tracker
    ... )
    >>> install_cmd = InstallCommand()
    >>> pip_options, _ = install_cmd.parser.parse_args([])
    >>> session = install_cmd._build_session(pip_options)
    >>> finder = get_package_finder(
    ...     install_cmd, session=session, options=pip_options
    ... )
    >>> with make_preparer(
    ...     options=pip_options, finder=finder, session=session, install_cmd=ic
    ... ) as preparer:
    ...     print(preparer)
    <pip._internal.operations.prepare.RequirementPreparer object at 0x7f8a2734be80>
    """
    preparer_fn = resolve_possible_shim(preparer_fn)
    required_args = inspect.getargs(preparer_fn.__init__.__code__).args  # type: ignore
    if not req_tracker and not req_tracker_fn and "req_tracker" in required_args:
        raise TypeError("No requirement tracker and no req tracker generator found!")
    req_tracker_fn = resolve_possible_shim(req_tracker_fn)
    pip_options_created = options is None
    session_is_required = "session" in required_args
    finder_is_required = "finder" in required_args
    options_map = {
        "src_dir": src_dir,
        "download_dir": download_dir,
        "wheel_download_dir": wheel_download_dir,
        "build_dir": build_dir,
        "progress_bar": progress_bar,
        "build_isolation": build_isolation,
        "require_hashes": require_hashes,
        "use_user_site": use_user_site,
    }
    if install_cmd is None:
        assert install_cmd_provider is not None
        install_cmd_provider = resolve_possible_shim(install_cmd_provider)
        assert isinstance(install_cmd_provider, (type, functools.partial))
        install_cmd = install_cmd_provider()
    preparer_args, options = populate_options(install_cmd, options, **options_map)
    if options is not None and pip_options_created:
        for k, v in options_map.items():
            suppress_setattr(options, k, v, filter_none=True)
    if all([session is None, install_cmd is None, session_is_required]):
        raise TypeError(
            "Preparer requires a session instance which was not supplied and cannot be "
            "created without an InstallCommand."
        )
    elif all([session is None, session_is_required]):
        session = get_session(install_cmd=install_cmd, options=options)
    if all([finder is None, install_cmd is None, finder_is_required]):
        raise TypeError(
            "RequirementPreparer requires a packagefinder but no InstallCommand"
            " was provided to build one and none was passed in."
        )
    elif all([finder is None, finder_is_required]):
        finder = get_package_finder(install_cmd, options=options, session=session)
    preparer_args.update({"finder": finder, "session": session})
    req_tracker_fn = nullcontext if not req_tracker_fn else req_tracker_fn
    with req_tracker_fn() as tracker_ctx:
        if "req_tracker" in required_args:
            req_tracker = tracker_ctx if req_tracker is None else req_tracker
            preparer_args["req_tracker"] = req_tracker

        result = call_function_with_correct_args(preparer_fn, **preparer_args)
        yield result


def get_resolver(
    resolver_fn,  # type: TShimmedFunc
    install_req_provider=None,  # type: Optional[TShimmedFunc]
    format_control_provider=None,  # type: Optional[TShimmedFunc]
    wheel_cache_provider=None,  # type: Optional[TShimmedFunc]
    finder=None,  # type: Optional[TFinder]
    upgrade_strategy="to-satisfy-only",  # type: str
    force_reinstall=None,  # type: Optional[bool]
    ignore_dependencies=None,  # type: Optional[bool]
    ignore_requires_python=None,  # type: Optional[bool]
    ignore_installed=True,  # type: bool
    use_user_site=False,  # type: bool
    isolated=None,  # type: Optional[bool]
    wheel_cache=None,  # type: Optional[TWheelCache]
    preparer=None,  # type: Optional[TPreparer]
    session=None,  # type: Optional[TSession]
    options=None,  # type: Optional[Values]
    make_install_req=None,  # type: Optional[Callable]
    install_cmd_provider=None,  # type: Optional[TShimmedFunc]
    install_cmd=None,  # type: Optional[TCommandInstance]
):
    # (...) -> TResolver
    """
    A resolver creation compatibility shim for generating a resolver.

    Consumes any argument that was previously used to instantiate a
    resolver, discards anything that is no longer valid.

    .. note:: This is only valid for **pip >= 10.0.0**

    :raises ValueError: A session is required but not provided and one cannot be created
    :raises ValueError: A finder is required but not provided and one cannot be created
    :raises ValueError: An install requirement provider is required and has not been
        provided
    :param TShimmedFunc resolver_fn: The resolver function used to create new resolver
        instances.
    :param TShimmedFunc install_req_provider: The provider function to use to generate
        install requirements if needed.
    :param TShimmedFunc format_control_provider: The provider function to use to generate
        a format_control instance if needed.
    :param TShimmedFunc wheel_cache_provider: The provider function to use to generate
        a wheel cache if needed.
    :param Optional[TFinder] finder: The package finder to use during resolution,
        defaults to None.
    :param str upgrade_strategy: Upgrade strategy to use, defaults to ``only-if-needed``.
    :param Optional[bool] force_reinstall: Whether to simulate or assume package
        reinstallation during resolution, defaults to None
    :param Optional[bool] ignore_dependencies: Whether to ignore package dependencies,
        defaults to None
    :param Optional[bool] ignore_requires_python: Whether to ignore indicated
        required_python versions on packages, defaults to None
    :param bool ignore_installed: Whether to ignore installed packages during resolution,
        defaults to True
    :param bool use_user_site: Whether to use the user site location during resolution,
        defaults to False
    :param Optional[bool] isolated: Whether to isolate the resolution process, defaults
        to None
    :param Optional[TWheelCache] wheel_cache: The wheel cache to use, defaults to None
    :param Optional[TPreparer] preparer: The requirement preparer to use, defaults to
        None
    :param Optional[TSession] session: Existing session to use for getting requirements,
        defaults to None
    :param Optional[Values] options: Pip options to use if needed, defaults to None
    :param Optional[functools.partial] make_install_req: The partial function to pass in
        to the resolver for actually generating install requirements, if necessary
    :param Optional[TCommandInstance] install_cmd: The install command used to create
        the finder, session, and options if needed, defaults to None.
    :return: A new resolver instance.
    :rtype: :class:`~pip._internal.legacy_resolve.Resolver`

    :Example:

    >>> import os
    >>> from tempdir import TemporaryDirectory
    >>> from pip_shims.shims import (
    ...     InstallCommand, get_package_finder, make_preparer, get_requirement_tracker,
    ...     get_resolver, InstallRequirement, RequirementSet
    ... )
    >>> install_cmd = InstallCommand()
    >>> pip_options, _ = install_cmd.parser.parse_args([])
    >>> session = install_cmd._build_session(pip_options)
    >>> finder = get_package_finder(
    ...     install_cmd, session=session, options=pip_options
    ... )
    >>> wheel_cache = WheelCache(USER_CACHE_DIR, FormatControl(None, None))
    >>> with TemporaryDirectory() as temp_base:
    ...     reqset = RequirementSet()
    ...     ireq = InstallRequirement.from_line("requests")
    ...     ireq.is_direct = True
    ...     build_dir = os.path.join(temp_base, "build")
    ...     src_dir = os.path.join(temp_base, "src")
    ...     ireq.build_location(build_dir)
    ...     with make_preparer(
    ...         options=pip_options, finder=finder, session=session,
    ...         build_dir=build_dir, install_cmd=install_cmd,
    ...     ) as preparer:
    ...         resolver = get_resolver(
    ...             finder=finder, ignore_dependencies=False, ignore_requires_python=True,
    ...             preparer=preparer, session=session, options=pip_options,
    ...             install_cmd=install_cmd, wheel_cache=wheel_cache,
    ...         )
    ...         resolver.require_hashes = False
    ...         reqset.add_requirement(ireq)
    ...         results = resolver.resolve(reqset)
    ...         #reqset.cleanup_files()
    ...         for result_req in reqset.requirements:
    ...             print(result_req)
    requests
    chardet
    certifi
    urllib3
    idna
    """
    resolver_fn = resolve_possible_shim(resolver_fn)
    install_req_provider = resolve_possible_shim(install_req_provider)
    format_control_provider = resolve_possible_shim(format_control_provider)
    wheel_cache_provider = resolve_possible_shim(wheel_cache_provider)
    install_cmd_provider = resolve_possible_shim(install_cmd_provider)
    required_args = inspect.getargs(resolver_fn.__init__.__code__).args  # type: ignore
    install_cmd_dependency_map = {"session": session, "finder": finder}
    resolver_kwargs = {}  # type: Dict[str, Any]
    if install_cmd is None:
        assert isinstance(install_cmd_provider, (type, functools.partial))
        install_cmd = install_cmd_provider()
    if options is None and install_cmd is not None:
        options = install_cmd.parser.parse_args([])  # type: ignore
    for arg, val in install_cmd_dependency_map.items():
        if arg not in required_args:
            continue
        elif val is None and install_cmd is None:
            raise TypeError(
                "Preparer requires a {0} but did not receive one "
                "and cannot generate one".format(arg)
            )
        elif arg == "session" and val is None:
            val = get_session(install_cmd=install_cmd, options=options)
        elif arg == "finder" and val is None:
            val = get_package_finder(install_cmd, options=options, session=session)
        resolver_kwargs[arg] = val
    if "make_install_req" in required_args:
        if make_install_req is None and install_req_provider is not None:
            make_install_req = functools.partial(
                install_req_provider,
                isolated=isolated,
                wheel_cache=wheel_cache,
                # use_pep517=use_pep517,
            )
        assert make_install_req is not None
        resolver_kwargs["make_install_req"] = make_install_req
    if "isolated" in required_args:
        resolver_kwargs["isolated"] = isolated
    if "wheel_cache" in required_args:
        if wheel_cache is None and wheel_cache_provider is not None:
            cache_dir = getattr(options, "cache_dir", None)
            format_control = getattr(
                options,
                "format_control",
                format_control_provider(None, None),  # type: ignore
            )
            wheel_cache = wheel_cache_provider(cache_dir, format_control)
        resolver_kwargs["wheel_cache"] = wheel_cache
    resolver_kwargs.update(
        {
            "upgrade_strategy": upgrade_strategy,
            "force_reinstall": force_reinstall,
            "ignore_dependencies": ignore_dependencies,
            "ignore_requires_python": ignore_requires_python,
            "ignore_installed": ignore_installed,
            "use_user_site": use_user_site,
            "preparer": preparer,
        }
    )
    return resolver_fn(**resolver_kwargs)  # type: ignore


def resolve(
    ireq,  # type: TInstallRequirement
    reqset_provider=None,  # type: Optional[TShimmedFunc]
    req_tracker_provider=None,  # type: Optional[TShimmedFunc]
    install_cmd_provider=None,  # type: Optional[TShimmedFunc]
    install_command=None,  # type: Optional[TCommand]
    finder_provider=None,  # type: Optional[TShimmedFunc]
    resolver_provider=None,  # type: Optional[TShimmedFunc]
    wheel_cache_provider=None,  # type: Optional[TShimmedFunc]
    format_control_provider=None,  # type: Optional[TShimmedFunc]
    make_preparer_provider=None,  # type: Optional[TShimmedFunc]
    options=None,  # type: Optional[Values]
    session=None,  # type: Optional[TSession]
    resolver=None,  # type: Optional[TResolver]
    finder=None,  # type: Optional[TFinder]
    upgrade_strategy="to-satisfy-only",  # type: str
    force_reinstall=None,  # type: Optional[bool]
    ignore_dependencies=None,  # type: Optional[bool]
    ignore_requires_python=None,  # type: Optional[bool]
    ignore_installed=True,  # type: bool
    use_user_site=False,  # type: bool
    isolated=None,  # type: Optional[bool]
    build_dir=None,  # type: Optional[str]
    source_dir=None,  # type: Optional[str]
    download_dir=None,  # type: Optional[str]
    cache_dir=None,  # type: Optional[str]
    wheel_download_dir=None,  # type: Optional[str]
    wheel_cache=None,  # type: Optional[TWheelCache]
    require_hashes=None,  # type: bool
):
    # (...) -> Set[TInstallRequirement]
    """
    Resolves the provided **InstallRequirement**, returning a dictionary.

    Maps a dictionary of names to corresponding ``InstallRequirement`` values.

    :param :class:`~pip._internal.req.req_install.InstallRequirement` ireq: An
        InstallRequirement to initiate the resolution process
    :param :class:`~pip_shims.models.ShimmedPathCollection` reqset_provider: A provider
        to build requirement set instances.
    :param :class:`~pip_shims.models.ShimmedPathCollection` req_tracker_provider: A
        provider to build requirement tracker instances
    :param install_cmd_provider: A shim for providing new install command instances.
    :type install_cmd_provider: :class:`~pip_shims.models.ShimmedPathCollection`
    :param Optional[TCommandInstance] install_command:  The install command used to
        create the finder, session, and options if needed, defaults to None.
    :param :class:`~pip_shims.models.ShimmedPathCollection` finder_provider: A provider
        to package finder instances.
    :param :class:`~pip_shims.models.ShimmedPathCollection` resolver_provider: A provider
        to build resolver instances
    :param TShimmedFunc wheel_cache_provider: The provider function to use to generate a
        wheel cache if needed.
    :param TShimmedFunc format_control_provider: The provider function to use to generate
        a format_control instance if needed.
    :param TShimmedFunc make_preparer_provider: Callable or shim for generating preparers.
    :param Optional[Values] options: Pip options to use if needed, defaults to None
    :param Optional[TSession] session: Existing session to use for getting requirements,
        defaults to None
    :param :class:`~pip._internal.legacy_resolve.Resolver` resolver: A pre-existing
        resolver instance to use for resolution
    :param Optional[TFinder] finder: The package finder to use during resolution,
        defaults to None.
    :param str upgrade_strategy: Upgrade strategy to use, defaults to ``only-if-needed``.
    :param Optional[bool] force_reinstall: Whether to simulate or assume package
        reinstallation during resolution, defaults to None
    :param Optional[bool] ignore_dependencies: Whether to ignore package dependencies,
        defaults to None
    :param Optional[bool] ignore_requires_python: Whether to ignore indicated
        required_python versions on packages, defaults to None
    :param bool ignore_installed: Whether to ignore installed packages during
        resolution, defaults to True
    :param bool use_user_site: Whether to use the user site location during resolution,
        defaults to False
    :param Optional[bool] isolated: Whether to isolate the resolution process, defaults
        to None
    :param Optional[str] build_dir: Directory for building packages and wheels, defaults
        to None
    :param str source_dir: The directory to use for source requirements. Removed in pip
        10, defaults to None
    :param Optional[str] download_dir: Target directory to download files, defaults to
        None
    :param str cache_dir: The cache directory to use for caching artifacts during
        resolution
    :param Optional[str] wheel_download_dir: Target directoryto download wheels, defaults
        to None
    :param Optional[TWheelCache] wheel_cache: The wheel cache to use, defaults to None
    :param bool require_hashes: Whether to require hashes when resolving. Defaults to
        False.
    :return: A dictionary mapping requirements to corresponding
        :class:`~pip._internal.req.req_install.InstallRequirement`s
    :rtype: :class:`~pip._internal.req.req_install.InstallRequirement`

    :Example:

    >>> from pip_shims.shims import resolve, InstallRequirement
    >>> ireq = InstallRequirement.from_line("requests>=2.20")
    >>> results = resolve(ireq)
    >>> for k, v in results.items():
    ...    print("{0}: {1!r}".format(k, v))
    requests: <InstallRequirement object: requests>=2.20 from https://files.pythonhosted.
    org/packages/51/bd/23c926cd341ea6b7dd0b2a00aba99ae0f828be89d72b2190f27c11d4b7fb/reque
    sts-2.22.0-py2.py3-none-any.whl#sha256=9cf5292fcd0f598c671cfc1e0d7d1a7f13bb8085e9a590
    f48c010551dc6c4b31 editable=False>
    idna: <InstallRequirement object: idna<2.9,>=2.5 from https://files.pythonhosted.org/
    packages/14/2c/cd551d81dbe15200be1cf41cd03869a46fe7226e7450af7a6545bfc474c9/idna-2.8-
    py2.py3-none-any.whl#sha256=ea8b7f6188e6fa117537c3df7da9fc686d485087abf6ac197f9c46432
    f7e4a3c (from requests>=2.20) editable=False>
    urllib3: <InstallRequirement object: urllib3!=1.25.0,!=1.25.1,<1.26,>=1.21.1 from htt
    ps://files.pythonhosted.org/packages/b4/40/a9837291310ee1ccc242ceb6ebfd9eb21539649f19
    3a7c8c86ba15b98539/urllib3-1.25.7-py2.py3-none-any.whl#sha256=a8a318824cc77d1fd4b2bec
    2ded92646630d7fe8619497b142c84a9e6f5a7293 (from requests>=2.20) editable=False>
    chardet: <InstallRequirement object: chardet<3.1.0,>=3.0.2 from https://files.pythonh
    osted.org/packages/bc/a9/01ffebfb562e4274b6487b4bb1ddec7ca55ec7510b22e4c51f14098443b8
    /chardet-3.0.4-py2.py3-none-any.whl#sha256=fc323ffcaeaed0e0a02bf4d117757b98aed530d9ed
    4531e3e15460124c106691 (from requests>=2.20) editable=False>
    certifi: <InstallRequirement object: certifi>=2017.4.17 from https://files.pythonhost
    ed.org/packages/18/b0/8146a4f8dd402f60744fa380bc73ca47303cccf8b9190fd16a827281eac2/ce
    rtifi-2019.9.11-py2.py3-none-any.whl#sha256=fd7c7c74727ddcf00e9acd26bba8da604ffec95bf
    1c2144e67aff7a8b50e6cef (from requests>=2.20) editable=False>
    """
    reqset_provider = resolve_possible_shim(reqset_provider)
    finder_provider = resolve_possible_shim(finder_provider)
    resolver_provider = resolve_possible_shim(resolver_provider)
    wheel_cache_provider = resolve_possible_shim(wheel_cache_provider)
    format_control_provider = resolve_possible_shim(format_control_provider)
    make_preparer_provider = resolve_possible_shim(make_preparer_provider)
    req_tracker_provider = resolve_possible_shim(req_tracker_provider)
    install_cmd_provider = resolve_possible_shim(install_cmd_provider)
    if install_command is None:
        assert isinstance(install_cmd_provider, (type, functools.partial))
        install_command = install_cmd_provider()
    kwarg_map = {
        "upgrade_strategy": upgrade_strategy,
        "force_reinstall": force_reinstall,
        "ignore_dependencies": ignore_dependencies,
        "ignore_requires_python": ignore_requires_python,
        "ignore_installed": ignore_installed,
        "use_user_site": use_user_site,
        "isolated": isolated,
        "build_dir": build_dir,
        "src_dir": source_dir,
        "download_dir": download_dir,
        "require_hashes": require_hashes,
        "cache_dir": cache_dir,
    }
    kwargs, options = populate_options(install_command, options, **kwarg_map)
    with ExitStack() as ctx:
        kwargs = ctx.enter_context(
            ensure_resolution_dirs(wheel_download_dir=wheel_download_dir, **kwargs)
        )
        wheel_download_dir = kwargs.pop("wheel_download_dir")
        if session is None:
            session = get_session(install_cmd=install_command, options=options)
        if finder is None:
            finder = finder_provider(
                install_command, options=options, session=session
            )  # type: ignore
        format_control = getattr(options, "format_control", None)
        if not format_control:
            format_control = format_control_provider(None, None)  # type: ignore
        wheel_cache = wheel_cache_provider(
            kwargs["cache_dir"], format_control
        )  # type: ignore
        ireq.is_direct = True  # type: ignore
        ireq.build_location(kwargs["build_dir"])  # type: ignore
        if reqset_provider is None:
            raise TypeError(
                "cannot resolve without a requirement set provider... failed!"
            )
        reqset = reqset_provider(
            install_command,
            options=options,
            session=session,
            wheel_download_dir=wheel_download_dir,
            **kwargs
        )  # type: ignore
        if getattr(reqset, "prepare_files", None):
            reqset.add_requirement(ireq)
            results = reqset.prepare_files(finder)
            result = reqset.requirements
            reqset.cleanup_files()
            return result
        if make_preparer_provider is None:
            raise TypeError("Cannot create requirement preparer, cannot resolve!")

        preparer_args = {
            "build_dir": kwargs["build_dir"],
            "src_dir": kwargs["src_dir"],
            "download_dir": kwargs["download_dir"],
            "wheel_download_dir": wheel_download_dir,
            "build_isolation": kwargs["isolated"],
            "install_cmd": install_command,
            "options": options,
            "finder": finder,
            "session": session,
            "use_user_site": use_user_site,
            "require_hashes": require_hashes,
        }
        # with req_tracker_provider() as req_tracker:
        if isinstance(req_tracker_provider, (types.FunctionType, functools.partial)):
            preparer_args["req_tracker"] = ctx.enter_context(req_tracker_provider())
        resolver_keys = [
            "upgrade_strategy",
            "force_reinstall",
            "ignore_dependencies",
            "ignore_installed",
            "use_user_site",
            "isolated",
            "use_user_site",
        ]
        resolver_args = {key: kwargs[key] for key in resolver_keys if key in kwargs}
        if resolver_provider is None:
            raise TypeError("Cannot resolve without a resolver provider... failed!")
        preparer = ctx.enter_context(make_preparer_provider(**preparer_args))
        resolver = resolver_provider(
            finder=finder,
            preparer=preparer,
            session=session,
            options=options,
            install_cmd=install_command,
            wheel_cache=wheel_cache,
            **resolver_args
        )  # type: ignore
        reqset.add_requirement(ireq)
        resolver.require_hashes = kwargs.get("require_hashes", False)  # type: ignore
        resolver.resolve(reqset)  # type: ignore
        results = reqset.requirements
        reqset.cleanup_files()
        return results
