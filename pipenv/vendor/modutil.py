"""Help for working with modules."""
__version__ = "2.0.0"

import importlib
import importlib.machinery
import importlib.util
import types


STANDARD_MODULE_ATTRS = frozenset(['__all__', '__builtins__', '__cached__',
                                   '__doc__', '__file__', '__loader__',
                                   '__name__', '__package__', '__spec__',
                                   '__getattr__'])


class ModuleAttributeError(AttributeError):
    """An AttributeError specifically for modules.

    The module_name and 'attribute' attributes are set to strings representing
    the module the attribute was searched on and the missing attribute,
    respectively.

    """

    def __init__(self, module_name, attribute):
        self.module_name = module_name
        self.attribute = attribute
        super().__init__(f"module {module_name!r} has no attribute {attribute!r}")



def lazy_import(module_name, to_import):
    """Return the importing module and a callable for lazy importing.

    The module named by module_name represents the module performing the
    import to help facilitate resolving relative imports.

    to_import is an iterable of the modules to be potentially imported (absolute
    or relative). The `as` form of importing is also supported,
    e.g. `pkg.mod as spam`.

    This function returns a tuple of two items. The first is the importer
    module for easy reference within itself. The second item is a callable to be
    set to `__getattr__`.
    """
    module = importlib.import_module(module_name)
    import_mapping = {}
    for name in to_import:
        importing, _, binding = name.partition(' as ')
        if not binding:
            _, _, binding = importing.rpartition('.')
        import_mapping[binding] = importing

    def __getattr__(name):
        if name not in import_mapping:
            raise ModuleAttributeError(module_name, name)
        importing = import_mapping[name]
        # imortlib.import_module() implicitly sets submodules on this module as
        # appropriate for direct imports.
        imported = importlib.import_module(importing,
                                           module.__spec__.parent)
        setattr(module, name, imported)
        return imported

    return module, __getattr__


def filtered_attrs(module, *, modules=False, private=False, dunder=False,
                   common=False):
    """Return a collection of attributes on 'module'.

    If 'modules' is false then module instances are excluded. If 'private' is
    false then attributes starting with, but not ending in, '_' will be
    excluded. With 'dunder' set to false then attributes starting and ending
    with '_' are left out. The 'common' argument controls whether attributes
    found in STANDARD_MODULE_ATTRS are returned.

    """
    attr_names = set()
    for name, value in module.__dict__.items():
        if not common and name in STANDARD_MODULE_ATTRS:
            continue
        if name.startswith('_'):
            if name.endswith('_'):
                if not dunder:
                    continue
            elif not private:
                continue
        if not modules and isinstance(value, types.ModuleType):
            continue
        attr_names.add(name)
    return frozenset(attr_names)


def calc___all__(module_name, **kwargs):
    """Return a sorted list of defined attributes on 'module_name'.

    All values specified in **kwargs are directly passed to filtered_attrs().

    """
    module = importlib.import_module(module_name)
    return sorted(filtered_attrs(module, **kwargs))


def filtered_dir(module_name, *, additions={}, **kwargs):
    """Return a callable appropriate for __dir__().

    All values specified in **kwargs get passed directly to filtered_attrs().
    The 'additions' argument should be an iterable which is added to the final
    results.

    """
    module = importlib.import_module(module_name)

    def __dir__():
        attr_names = set(filtered_attrs(module, **kwargs))
        attr_names.update(additions)
        return sorted(attr_names)

    return __dir__


def chained___getattr__(module_name, *getattrs):
    """Create a callable which calls each __getattr__ in sequence.

    Any raised ModuleAttributeError which matches module_name and the
    attribute being searched for will be caught and the search will continue.
    All other exceptions will be allowed to propagate. If no callable
    successfully returns a value, ModuleAttributeError will be raised.

    """
    def __getattr__(name):
        """Call each __getattr__ function in sequence."""
        for getattr_ in getattrs:
            try:
                return getattr_(name)
            except ModuleAttributeError as exc:
                if exc.module_name == module_name and exc.attribute == name:
                    continue
                else:
                    raise
        else:
            raise ModuleAttributeError(module_name, name)

    return __getattr__
