import logging
import functools
import importlib
import collections


MEMOIZED_CLASSES = [
    '.patched.notpip._vendor.packaging.version.Version',
    # 'pkg_resources.extern.packaging.version.Version',
]
MEMOIZED_METHODS = [
    '.patched.notpip._internal.index.PackageFinder._link_package_versions',
    # '.patched.notpip._internal.index.PackageFinder.find_all_candidates',
]
MEMOIZED_FUNCTIONS = [
    # 'urllib.parse.urlsplit',
    # 'urllib.parse._splitnetloc',
    # 'urllib.parse._coerce_args',
    # 'urllib.parse._noop',
]


class Statistic:

    def __init__(self):
        self.calls = 0
        self.from_call = 0
        self.from_cache = 0
        self.from_exception = 0

    def __repr__(self):
        if self.calls:
            ratio = 100. * (self.calls - self.from_call) / self.calls
        else:
            ratio = 100

        return '''
        <Statistic: %d calls, %d real, %d cached, %d exceptions, ratio: %.1f%%>
        '''.strip() % (self.calls, self.from_call, self.from_cache,
                       self.from_exception, ratio)


package = __name__.split('.', 1)[0]
stats = collections.defaultdict(Statistic)


def get_object(module_name, object_name=None):
    if not object_name:
        # Split the import from the actual object
        module_name, object_name = module_name.rsplit('.', 1)

    # Import the module from the current package
    module = importlib.import_module(module_name, package)

    # Fetch the object from the module
    object_ = getattr(module, object_name)

    return module_name, object_name, module, object_


def memoize_class(name,
                  keyfunc=lambda s, *a, **kw: str(a) + str(kw),
                  valuefunc=lambda s, *a, **kw: s.__dict__):
    module_name, class_name, _, class_ = get_object(name)

    # Make sure not to re-patch classes
    if hasattr(class_, '_original_init'):
        logging.warning('Cannot patch %s.%s, it has already been patched',
                        module_name, class_name)
        return

    # Wrapping the method with the original docs and such
    @functools.wraps(class_.__init__)
    def cached_init(self, *args, **kwargs):
        # Generate the cache key from the given arguments
        cache_key = keyfunc(self, *args, **kwargs)
        stats[name].calls += 1

        # insert/raise the value or exception from the cache respectively.
        # Or execute and store the value/exception if no cache is available.
        if cache_key in cache:
            stats[name].from_cache += 1
            self.__dict__.update(cache[cache_key])
        elif cache_key in exception_cache:
            stats[name].from_exception += 1
            raise exception_cache[cache_key]
        else:
            try:
                stats[name].from_call += 1
                self._original_init(*args, **kwargs)
                cache[cache_key] = valuefunc(self, *args, **kwargs)
            except Exception as exception:
                exception_cache[cache_key] = exception
                raise

    # Create the cache and overwrite the original method
    cache = dict()
    exception_cache = dict()
    class_._original_init = class_.__init__
    class_.__init__ = cached_init


def memoize_function(name,
                     keyfunc=lambda *a, **kw: str(a) + str(kw),
                     valuefunc=lambda f, *a, **kw: f(*a, **kw)):
    module_name, function_name, module, function = get_object(name)
    original_function_name = '_original_%s' % function_name

    # Make sure not to re-patch classes
    if hasattr(module, original_function_name):
        logging.warning('Cannot patch %s.%s, it has already been patched',
                        module_name, function_name)
        return

    # Wrapping the function with the original docs and such
    @functools.wraps(function)
    def cached(*args, **kwargs):
        # Generate the cache key from the given arguments
        cache_key = keyfunc(*args, **kwargs)
        stats[name].calls += 1

        # insert/raise the value or exception from the cache respectively.
        # Or execute and store the value/exception if no cache is available.
        if cache_key in cache:
            stats[name].from_cache += 1
            value = cache[cache_key]
        elif cache_key in exception_cache:
            stats[name].from_exception += 1
            raise exception_cache[cache_key]
        else:
            try:
                stats[name].from_call += 1
                value = cache[cache_key] = valuefunc(function, *args, **kwargs)
            except Exception as exception:
                exception_cache[cache_key] = exception
                raise

        return value

    # Create the cache and overwrite the original function
    cache = dict()
    exception_cache = dict()
    setattr(module, original_function_name, function)
    setattr(module, function_name, cached)


def memoize_method(name,
                   keyfunc=lambda s, *a, **kw: str(a) + str(kw),
                   valuefunc=lambda f, *a, **kw: f(*a, **kw)):
    class_name, function_name = name.rsplit('.', 1)
    module_name, class_name, _, class_ = get_object(class_name)
    function = getattr(class_, function_name)
    original_function_name = '_original_%s' % function_name

    # Make sure not to re-patch classes
    if hasattr(class_, original_function_name):
        logging.warning('Cannot patch %s.%s.%s, it has already been patched',
                        module_name, class_name, function_name)
        return

    # Wrapping the function with the original docs and such
    # @functools.wraps(function)
    def cached(self, *args, **kwargs):
        # Generate the cache key from the given arguments
        cache_key = keyfunc(self, *args, **kwargs)
        stats[name].calls += 1

        # insert/raise the value or exception from the cache respectively.
        # Or execute and store the value/exception if no cache is available.
        if cache_key in cache:
            stats[name].from_cache += 1
            value = cache[cache_key]
        elif cache_key in exception_cache:
            stats[name].from_exception += 1
            raise exception_cache[cache_key]
        else:
            try:
                stats[name].from_call += 1
                value = cache[cache_key] = valuefunc(
                    function, self, *args, **kwargs)
            except Exception as exception:
                exception_cache[cache_key] = exception
                raise

        return value

    # Create the cache and overwrite the original function
    cache = dict()
    exception_cache = dict()
    setattr(class_, original_function_name, function)
    setattr(class_, function_name, cached)


def monkeypatch_html_page():
    from pipenv.patched.notpip._internal import index

    def keyfunc(self):
        transport_encoding = index._get_encoding_from_headers(self.headers)
        return self.content, transport_encoding, self.url

    def valuefunc(method, self, *args, **kwargs):
        return list(method(self, *args, **kwargs))

    index.HTMLPage.cache_enabled = True
    memoize_method(
        'pipenv.patched.notpip._internal.index.HTMLPage.iter_links',
        keyfunc, valuefunc)

    # memoize_method(
    #     'pipenv.patched.notpip._internal.index.PackageFinder._get_pages',
    #     valuefunc=valuefunc)


def init():
    for class_ in MEMOIZED_CLASSES:
        memoize_class(class_)
    for method in MEMOIZED_METHODS:
        memoize_method(method)
    for function in MEMOIZED_FUNCTIONS:
        memoize_function(function)

    monkeypatch_html_page()
