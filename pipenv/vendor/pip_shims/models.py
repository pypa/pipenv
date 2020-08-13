# -*- coding: utf-8 -*-
"""
Helper module for shimming functionality across pip versions.
"""
from __future__ import absolute_import, print_function

import collections
import functools
import importlib
import inspect
import operator
import sys
import types
import weakref

import six

from . import compat
from .environment import BASE_IMPORT_PATH, MYPY_RUNNING, get_pip_version
from .utils import (
    add_mixin_to_class,
    apply_alias,
    ensure_function,
    fallback_is_artifact,
    fallback_is_file_url,
    fallback_is_vcs,
    get_method_args,
    has_property,
    make_classmethod,
    make_method,
    nullcontext,
    parse_version,
    resolve_possible_shim,
    set_default_kwargs,
    split_package,
    suppress_setattr,
)

# format: off
six.add_move(
    six.MovedAttribute("Sequence", "collections", "collections.abc")
)  # type: ignore  # noqa
six.add_move(
    six.MovedAttribute("Mapping", "collections", "collections.abc")
)  # type: ignore  # noqa
from six.moves import Sequence, Mapping  # type: ignore  # noqa  # isort:skip

# format: on


if MYPY_RUNNING:
    import packaging.version

    Module = types.ModuleType
    from typing import (  # noqa:F811
        Any,
        Callable,
        ContextManager,
        Dict,
        Iterable,
        List,
        Mapping,
        Optional,
        Set,
        Tuple,
        Type,
        TypeVar,
        Union,
    )


PIP_VERSION_SET = {
    "7.0.0",
    "7.0.1",
    "7.0.2",
    "7.0.3",
    "7.1.0",
    "7.1.1",
    "7.1.2",
    "8.0.0",
    "8.0.1",
    "8.0.2",
    "8.0.3",
    "8.1.0",
    "8.1.1",
    "8.1.2",
    "9.0.0",
    "9.0.1",
    "9.0.2",
    "9.0.3",
    "10.0.0",
    "10.0.1",
    "18.0",
    "18.1",
    "19.0",
    "19.0.1",
    "19.0.2",
    "19.0.3",
    "19.1",
    "19.1.1",
    "19.2",
    "19.2.1",
    "19.2.2",
    "19.2.3",
    "19.3",
    "19.3.1",
    "20.0",
    "20.0.1",
    "20.0.2",
}


ImportTypesBase = collections.namedtuple(
    "ImportTypes", ["FUNCTION", "CLASS", "MODULE", "CONTEXTMANAGER"]
)


class ImportTypes(ImportTypesBase):
    FUNCTION = 0
    CLASS = 1
    MODULE = 2
    CONTEXTMANAGER = 3
    METHOD = 4
    ATTRIBUTE = 5


class PipVersion(Sequence):
    def __init__(
        self,
        version,
        round_prereleases_up=True,
        base_import_path=None,
        vendor_import_path="pip._vendor",
    ):
        # type: (str, bool, Optional[str], str) -> None
        self.version = version
        self.vendor_import_path = vendor_import_path
        self.round_prereleases_up = round_prereleases_up
        parsed_version = self._parse()
        if round_prereleases_up and parsed_version.is_prerelease:
            parsed_version._version = parsed_version._version._replace(dev=None, pre=None)
            self.version = str(parsed_version)
            parsed_version = self._parse()
        if base_import_path is None:
            if parsed_version >= parse_version("10.0.0"):
                base_import_path = "{}._internal".format(BASE_IMPORT_PATH)
            else:
                base_import_path = "{}".format(BASE_IMPORT_PATH)
        self.base_import_path = base_import_path
        self.parsed_version = parsed_version

    @property
    def version_tuple(self):
        return tuple(self.parsed_version._version)

    @property
    def version_key(self):
        return self.parsed_version._key

    def is_valid(self, compared_to):
        # type: (PipVersion) -> bool
        return self == compared_to

    def __len__(self):
        # type: () -> int
        return len(self.version_tuple)

    def __getitem__(self, item):
        return self.version_tuple[item]

    def _parse(self):
        # type: () -> packaging.version._BaseVersion
        return parse_version(self.version)

    def __hash__(self):
        # type: () -> int
        return hash(self.parsed_version)

    def __str__(self):
        # type: () -> str
        return "{!s}".format(self.parsed_version)

    def __repr__(self):
        # type: () -> str
        return (
            "<PipVersion {!r}, Path: {!r}, Vendor Path: {!r}, " "Parsed Version: {!r}>"
        ).format(
            self.version,
            self.base_import_path,
            self.vendor_import_path,
            self.parsed_version,
        )

    def __gt__(self, other):
        # type: (PipVersion) -> bool
        return self.parsed_version > other.parsed_version

    def __lt__(self, other):
        # type: (PipVersion) -> bool
        return self.parsed_version < other.parsed_version

    def __le__(self, other):
        # type: (PipVersion) -> bool
        return self.parsed_version <= other.parsed_version

    def __ge__(self, other):
        # type: (PipVersion) -> bool
        return self.parsed_version >= other.parsed_version

    def __ne__(self, other):
        # type: (object) -> bool
        if not isinstance(other, PipVersion):
            return NotImplemented
        return self.parsed_version != other.parsed_version

    def __eq__(self, other):
        # type: (object) -> bool
        if not isinstance(other, PipVersion):
            return NotImplemented
        return self.parsed_version == other.parsed_version


version_cache = weakref.WeakValueDictionary()  # type: Mapping[str, PipVersion]
CURRENT_PIP_VERSION = None  # type: Optional[PipVersion]


def pip_version_lookup(version, *args, **kwargs):
    # type: (str, Any, Any) -> PipVersion
    try:
        cached = version_cache.get(version)
    except KeyError:
        cached = None
    if cached is not None:
        return cached
    pip_version = PipVersion(version, *args, **kwargs)
    version_cache[version] = pip_version
    return pip_version


def lookup_current_pip_version():
    # type: () -> PipVersion
    global CURRENT_PIP_VERSION
    if CURRENT_PIP_VERSION is not None:
        return CURRENT_PIP_VERSION
    CURRENT_PIP_VERSION = pip_version_lookup(get_pip_version())
    return CURRENT_PIP_VERSION


class PipVersionRange(Sequence):
    def __init__(self, start, end):
        # type: (PipVersion, PipVersion) -> None
        if start > end:
            raise ValueError("Start version must come before end version")
        self._versions = (start, end)

    def __str__(self):
        # type: () -> str
        return "{!s} -> {!s}".format(self._versions[0], self._versions[-1])

    @property
    def base_import_paths(self):
        # type: () -> Set[str]
        return {version.base_import_path for version in self._versions}

    @property
    def vendor_import_paths(self):
        # type: () -> Set[str]
        return {version.vendor_import_path for version in self._versions}

    def is_valid(self):
        # type: () -> bool
        return pip_version_lookup(get_pip_version()) in self

    def __contains__(self, item):
        # type: (PipVersion) -> bool
        if not isinstance(item, PipVersion):
            raise TypeError("Need a PipVersion instance to compare")
        return item >= self[0] and item <= self[-1]

    def __getitem__(self, item):
        # type: (int) -> PipVersion
        return self._versions[item]

    def __len__(self):
        # type: () -> int
        return len(self._versions)

    def __lt__(self, other):
        # type: ("PipVersionRange") -> bool
        return (other.is_valid() and not self.is_valid()) or (
            not (self.is_valid() or other.is_valid())
            or (self.is_valid() and other.is_valid())
            and self._versions[-1] < other._versions[-1]
        )

    def __hash__(self):
        # type: () -> int
        return hash(self._versions)


class ShimmedPath(object):
    __modules = {}  # type: Dict[str, Module]

    def __init__(
        self,
        name,  # type: str
        import_target,  # type: str
        import_type,  # type: int
        version_range,  # type: PipVersionRange
        provided_methods=None,  # type: Optional[Dict[str, Callable]]
        provided_functions=None,  # type: Optional[Dict[str, Callable]]
        provided_classmethods=None,  # type: Optional[Dict[str, Callable]]
        provided_contextmanagers=None,  # type: Optional[Dict[str, Callable]]
        provided_mixins=None,  # type: Optional[List[Type]]
        default_args=None,  # type: Dict[str, Sequence[List[Any], Dict[str, Any]]]
    ):
        # type: (...) -> None
        if provided_methods is None:
            provided_methods = {}
        if provided_classmethods is None:
            provided_classmethods = {}
        if provided_functions is None:
            provided_functions = {}
        if provided_contextmanagers is None:
            provided_contextmanagers = {}
        if provided_mixins is None:
            provided_mixins = []
        if default_args is None:
            default_args = {}
        self.version_range = version_range
        self.name = name
        self.full_import_path = import_target
        module_path, name_to_import = split_package(import_target)
        self.module_path = module_path
        self.name_to_import = name_to_import
        self.import_type = import_type
        self._imported = None  # type: Optional[Module]
        self._provided = None  # type: Optional[Union[Module, Type, Callable, Any]]
        self.provided_methods = provided_methods
        self.provided_functions = provided_functions
        self.provided_classmethods = provided_classmethods
        self.provided_contextmanagers = provided_contextmanagers
        self.provided_mixins = [m for m in provided_mixins if m is not None]
        self.default_args = default_args
        self.aliases = []  # type: List[List[str]]
        self._shimmed = None  # type: Optional[Any]

    def _as_tuple(self):
        # type: () -> Tuple[str, PipVersionRange, str, int]
        return (self.name, self.version_range, self.full_import_path, self.import_type)

    def alias(self, aliases):
        # type: (List[str]) -> "ShimmedPath"
        self.aliases.append(aliases)
        return self

    @classmethod
    def _import_module(cls, module):
        # type: (str) -> Optional[Module]
        if module in ShimmedPath.__modules:
            result = ShimmedPath.__modules[module]
            if result is not None:
                return result
        try:
            imported = importlib.import_module(module)
        except ImportError:
            return None
        else:
            ShimmedPath.__modules[module] = imported
        return imported

    @classmethod
    def _parse_provides_dict(
        cls,
        provides,  # type: Dict[str, Callable]
        prepend_arg_to_callables=None,  # type: Optional[str]
    ):
        # type: (...) -> Dict[str, Callable]
        creating_methods = False
        creating_classmethods = False
        if prepend_arg_to_callables is not None:
            if prepend_arg_to_callables == "self":
                creating_methods = True
            elif prepend_arg_to_callables == "cls":
                creating_classmethods = True
        provides_map = {}
        for item_name, item_value in provides.items():
            if isinstance(item_value, ShimmedPath):
                item_value = item_value.shim()
            if inspect.isfunction(item_value):
                callable_args = inspect.getargs(item_value.__code__).args
                if "self" not in callable_args and creating_methods:
                    item_value = make_method(item_value)(item_name)
                elif "cls" not in callable_args and creating_classmethods:
                    item_value = make_classmethod(item_value)(item_name)
            elif isinstance(item_value, six.string_types):
                module_path, name = split_package(item_value)
                module = cls._import_module(module_path)
                item_value = getattr(module, name, None)
            if item_value is not None:
                provides_map[item_name] = item_value
        return provides_map

    def _update_default_kwargs(self, parent, provided):
        # type: (Union[Module, None], Union[Type, Module]) -> Tuple[Optional[Module], Union[Type, Module]]  # noqa
        for func_name, defaults in self.default_args.items():
            # * Note that we set default args here because we have the
            # * option to use it, even though currently we dont
            # * so we are forcibly ignoring the linter warning about it
            default_args, default_kwargs = defaults  # noqa:W0612
            provided = set_default_kwargs(
                provided, func_name, *default_args, **default_kwargs
            )
        return parent, provided

    def _ensure_functions(self, provided):
        # type: (Union[Module, Type, None]) -> Any
        functions = self._parse_provides_dict(self.provided_functions)
        if provided is None:
            provided = __module__  # type: ignore  # noqa:F821
        for funcname, func in functions.items():
            func = ensure_function(provided, funcname, func)
            setattr(provided, funcname, func)
        return provided

    def _ensure_methods(self, provided):
        # type: (Type) -> Type
        """Given a base class, a new name, and any number of functions to
        attach, turns those functions into classmethods, attaches them,
        and returns an updated class object.
        """
        if not self.is_class:
            return provided
        if not inspect.isclass(provided):
            raise TypeError("Provided argument is not a class: {!r}".format(provided))
        methods = self._parse_provides_dict(
            self.provided_methods, prepend_arg_to_callables="self"
        )
        classmethods = self._parse_provides_dict(
            self.provided_classmethods, prepend_arg_to_callables="cls"
        )
        if not methods and not classmethods:
            return provided
        classname = provided.__name__
        if six.PY2:
            classname = classname.encode(sys.getdefaultencoding())
        type_ = type(classname, (provided,), {})

        if classmethods:
            for method_name, clsmethod in classmethods.items():
                if method_name not in provided.__dict__:
                    type.__setattr__(type_, method_name, clsmethod)

        if methods:
            for method_name, clsmethod in methods.items():
                if method_name not in provided.__dict__:
                    type.__setattr__(type_, method_name, clsmethod)
        return type_

    @property
    def is_class(self):
        # type: () -> bool
        return self.import_type == ImportTypes.CLASS

    @property
    def is_module(self):
        # type: () -> bool
        return self.import_type == ImportTypes.MODULE

    @property
    def is_method(self):
        # type: () -> bool
        return self.import_type == ImportTypes.METHOD

    @property
    def is_function(self):
        # type: () -> bool
        return self.import_type == ImportTypes.FUNCTION

    @property
    def is_contextmanager(self):
        # type: () -> bool
        return self.import_type == ImportTypes.CONTEXTMANAGER

    @property
    def is_attribute(self):
        # type: () -> bool
        return self.import_type == ImportTypes.ATTRIBUTE

    def __contains__(self, pip_version):
        # type: (str) -> bool
        return pip_version_lookup(pip_version) in self.version_range

    @property
    def is_valid(self):
        # type: () -> bool
        return self.version_range.is_valid()

    @property
    def sort_order(self):
        # type: () -> int
        return 1 if self.is_valid else 0

    def _shim_base(self, imported, attribute_name):
        # type: (Union[Module, None], str) -> Any
        result = getattr(imported, attribute_name, None)
        return self._apply_aliases(imported, result)

    def _apply_aliases(self, imported, target):
        # type: (Union[Module, None], Any) -> Any
        for alias_list in self.aliases:
            target = apply_alias(imported, target, *alias_list)
        suppress_setattr(imported, self.name, target)
        return target

    def _shim_parent(self, imported, attribute_name):
        # type: (Union[Module, None], str) -> Tuple[Optional[Module], Any]
        result = self._shim_base(imported, attribute_name)
        if result is not None:
            imported, result = self._update_default_kwargs(imported, result)
            suppress_setattr(imported, attribute_name, result)
        return imported, result

    def update_sys_modules(self, imported):
        # type: (Optional[Module]) -> None
        if imported is None:
            return None
        if self.calculated_module_path in sys.modules:
            del sys.modules[self.calculated_module_path]
        sys.modules[self.calculated_module_path] = imported

    def shim_class(self, imported, attribute_name):
        # type: (Union[Module, None], str) -> Type
        imported, result = self._shim_parent(imported, attribute_name)
        if result is not None:
            assert inspect.isclass(result)  # noqa
            result = self._ensure_methods(result)
            if self.provided_mixins:
                result = add_mixin_to_class(result, self.provided_mixins)
            self._imported = imported
            self._provided = result
            self.update_sys_modules(imported)
            if imported is not None:
                ShimmedPath.__modules[imported.__name__] = imported
        return result

    def shim_module(self, imported, attribute_name):
        # type: (Union[Module, None], str) -> Module
        imported, result = self._shim_parent(imported, attribute_name)
        if result is not None:
            result = self._ensure_functions(result)
            full_import_path = "{}.{}".format(self.calculated_module_path, attribute_name)
            self._imported = imported
            assert isinstance(result, types.ModuleType)
            self._provided = result
            if full_import_path in sys.modules:
                del sys.modules[full_import_path]
                sys.modules[full_import_path] = result
            self.update_sys_modules(imported)
            if imported is not None:
                ShimmedPath.__modules[imported.__name__] = imported
        return result  # type: ignore

    def shim_function(self, imported, attribute_name):
        # type: (Union[Module, None], str) -> Callable
        return self._shim_base(imported, attribute_name)

    def shim_attribute(self, imported, attribute_name):
        # type: (Union[Module, None], Any) -> Any
        return self._shim_base(imported, attribute_name)

    def shim_contextmanager(self, imported, attribute_name):
        # type: (Union[Module, None], str) -> Callable
        result = self._shim_base(imported, attribute_name)
        if result is None:
            result = nullcontext
        suppress_setattr(imported, attribute_name, result)
        self.update_sys_modules(imported)
        return result

    @property
    def shimmed(self):
        # type: () -> Any
        if self._shimmed is None:
            self._shimmed = self.shim()
        return self._shimmed

    def shim(self):
        # type: () -> (Union[Module, Callable, ContextManager, Type])
        imported = self._import()
        if self.is_class:
            return self.shim_class(imported, self.name_to_import)
        elif self.is_module:
            return self.shim_module(imported, self.name_to_import)
        elif self.is_contextmanager:
            return self.shim_contextmanager(imported, self.name_to_import)
        elif self.is_function:
            return self.shim_function(imported, self.name_to_import)
        elif self.is_attribute:
            return self.shim_attribute(imported, self.name_to_import)
        return self._shim_base(imported, self.name_to_import)

    @property
    def calculated_module_path(self):
        current_pip = lookup_current_pip_version()
        prefix = current_pip.base_import_path
        return ".".join([prefix, self.module_path]).rstrip(".")

    def _import(self, prefix=None):
        # type: (Optional[str]) -> Optional[Module]
        # TODO: Decide whether to use _imported and _shimmed or to set the shimmed
        # always to _imported and never save the unshimmed module
        if self._imported is not None:
            return self._imported
        result = self._import_module(self.calculated_module_path)
        return result

    def __hash__(self):
        # type: () -> int
        return hash(self._as_tuple())


class ShimmedPathCollection(object):

    __registry = {}  # type: Dict[str, Any]

    def __init__(self, name, import_type, paths=None):
        # type: (str, int, Optional[Sequence[ShimmedPath]]) -> None
        self.name = name
        self.import_type = import_type
        self.paths = set()  # type: Set[ShimmedPath]
        self.top_path = None
        self._default = None
        self._default_args = {}  # type: Dict[str, Sequence[List[Any], Dict[str, Any]]]
        self.provided_methods = {}  # type: Dict[str, Callable]
        self.provided_functions = {}  # type: Dict[str, Callable]
        self.provided_contextmanagers = {}  # type: Dict[str, Callable]
        self.provided_classmethods = {}  # type: Dict[str, Callable]
        self.provided_mixins = []  # type: List[Type]
        self.pre_shim_functions = []  # type: List[Callable]
        self.aliases = []  # type: List[List[str]]
        if paths is not None:
            if isinstance(paths, six.string_types):
                self.create_path(paths, version_start=lookup_current_pip_version())
            else:
                self.paths.update(set(paths))
        self.register()

    def register(self):
        # type: () -> None
        self.__registry[self.name] = self

    @classmethod
    def get_registry(cls):
        # type: () -> Dict[str, "ShimmedPathCollection"]
        return cls.__registry.copy()

    def add_path(self, path):
        # type: (ShimmedPath) -> None
        self.paths.add(path)

    def set_default(self, default):
        # type: (Any) -> None
        if isinstance(default, (ShimmedPath, ShimmedPathCollection)):
            default = default.shim()
        try:
            default.__qualname__ = default.__name__ = self.name
        except AttributeError:
            pass
        self._default = default

    def set_default_args(self, callable_name, *args, **kwargs):
        # type: (str, Any, Any) -> None
        self._default_args.update({callable_name: [args, kwargs]})

    def provide_function(self, name, fn):
        # type: (str, Union[Callable, ShimmedPath, ShimmedPathCollection]) -> None
        if isinstance(fn, (ShimmedPath, ShimmedPathCollection)):
            fn = resolve_possible_shim(fn)  # type: ignore
        self.provided_functions[name] = fn  # type: ignore

    def provide_method(self, name, fn):
        # type: (str, Union[Callable, ShimmedPath, ShimmedPathCollection, property]) -> None
        if isinstance(fn, (ShimmedPath, ShimmedPathCollection)):
            fn = resolve_possible_shim(fn)  # type: ignore
        self.provided_methods[name] = fn  # type: ignore

    def alias(self, aliases):
        # type: (List[str]) -> None
        """
        Takes a list of methods, functions, attributes, etc and ensures they
        all exist on the object pointing at the same referent.

        :param List[str] aliases: Names to map to the same functionality if they do not
            exist.
        :return: None
        :rtype: None
        """
        self.aliases.append(aliases)

    def add_mixin(self, mixin):
        # type: (Optional[Union[Type, ShimmedPathCollection]]) -> None
        if isinstance(mixin, ShimmedPathCollection):
            mixin = mixin.shim()
        if mixin is not None and inspect.isclass(mixin):
            self.provided_mixins.append(mixin)

    def create_path(self, import_path, version_start, version_end=None):
        # type: (str, str, Optional[str]) -> None
        pip_version_start = pip_version_lookup(version_start)
        if version_end is None:
            version_end = "9999"
        pip_version_end = pip_version_lookup(version_end)
        version_range = PipVersionRange(pip_version_start, pip_version_end)
        new_path = ShimmedPath(
            self.name,
            import_path,
            self.import_type,
            version_range,
            self.provided_methods,
            self.provided_functions,
            self.provided_classmethods,
            self.provided_contextmanagers,
            self.provided_mixins,
            self._default_args,
        )
        if self.aliases:
            for alias_list in self.aliases:
                new_path.alias(alias_list)
        self.add_path(new_path)

    def _sort_paths(self):
        # type: () -> List[ShimmedPath]
        return sorted(self.paths, key=operator.attrgetter("version_range"), reverse=True)

    def _get_top_path(self):
        # type: () -> Optional[ShimmedPath]
        return next(iter(self._sort_paths()), None)

    @classmethod
    def traverse(cls, shim):
        # type: (Union[ShimmedPath, ShimmedPathCollection, Any]) -> Any
        if isinstance(shim, (ShimmedPath, ShimmedPathCollection)):
            result = shim.shim()
            return result
        return shim

    def shim(self):
        # type: () -> Any
        top_path = self._get_top_path()  # type: Union[ShimmedPath, None]
        if not self.pre_shim_functions:
            result = self.traverse(top_path)
        else:
            for fn in self.pre_shim_functions:
                result = fn(top_path)
            result = self.traverse(result)
        if result == nullcontext and self._default is not None:
            default_result = self.traverse(self._default)
            if default_result:
                return default_result
        if result is None and self._default is not None:
            result = self.traverse(self._default)
        return result

    def pre_shim(self, fn):
        # type: (Callable) -> None
        self.pre_shim_functions.append(fn)


def import_pip():
    return importlib.import_module("pip")


_strip_extras = ShimmedPathCollection("_strip_extras", ImportTypes.FUNCTION)
_strip_extras.create_path("req.req_install._strip_extras", "7.0.0", "18.0.0")
_strip_extras.create_path("req.constructors._strip_extras", "18.1.0")

cmdoptions = ShimmedPathCollection("cmdoptions", ImportTypes.MODULE)
cmdoptions.create_path("cli.cmdoptions", "18.1", "9999")
cmdoptions.create_path("cmdoptions", "7.0.0", "18.0")

commands_dict = ShimmedPathCollection("commands_dict", ImportTypes.ATTRIBUTE)
commands_dict.create_path("commands.commands_dict", "7.0.0", "9999")

SessionCommandMixin = ShimmedPathCollection("SessionCommandMixin", ImportTypes.CLASS)
SessionCommandMixin.create_path("cli.req_command.SessionCommandMixin", "19.3.0", "9999")

Command = ShimmedPathCollection("Command", ImportTypes.CLASS)
Command.set_default_args("__init__", name="PipCommand", summary="Default pip command.")
Command.add_mixin(SessionCommandMixin)
Command.create_path("cli.base_command.Command", "18.1", "9999")
Command.create_path("basecommand.Command", "7.0.0", "18.0")

ConfigOptionParser = ShimmedPathCollection("ConfigOptionParser", ImportTypes.CLASS)
ConfigOptionParser.create_path("cli.parser.ConfigOptionParser", "18.1", "9999")
ConfigOptionParser.create_path("baseparser.ConfigOptionParser", "7.0.0", "18.0")

InstallCommand = ShimmedPathCollection("InstallCommand", ImportTypes.CLASS)
InstallCommand.pre_shim(
    functools.partial(compat.partial_command, cmd_mapping=commands_dict)
)
InstallCommand.create_path("commands.install.InstallCommand", "7.0.0", "9999")

DistributionNotFound = ShimmedPathCollection("DistributionNotFound", ImportTypes.CLASS)
DistributionNotFound.create_path("exceptions.DistributionNotFound", "7.0.0", "9999")

FAVORITE_HASH = ShimmedPathCollection("FAVORITE_HASH", ImportTypes.ATTRIBUTE)
FAVORITE_HASH.create_path("utils.hashes.FAVORITE_HASH", "7.0.0", "9999")

FormatControl = ShimmedPathCollection("FormatControl", ImportTypes.CLASS)
FormatControl.create_path("models.format_control.FormatControl", "18.1", "9999")
FormatControl.create_path("index.FormatControl", "7.0.0", "18.0")

FrozenRequirement = ShimmedPathCollection("FrozenRequirement", ImportTypes.CLASS)
FrozenRequirement.create_path("FrozenRequirement", "7.0.0", "9.0.3")
FrozenRequirement.create_path("operations.freeze.FrozenRequirement", "10.0.0", "9999")

get_installed_distributions = ShimmedPathCollection(
    "get_installed_distributions", ImportTypes.FUNCTION
)
get_installed_distributions.create_path(
    "utils.misc.get_installed_distributions", "10", "9999"
)
get_installed_distributions.create_path("utils.get_installed_distributions", "7", "9.0.3")

get_supported = ShimmedPathCollection("get_supported", ImportTypes.FUNCTION)
get_supported.create_path("pep425tags.get_supported", "7.0.0", "9999")

get_tags = ShimmedPathCollection("get_tags", ImportTypes.FUNCTION)
get_tags.create_path("pep425tags.get_tags", "7.0.0", "9999")

index_group = ShimmedPathCollection("index_group", ImportTypes.FUNCTION)
index_group.create_path("cli.cmdoptions.index_group", "18.1", "9999")
index_group.create_path("cmdoptions.index_group", "7.0.0", "18.0")

InstallationError = ShimmedPathCollection("InstallationError", ImportTypes.CLASS)
InstallationError.create_path("exceptions.InstallationError", "7.0.0", "9999")

UninstallationError = ShimmedPathCollection("UninstallationError", ImportTypes.CLASS)
UninstallationError.create_path("exceptions.UninstallationError", "7.0.0", "9999")

DistributionNotFound = ShimmedPathCollection("DistributionNotFound", ImportTypes.CLASS)
DistributionNotFound.create_path("exceptions.DistributionNotFound", "7.0.0", "9999")

RequirementsFileParseError = ShimmedPathCollection(
    "RequirementsFileParseError", ImportTypes.CLASS
)
RequirementsFileParseError.create_path(
    "exceptions.RequirementsFileParseError", "7.0.0", "9999"
)

BestVersionAlreadyInstalled = ShimmedPathCollection(
    "BestVersionAlreadyInstalled", ImportTypes.CLASS
)
BestVersionAlreadyInstalled.create_path(
    "exceptions.BestVersionAlreadyInstalled", "7.0.0", "9999"
)

BadCommand = ShimmedPathCollection("BadCommand", ImportTypes.CLASS)
BadCommand.create_path("exceptions.BadCommand", "7.0.0", "9999")

CommandError = ShimmedPathCollection("CommandError", ImportTypes.CLASS)
CommandError.create_path("exceptions.CommandError", "7.0.0", "9999")

PreviousBuildDirError = ShimmedPathCollection("PreviousBuildDirError", ImportTypes.CLASS)
PreviousBuildDirError.create_path("exceptions.PreviousBuildDirError", "7.0.0", "9999")

install_req_from_editable = ShimmedPathCollection(
    "install_req_from_editable", ImportTypes.FUNCTION
)
install_req_from_editable.create_path(
    "req.constructors.install_req_from_editable", "18.1", "9999"
)
install_req_from_editable.create_path(
    "req.req_install.InstallRequirement.from_editable", "7.0.0", "18.0"
)

install_req_from_line = ShimmedPathCollection(
    "install_req_from_line", ImportTypes.FUNCTION
)
install_req_from_line.create_path(
    "req.constructors.install_req_from_line", "18.1", "9999"
)
install_req_from_line.create_path(
    "req.req_install.InstallRequirement.from_line", "7.0.0", "18.0"
)

install_req_from_req_string = ShimmedPathCollection(
    "install_req_from_req_string", ImportTypes.FUNCTION
)
install_req_from_req_string.create_path(
    "req.constructors.install_req_from_req_string", "19.0", "9999"
)

InstallRequirement = ShimmedPathCollection("InstallRequirement", ImportTypes.CLASS)
InstallRequirement.provide_method("from_line", install_req_from_line)
InstallRequirement.provide_method("from_editable", install_req_from_editable)
InstallRequirement.alias(["build_location", "ensure_build_location"])

InstallRequirement.create_path("req.req_install.InstallRequirement", "7.0.0", "9999")

is_archive_file = ShimmedPathCollection("is_archive_file", ImportTypes.FUNCTION)
is_archive_file.create_path("req.constructors.is_archive_file", "19.3", "9999")
is_archive_file.create_path("download.is_archive_file", "7.0.0", "19.2.3")

is_file_url = ShimmedPathCollection("is_file_url", ImportTypes.FUNCTION)
is_file_url.set_default(fallback_is_file_url)
is_file_url.create_path("download.is_file_url", "7.0.0", "19.2.3")

Downloader = ShimmedPathCollection("Downloader", ImportTypes.CLASS)
Downloader.create_path("network.download.Downloader", "19.3.9", "9999")

unpack_url = ShimmedPathCollection("unpack_url", ImportTypes.FUNCTION)
unpack_url.create_path("download.unpack_url", "7.0.0", "19.3.9")
unpack_url.create_path("operations.prepare.unpack_url", "20.0", "9999")

is_installable_dir = ShimmedPathCollection("is_installable_dir", ImportTypes.FUNCTION)
is_installable_dir.create_path("utils.misc.is_installable_dir", "10.0.0", "9999")
is_installable_dir.create_path("utils.is_installable_dir", "7.0.0", "9.0.3")

Link = ShimmedPathCollection("Link", ImportTypes.CLASS)
Link.provide_method("is_vcs", property(fallback_is_vcs))
Link.provide_method("is_artifact", property(fallback_is_artifact))
Link.create_path("models.link.Link", "19.0.0", "9999")
Link.create_path("index.Link", "7.0.0", "18.1")

make_abstract_dist = ShimmedPathCollection("make_abstract_dist", ImportTypes.FUNCTION)
make_abstract_dist.create_path(
    "distributions.make_distribution_for_install_requirement", "20.0.0", "9999"
)
make_abstract_dist.create_path(
    "distributions.make_distribution_for_install_requirement", "19.1.2", "19.3.9"
)
make_abstract_dist.create_path(
    "operations.prepare.make_abstract_dist", "10.0.0", "19.1.1"
)
make_abstract_dist.create_path("req.req_set.make_abstract_dist", "7.0.0", "9.0.3")

make_distribution_for_install_requirement = ShimmedPathCollection(
    "make_distribution_for_install_requirement", ImportTypes.FUNCTION
)
make_distribution_for_install_requirement.create_path(
    "distributions.make_distribution_for_install_requirement", "20.0.0", "9999"
)
make_distribution_for_install_requirement.create_path(
    "distributions.make_distribution_for_install_requirement", "19.1.2", "19.9.9"
)

make_option_group = ShimmedPathCollection("make_option_group", ImportTypes.FUNCTION)
make_option_group.create_path("cli.cmdoptions.make_option_group", "18.1", "9999")
make_option_group.create_path("cmdoptions.make_option_group", "7.0.0", "18.0")

PackageFinder = ShimmedPathCollection("PackageFinder", ImportTypes.CLASS)
PackageFinder.create_path("index.PackageFinder", "7.0.0", "19.9")
PackageFinder.create_path("index.package_finder.PackageFinder", "20.0", "9999")

CandidateEvaluator = ShimmedPathCollection("CandidateEvaluator", ImportTypes.CLASS)
CandidateEvaluator.set_default(compat.CandidateEvaluator)
CandidateEvaluator.create_path("index.CandidateEvaluator", "19.1.0", "19.3.9")
CandidateEvaluator.create_path("index.package_finder.CandidateEvaluator", "20.0", "9999")

CandidatePreferences = ShimmedPathCollection("CandidatePreferences", ImportTypes.CLASS)
CandidatePreferences.set_default(compat.CandidatePreferences)
CandidatePreferences.create_path("index.CandidatePreferences", "19.2.0", "19.9")
CandidatePreferences.create_path(
    "index.package_finder.CandidatePreferences", "20.0", "9999"
)

LinkCollector = ShimmedPathCollection("LinkCollector", ImportTypes.CLASS)
LinkCollector.set_default(compat.LinkCollector)
LinkCollector.create_path("collector.LinkCollector", "19.3.0", "19.9")
LinkCollector.create_path("index.collector.LinkCollector", "20.0", "9999")

LinkEvaluator = ShimmedPathCollection("LinkEvaluator", ImportTypes.CLASS)
LinkEvaluator.set_default(compat.LinkEvaluator)
LinkEvaluator.create_path("index.LinkEvaluator", "19.2.0", "19.9")
LinkEvaluator.create_path("index.package_finder.LinkEvaluator", "20.0", "9999")

TargetPython = ShimmedPathCollection("TargetPython", ImportTypes.CLASS)
compat.TargetPython.fallback_get_tags = get_tags
TargetPython.set_default(compat.TargetPython)
TargetPython.create_path("models.target_python.TargetPython", "19.2.0", "9999")

SearchScope = ShimmedPathCollection("SearchScope", ImportTypes.CLASS)
SearchScope.set_default(compat.SearchScope)
SearchScope.create_path("models.search_scope.SearchScope", "19.2.0", "9999")

SelectionPreferences = ShimmedPathCollection("SelectionPreferences", ImportTypes.CLASS)
SelectionPreferences.set_default(compat.SelectionPreferences)
SelectionPreferences.create_path(
    "models.selection_prefs.SelectionPreferences", "19.2.0", "9999"
)

parse_requirements = ShimmedPathCollection("parse_requirements", ImportTypes.FUNCTION)
parse_requirements.create_path("req.req_file.parse_requirements", "7.0.0", "9999")

path_to_url = ShimmedPathCollection("path_to_url", ImportTypes.FUNCTION)
path_to_url.create_path("download.path_to_url", "7.0.0", "19.2.3")
path_to_url.create_path("utils.urls.path_to_url", "19.3.0", "9999")

PipError = ShimmedPathCollection("PipError", ImportTypes.CLASS)
PipError.create_path("exceptions.PipError", "7.0.0", "9999")

RequirementPreparer = ShimmedPathCollection("RequirementPreparer", ImportTypes.CLASS)
RequirementPreparer.create_path("operations.prepare.RequirementPreparer", "7", "9999")

RequirementSet = ShimmedPathCollection("RequirementSet", ImportTypes.CLASS)
RequirementSet.create_path("req.req_set.RequirementSet", "7.0.0", "9999")

RequirementTracker = ShimmedPathCollection(
    "RequirementTracker", ImportTypes.CONTEXTMANAGER
)
RequirementTracker.create_path("req.req_tracker.RequirementTracker", "7.0.0", "9999")

TempDirectory = ShimmedPathCollection("TempDirectory", ImportTypes.CLASS)
TempDirectory.create_path("utils.temp_dir.TempDirectory", "7.0.0", "9999")

global_tempdir_manager = ShimmedPathCollection(
    "global_tempdir_manager", ImportTypes.CONTEXTMANAGER
)
global_tempdir_manager.create_path(
    "utils.temp_dir.global_tempdir_manager", "7.0.0", "9999"
)

shim_unpack = ShimmedPathCollection("shim_unpack", ImportTypes.FUNCTION)
shim_unpack.set_default(
    functools.partial(
        compat.shim_unpack,
        unpack_fn=unpack_url,
        downloader_provider=Downloader,
        tempdir_manager_provider=global_tempdir_manager,
    )
)

get_requirement_tracker = ShimmedPathCollection(
    "get_requirement_tracker", ImportTypes.CONTEXTMANAGER
)
get_requirement_tracker.set_default(
    functools.partial(compat.get_requirement_tracker, RequirementTracker.shim())
)
get_requirement_tracker.create_path(
    "req.req_tracker.get_requirement_tracker", "7.0.0", "9999"
)

Resolver = ShimmedPathCollection("Resolver", ImportTypes.CLASS)
Resolver.create_path("resolve.Resolver", "7.0.0", "19.1.1")
Resolver.create_path("legacy_resolve.Resolver", "19.1.2", "20.0.89999")
Resolver.create_path("resolution.legacy.resolver.Resolver", "20.0.99999", "99999")

SafeFileCache = ShimmedPathCollection("SafeFileCache", ImportTypes.CLASS)
SafeFileCache.create_path("network.cache.SafeFileCache", "19.3.0", "9999")
SafeFileCache.create_path("download.SafeFileCache", "7.0.0", "19.2.3")

UninstallPathSet = ShimmedPathCollection("UninstallPathSet", ImportTypes.CLASS)
UninstallPathSet.create_path("req.req_uninstall.UninstallPathSet", "7.0.0", "9999")

url_to_path = ShimmedPathCollection("url_to_path", ImportTypes.FUNCTION)
url_to_path.create_path("download.url_to_path", "7.0.0", "19.2.3")
url_to_path.create_path("utils.urls.url_to_path", "19.3.0", "9999")

USER_CACHE_DIR = ShimmedPathCollection("USER_CACHE_DIR", ImportTypes.ATTRIBUTE)
USER_CACHE_DIR.create_path("locations.USER_CACHE_DIR", "7.0.0", "9999")

VcsSupport = ShimmedPathCollection("VcsSupport", ImportTypes.CLASS)
VcsSupport.create_path("vcs.VcsSupport", "7.0.0", "19.1.1")
VcsSupport.create_path("vcs.versioncontrol.VcsSupport", "19.2", "9999")

Wheel = ShimmedPathCollection("Wheel", ImportTypes.CLASS)
Wheel.create_path("wheel.Wheel", "7.0.0", "19.3.9")
Wheel.set_default(compat.Wheel)

WheelCache = ShimmedPathCollection("WheelCache", ImportTypes.CLASS)
WheelCache.create_path("cache.WheelCache", "10.0.0", "9999")
WheelCache.create_path("wheel.WheelCache", "7", "9.0.3")

WheelBuilder = ShimmedPathCollection("WheelBuilder", ImportTypes.CLASS)
WheelBuilder.create_path("wheel.WheelBuilder", "7.0.0", "19.9")

build = ShimmedPathCollection("build", ImportTypes.FUNCTION)
build.create_path("wheel_builder.build", "19.9", "9999")

build_one = ShimmedPathCollection("build_one", ImportTypes.FUNCTION)
build_one.create_path("wheel_builder._build_one", "19.9", "9999")

build_one_inside_env = ShimmedPathCollection("build_one_inside_env", ImportTypes.FUNCTION)
build_one_inside_env.create_path("wheel_builder._build_one_inside_env", "19.9", "9999")

AbstractDistribution = ShimmedPathCollection("AbstractDistribution", ImportTypes.CLASS)
AbstractDistribution.create_path(
    "distributions.base.AbstractDistribution", "19.1.2", "9999"
)

InstalledDistribution = ShimmedPathCollection("InstalledDistribution", ImportTypes.CLASS)
InstalledDistribution.create_path(
    "distributions.installed.InstalledDistribution", "19.1.2", "9999"
)

SourceDistribution = ShimmedPathCollection("SourceDistribution", ImportTypes.CLASS)
SourceDistribution.create_path("req.req_set.IsSDist", "7.0.0", "9.0.3")
SourceDistribution.create_path("operations.prepare.IsSDist", "10.0.0", "19.1.1")
SourceDistribution.create_path(
    "distributions.source.SourceDistribution", "19.1.2", "19.2.3"
)
SourceDistribution.create_path(
    "distributions.source.legacy.SourceDistribution", "19.3.0", "19.9"
)
SourceDistribution.create_path("distributions.sdist.SourceDistribution", "20.0", "9999")

WheelDistribution = ShimmedPathCollection("WheelDistribution", ImportTypes.CLASS)
WheelDistribution.create_path("distributions.wheel.WheelDistribution", "19.1.2", "9999")

Downloader = ShimmedPathCollection("Downloader", ImportTypes.CLASS)
Downloader.create_path("network.download.Downloader", "20.0.0", "9999")

PyPI = ShimmedPathCollection("PyPI", ImportTypes.ATTRIBUTE)
PyPI.create_path("models.index.PyPI", "7.0.0", "9999")

stdlib_pkgs = ShimmedPathCollection("stdlib_pkgs", ImportTypes.ATTRIBUTE)
stdlib_pkgs.create_path("utils.compat.stdlib_pkgs", "18.1", "9999")
stdlib_pkgs.create_path("compat.stdlib_pkgs", "7", "18.0")

DEV_PKGS = ShimmedPathCollection("DEV_PKGS", ImportTypes.ATTRIBUTE)
DEV_PKGS.create_path("commands.freeze.DEV_PKGS", "9.0.0", "9999")
DEV_PKGS.set_default({"setuptools", "pip", "distribute", "wheel"})


wheel_cache = ShimmedPathCollection("wheel_cache", ImportTypes.FUNCTION)
wheel_cache.set_default(
    functools.partial(
        compat.wheel_cache,
        wheel_cache_provider=WheelCache,
        tempdir_manager_provider=global_tempdir_manager,
        format_control_provider=FormatControl,
    )
)


get_package_finder = ShimmedPathCollection("get_package_finder", ImportTypes.FUNCTION)
get_package_finder.set_default(
    functools.partial(
        compat.get_package_finder,
        install_cmd_provider=InstallCommand,
        target_python_builder=TargetPython.shim(),
    )
)


make_preparer = ShimmedPathCollection("make_preparer", ImportTypes.FUNCTION)
make_preparer.set_default(
    functools.partial(
        compat.make_preparer,
        install_cmd_provider=InstallCommand,
        preparer_fn=RequirementPreparer,
        downloader_provider=Downloader,
        req_tracker_fn=get_requirement_tracker,
        finder_provider=get_package_finder,
    )
)


get_resolver = ShimmedPathCollection("get_resolver", ImportTypes.FUNCTION)
get_resolver.set_default(
    functools.partial(
        compat.get_resolver,
        install_cmd_provider=InstallCommand,
        resolver_fn=Resolver,
        install_req_provider=install_req_from_req_string,
        wheel_cache_provider=wheel_cache,
        format_control_provider=FormatControl,
    )
)


get_requirement_set = ShimmedPathCollection("get_requirement_set", ImportTypes.FUNCTION)
get_requirement_set.set_default(
    functools.partial(
        compat.get_requirement_set,
        install_cmd_provider=InstallCommand,
        req_set_provider=RequirementSet,
        wheel_cache_provider=wheel_cache,
    )
)


resolve = ShimmedPathCollection("resolve", ImportTypes.FUNCTION)
resolve.set_default(
    functools.partial(
        compat.resolve,
        install_cmd_provider=InstallCommand,
        reqset_provider=get_requirement_set,
        finder_provider=get_package_finder,
        resolver_provider=get_resolver,
        wheel_cache_provider=wheel_cache,
        format_control_provider=FormatControl,
        make_preparer_provider=make_preparer,
        req_tracker_provider=get_requirement_tracker,
        tempdir_manager_provider=global_tempdir_manager,
    )
)


build_wheel = ShimmedPathCollection("build_wheel", ImportTypes.FUNCTION)
build_wheel.set_default(
    functools.partial(
        compat.build_wheel,
        install_command_provider=InstallCommand,
        wheel_cache_provider=wheel_cache,
        wheel_builder_provider=WheelBuilder,
        build_one_provider=build_one,
        build_one_inside_env_provider=build_one_inside_env,
        build_many_provider=build,
        preparer_provider=make_preparer,
        format_control_provider=FormatControl,
        reqset_provider=get_requirement_set,
    )
)
