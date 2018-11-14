# -*- coding=utf-8 -*-
from __future__ import absolute_import

import contextlib
import logging
import os

import six
import sys
import tomlkit

six.add_move(six.MovedAttribute("Mapping", "collections", "collections.abc"))
six.add_move(six.MovedAttribute("Sequence", "collections", "collections.abc"))
six.add_move(six.MovedAttribute("Set", "collections", "collections.abc"))
six.add_move(six.MovedAttribute("ItemsView", "collections", "collections.abc"))
from six.moves import Mapping, Sequence, Set, ItemsView
from six.moves.urllib.parse import urlparse, urlsplit

import pip_shims.shims
from vistir.compat import Path
from vistir.path import is_valid_url, ensure_mkdir_p, create_tracked_tempdir


VCS_LIST = ("git", "svn", "hg", "bzr")


def setup_logger():
    logger = logging.getLogger("requirementslib")
    loglevel = logging.DEBUG
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(loglevel)
    logger.addHandler(handler)
    logger.setLevel(loglevel)
    return logger


log = setup_logger()


SCHEME_LIST = ("http://", "https://", "ftp://", "ftps://", "file://")


VCS_SCHEMES = [
    "git",
    "git+http",
    "git+https",
    "git+ssh",
    "git+git",
    "git+file",
    "hg",
    "hg+http",
    "hg+https",
    "hg+ssh",
    "hg+static-http",
    "svn",
    "svn+ssh",
    "svn+http",
    "svn+https",
    "svn+svn",
    "bzr",
    "bzr+http",
    "bzr+https",
    "bzr+ssh",
    "bzr+sftp",
    "bzr+ftp",
    "bzr+lp",
]


def is_installable_dir(path):
    if pip_shims.shims.is_installable_dir(path):
        return True
    path = Path(path)
    pyproject = path.joinpath("pyproject.toml")
    if pyproject.exists():
        pyproject_toml = tomlkit.loads(pyproject.read_text())
        build_system = pyproject_toml.get("build-system", {}).get("build-backend", "")
        if build_system:
            return True
    return False


def strip_ssh_from_git_uri(uri):
    """Return git+ssh:// formatted URI to git+git@ format"""
    if isinstance(uri, six.string_types):
        uri = uri.replace("git+ssh://", "git+", 1)
    return uri


def add_ssh_scheme_to_git_uri(uri):
    """Cleans VCS uris from pipenv.patched.notpip format"""
    if isinstance(uri, six.string_types):
        # Add scheme for parsing purposes, this is also what pip does
        if uri.startswith("git+") and "://" not in uri:
            uri = uri.replace("git+", "git+ssh://", 1)
    return uri


def is_vcs(pipfile_entry):
    """Determine if dictionary entry from Pipfile is for a vcs dependency."""
    if isinstance(pipfile_entry, Mapping):
        return any(key for key in pipfile_entry.keys() if key in VCS_LIST)

    elif isinstance(pipfile_entry, six.string_types):
        if not is_valid_url(pipfile_entry) and pipfile_entry.startswith("git+"):
            pipfile_entry = add_ssh_scheme_to_git_uri(pipfile_entry)

        parsed_entry = urlsplit(pipfile_entry)
        return parsed_entry.scheme in VCS_SCHEMES
    return False


def is_editable(pipfile_entry):
    if isinstance(pipfile_entry, Mapping):
        return pipfile_entry.get("editable", False) is True
    return False


def multi_split(s, split):
    """Splits on multiple given separators."""
    for r in split:
        s = s.replace(r, "|")
    return [i for i in s.split("|") if len(i) > 0]


def is_star(val):
    return (isinstance(val, six.string_types) and val == "*") or (
        isinstance(val, Mapping) and val.get("version", "") == "*"
    )


def is_installable_file(path):
    """Determine if a path can potentially be installed"""
    from packaging import specifiers

    if hasattr(path, "keys") and any(
        key for key in path.keys() if key in ["file", "path"]
    ):
        path = urlparse(path["file"]).path if "file" in path else path["path"]
    if not isinstance(path, six.string_types) or path == "*":
        return False

    # If the string starts with a valid specifier operator, test if it is a valid
    # specifier set before making a path object (to avoid breaking windows)
    if any(path.startswith(spec) for spec in "!=<>~"):
        try:
            specifiers.SpecifierSet(path)
        # If this is not a valid specifier, just move on and try it as a path
        except specifiers.InvalidSpecifier:
            pass
        else:
            return False

    parsed = urlparse(path)
    if parsed.scheme == "file":
        path = parsed.path

    if not os.path.exists(os.path.abspath(path)):
        return False

    lookup_path = Path(path)
    absolute_path = "{0}".format(lookup_path.absolute())
    if lookup_path.is_dir() and is_installable_dir(absolute_path):
        return True

    elif lookup_path.is_file() and pip_shims.shims.is_archive_file(absolute_path):
        return True

    return False


def prepare_pip_source_args(sources, pip_args=None):
    if pip_args is None:
        pip_args = []
    if sources:
        # Add the source to pip9.
        pip_args.extend(["-i", sources[0]["url"]])
        # Trust the host if it's not verified.
        if not sources[0].get("verify_ssl", True):
            pip_args.extend(["--trusted-host", urlparse(sources[0]["url"]).hostname])
        # Add additional sources as extra indexes.
        if len(sources) > 1:
            for source in sources[1:]:
                pip_args.extend(["--extra-index-url", source["url"]])
                # Trust the host if it's not verified.
                if not source.get("verify_ssl", True):
                    pip_args.extend(
                        ["--trusted-host", urlparse(source["url"]).hostname]
                    )
    return pip_args


@ensure_mkdir_p(mode=0o777)
def _ensure_dir(path):
    return path


@contextlib.contextmanager
def ensure_setup_py(base_dir):
    if not base_dir:
        base_dir = create_tracked_tempdir(prefix="requirementslib-setup")
    base_dir = Path(base_dir)
    if base_dir.exists() and base_dir.name == "setup.py":
        base_dir = base_dir.parent
    elif not (base_dir.exists() and base_dir.is_dir()):
        base_dir = base_dir.parent
        if not (base_dir.exists() and base_dir.is_dir()):
            base_dir = base_dir.parent
    setup_py = base_dir.joinpath("setup.py")

    is_new = False if setup_py.exists() else True
    if not setup_py.exists():
        setup_py.write_text(u"")
    try:
        yield
    finally:
        if is_new:
            setup_py.unlink()


_UNSET = object()
_REMAP_EXIT = object()


# The following functionality is either borrowed or modified from the itertools module
# in the boltons library by Mahmoud Hashemi and distributed under the BSD license
# the text of which is included below:

# (original text from https://github.com/mahmoud/boltons/blob/master/LICENSE)
#   Copyright (c) 2013, Mahmoud Hashemi
#
#   Redistribution and use in source and binary forms, with or without
#   modification, are permitted provided that the following conditions are
#   met:
#
#       * Redistributions of source code must retain the above copyright
#         notice, this list of conditions and the following disclaimer.
#
#       * Redistributions in binary form must reproduce the above
#         copyright notice, this list of conditions and the following
#         disclaimer in the documentation and/or other materials provided
#         with the distribution.
#
#       * The names of the contributors may not be used to endorse or
#         promote products derived from this software without specific
#         prior written permission.
#
#
#   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
#   "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
#   LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
#   A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
#   OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
#   SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
#   LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
#   DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
#   THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#   (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#   OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


class PathAccessError(KeyError, IndexError, TypeError):
    """An amalgamation of KeyError, IndexError, and TypeError,
    representing what can occur when looking up a path in a nested
    object.
    """

    def __init__(self, exc, seg, path):
        self.exc = exc
        self.seg = seg
        self.path = path

    def __repr__(self):
        cn = self.__class__.__name__
        return "%s(%r, %r, %r)" % (cn, self.exc, self.seg, self.path)

    def __str__(self):
        return "could not access %r from path %r, got error: %r" % (
            self.seg,
            self.path,
            self.exc,
        )


def get_path(root, path, default=_UNSET):
    """Retrieve a value from a nested object via a tuple representing the
    lookup path.
    >>> root = {'a': {'b': {'c': [[1], [2], [3]]}}}
    >>> get_path(root, ('a', 'b', 'c', 2, 0))
    3
    The path format is intentionally consistent with that of
    :func:`remap`.
    One of get_path's chief aims is improved error messaging. EAFP is
    great, but the error messages are not.
    For instance, ``root['a']['b']['c'][2][1]`` gives back
    ``IndexError: list index out of range``
    What went out of range where? get_path currently raises
    ``PathAccessError: could not access 2 from path ('a', 'b', 'c', 2,
    1), got error: IndexError('list index out of range',)``, a
    subclass of IndexError and KeyError.
    You can also pass a default that covers the entire operation,
    should the lookup fail at any level.
    Args:
       root: The target nesting of dictionaries, lists, or other
          objects supporting ``__getitem__``.
       path (tuple): A list of strings and integers to be successively
          looked up within *root*.
       default: The value to be returned should any
          ``PathAccessError`` exceptions be raised.
    """
    if isinstance(path, six.string_types):
        path = path.split(".")
    cur = root
    try:
        for seg in path:
            try:
                cur = cur[seg]
            except (KeyError, IndexError) as exc:
                raise PathAccessError(exc, seg, path)
            except TypeError as exc:
                # either string index in a list, or a parent that
                # doesn't support indexing
                try:
                    seg = int(seg)
                    cur = cur[seg]
                except (ValueError, KeyError, IndexError, TypeError):
                    if not getattr(cur, "__iter__", None):
                        exc = TypeError(
                            "%r object is not indexable" % type(cur).__name__
                        )
                    raise PathAccessError(exc, seg, path)
    except PathAccessError:
        if default is _UNSET:
            raise
        return default
    return cur


def default_visit(path, key, value):
    return key, value


_orig_default_visit = default_visit


# Modified from https://github.com/mahmoud/boltons/blob/master/boltons/iterutils.py
def dict_path_enter(path, key, value):
    if isinstance(value, six.string_types):
        return value, False
    elif isinstance(value, (Mapping, dict)):
        return value.__class__(), ItemsView(value)
    elif isinstance(value, tomlkit.items.Array):
        return value.__class__([], value.trivia), enumerate(value)
    elif isinstance(value, (Sequence, list)):
        return value.__class__(), enumerate(value)
    elif isinstance(value, (Set, set)):
        return value.__class__(), enumerate(value)
    else:
        return value, False


def dict_path_exit(path, key, old_parent, new_parent, new_items):
    ret = new_parent
    if isinstance(new_parent, (Mapping, dict)):
        vals = dict(new_items)
        try:
            new_parent.update(new_items)
        except AttributeError:
            # Handle toml containers specifically
            try:
                new_parent.update(vals)
            # Now use default fallback if needed
            except AttributeError:
                ret = new_parent.__class__(vals)
    elif isinstance(new_parent, tomlkit.items.Array):
        vals = tomlkit.items.item([v for i, v in new_items])
        try:
            new_parent._value.extend(vals._value)
        except AttributeError:
            ret = tomlkit.items.item(vals)
    elif isinstance(new_parent, (Sequence, list)):
        vals = [v for i, v in new_items]
        try:
            new_parent.extend(vals)
        except AttributeError:
            ret = new_parent.__class__(vals)  # tuples
    elif isinstance(new_parent, (Set, set)):
        vals = [v for i, v in new_items]
        try:
            new_parent.update(vals)
        except AttributeError:
            ret = new_parent.__class__(vals)  # frozensets
    else:
        raise RuntimeError("unexpected iterable type: %r" % type(new_parent))
    return ret


def remap(
    root, visit=default_visit, enter=dict_path_enter, exit=dict_path_exit, **kwargs
):
    """The remap ("recursive map") function is used to traverse and
    transform nested structures. Lists, tuples, sets, and dictionaries
    are just a few of the data structures nested into heterogenous
    tree-like structures that are so common in programming.
    Unfortunately, Python's built-in ways to manipulate collections
    are almost all flat. List comprehensions may be fast and succinct,
    but they do not recurse, making it tedious to apply quick changes
    or complex transforms to real-world data.
    remap goes where list comprehensions cannot.
    Here's an example of removing all Nones from some data:
    >>> from pprint import pprint
    >>> reviews = {'Star Trek': {'TNG': 10, 'DS9': 8.5, 'ENT': None},
    ...            'Babylon 5': 6, 'Dr. Who': None}
    >>> pprint(remap(reviews, lambda p, k, v: v is not None))
    {'Babylon 5': 6, 'Star Trek': {'DS9': 8.5, 'TNG': 10}}
    Notice how both Nones have been removed despite the nesting in the
    dictionary. Not bad for a one-liner, and that's just the beginning.
    See `this remap cookbook`_ for more delicious recipes.
    .. _this remap cookbook: http://sedimental.org/remap.html
    remap takes four main arguments: the object to traverse and three
    optional callables which determine how the remapped object will be
    created.
    Args:
        root: The target object to traverse. By default, remap
            supports iterables like :class:`list`, :class:`tuple`,
            :class:`dict`, and :class:`set`, but any object traversable by
            *enter* will work.
        visit (callable): This function is called on every item in
            *root*. It must accept three positional arguments, *path*,
            *key*, and *value*. *path* is simply a tuple of parents'
            keys. *visit* should return the new key-value pair. It may
            also return ``True`` as shorthand to keep the old item
            unmodified, or ``False`` to drop the item from the new
            structure. *visit* is called after *enter*, on the new parent.
            The *visit* function is called for every item in root,
            including duplicate items. For traversable values, it is
            called on the new parent object, after all its children
            have been visited. The default visit behavior simply
            returns the key-value pair unmodified.
        enter (callable): This function controls which items in *root*
            are traversed. It accepts the same arguments as *visit*: the
            path, the key, and the value of the current item. It returns a
            pair of the blank new parent, and an iterator over the items
            which should be visited. If ``False`` is returned instead of
            an iterator, the value will not be traversed.
            The *enter* function is only called once per unique value. The
            default enter behavior support mappings, sequences, and
            sets. Strings and all other iterables will not be traversed.
        exit (callable): This function determines how to handle items
            once they have been visited. It gets the same three
            arguments as the other functions -- *path*, *key*, *value*
            -- plus two more: the blank new parent object returned
            from *enter*, and a list of the new items, as remapped by
            *visit*.
            Like *enter*, the *exit* function is only called once per
            unique value. The default exit behavior is to simply add
            all new items to the new parent, e.g., using
            :meth:`list.extend` and :meth:`dict.update` to add to the
            new parent. Immutable objects, such as a :class:`tuple` or
            :class:`namedtuple`, must be recreated from scratch, but
            use the same type as the new parent passed back from the
            *enter* function.
        reraise_visit (bool): A pragmatic convenience for the *visit*
            callable. When set to ``False``, remap ignores any errors
            raised by the *visit* callback. Items causing exceptions
            are kept. See examples for more details.
    remap is designed to cover the majority of cases with just the
    *visit* callable. While passing in multiple callables is very
    empowering, remap is designed so very few cases should require
    passing more than one function.
    When passing *enter* and *exit*, it's common and easiest to build
    on the default behavior. Simply add ``from boltons.iterutils import
    default_enter`` (or ``default_exit``), and have your enter/exit
    function call the default behavior before or after your custom
    logic. See `this example`_.
    Duplicate and self-referential objects (aka reference loops) are
    automatically handled internally, `as shown here`_.
    .. _this example: http://sedimental.org/remap.html#sort_all_lists
    .. _as shown here: http://sedimental.org/remap.html#corner_cases
    """
    # TODO: improve argument formatting in sphinx doc
    # TODO: enter() return (False, items) to continue traverse but cancel copy?
    if not callable(visit):
        raise TypeError("visit expected callable, not: %r" % visit)
    if not callable(enter):
        raise TypeError("enter expected callable, not: %r" % enter)
    if not callable(exit):
        raise TypeError("exit expected callable, not: %r" % exit)
    reraise_visit = kwargs.pop("reraise_visit", True)
    if kwargs:
        raise TypeError("unexpected keyword arguments: %r" % kwargs.keys())

    path, registry, stack = (), {}, [(None, root)]
    new_items_stack = []
    while stack:
        key, value = stack.pop()
        id_value = id(value)
        if key is _REMAP_EXIT:
            key, new_parent, old_parent = value
            id_value = id(old_parent)
            path, new_items = new_items_stack.pop()
            value = exit(path, key, old_parent, new_parent, new_items)
            registry[id_value] = value
            if not new_items_stack:
                continue
        elif id_value in registry:
            value = registry[id_value]
        else:
            res = enter(path, key, value)
            try:
                new_parent, new_items = res
            except TypeError:
                # TODO: handle False?
                raise TypeError(
                    "enter should return a tuple of (new_parent,"
                    " items_iterator), not: %r" % res
                )
            if new_items is not False:
                # traverse unless False is explicitly passed
                registry[id_value] = new_parent
                new_items_stack.append((path, []))
                if value is not root:
                    path += (key,)
                stack.append((_REMAP_EXIT, (key, new_parent, value)))
                if new_items:
                    stack.extend(reversed(list(new_items)))
                continue
        if visit is _orig_default_visit:
            # avoid function call overhead by inlining identity operation
            visited_item = (key, value)
        else:
            try:
                visited_item = visit(path, key, value)
            except Exception:
                if reraise_visit:
                    raise
                visited_item = True
            if visited_item is False:
                continue  # drop
            elif visited_item is True:
                visited_item = (key, value)
            # TODO: typecheck?
            #    raise TypeError('expected (key, value) from visit(),'
            #                    ' not: %r' % visited_item)
        try:
            new_items_stack[-1][1].append(visited_item)
        except IndexError:
            raise TypeError("expected remappable root, not: %r" % root)
    return value


def merge_items(target_list, sourced=False):
    if not sourced:
        target_list = [(id(t), t) for t in target_list]

    ret = None
    source_map = {}

    def remerge_enter(path, key, value):
        new_parent, new_items = dict_path_enter(path, key, value)
        if ret and not path and key is None:
            new_parent = ret

        try:
            cur_val = get_path(ret, path + (key,))
        except KeyError as ke:
            pass
        else:
            new_parent = cur_val

        return new_parent, new_items

    def remerge_exit(path, key, old_parent, new_parent, new_items):
        return dict_path_exit(path, key, old_parent, new_parent, new_items)

    for t_name, target in target_list:
        if sourced:

            def remerge_visit(path, key, value):
                source_map[path + (key,)] = t_name
                return True

        else:
            remerge_visit = default_visit

        ret = remap(target, enter=remerge_enter, visit=remerge_visit, exit=remerge_exit)

    if not sourced:
        return ret
    return ret, source_map
