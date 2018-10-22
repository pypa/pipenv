# -*- coding=utf-8 -*-
from __future__ import absolute_import

import contextlib
import logging
import os

import boltons.iterutils
import six
import tomlkit

six.add_move(six.MovedAttribute("Mapping", "collections", "collections.abc"))
six.add_move(six.MovedAttribute("Sequence", "collections", "collections.abc"))
six.add_move(six.MovedAttribute("Set", "collections", "collections.abc"))
six.add_move(six.MovedAttribute("ItemsView", "collections", "collections.abc"))
from six.moves import Mapping, Sequence, Set, ItemsView
from six.moves.urllib.parse import urlparse, urlsplit

from pip_shims.shims import (
    Command, VcsSupport, cmdoptions, is_archive_file,
    is_installable_dir as _is_installable_dir
)
from vistir.compat import Path
from vistir.path import is_valid_url, ensure_mkdir_p, create_tracked_tempdir




VCS_LIST = ("git", "svn", "hg", "bzr")
VCS_SCHEMES = []
SCHEME_LIST = ("http://", "https://", "ftp://", "ftps://", "file://")

if not VCS_SCHEMES:
    VCS_SCHEMES = VcsSupport().all_schemes


def setup_logger():
    logger = logging.getLogger("requirementslib")
    loglevel = logging.DEBUG
    handler = logging.StreamHandler()
    handler.setLevel(loglevel)
    logger.addHandler(handler)
    logger.setLevel(loglevel)
    return logger


log = setup_logger()


def is_installable_dir(path):
    if _is_installable_dir(path):
        return True
    path = Path(path)
    pyproject = path.joinpath("pyproject.toml")
    if pyproject.exists():
        pyproject_toml = tomlkit.loads(pyproject.read_text())
        build_system = pyproject_toml.get("build-system", {}).get("build-backend", "")
        if build_system:
            return True
    return False


def is_vcs(pipfile_entry):
    """Determine if dictionary entry from Pipfile is for a vcs dependency."""
    if hasattr(pipfile_entry, "keys"):
        return any(key for key in pipfile_entry.keys() if key in VCS_LIST)

    elif isinstance(pipfile_entry, six.string_types):
        if not is_valid_url(pipfile_entry) and pipfile_entry.startswith("git+"):
            from .models.utils import add_ssh_scheme_to_git_uri
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
    return isinstance(val, six.string_types) and val == "*"


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

    elif lookup_path.is_file() and is_archive_file(absolute_path):
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
            pip_args.extend(
                ["--trusted-host", urlparse(sources[0]["url"]).hostname]
            )
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


class PipCommand(Command):
    name = 'PipCommand'


def get_pip_command():
    # Use pip's parser for pip.conf management and defaults.
    # General options (find_links, index_url, extra_index_url, trusted_host,
    # and pre) are defered to pip.
    import optparse
    pip_command = PipCommand()
    pip_command.parser.add_option(cmdoptions.no_binary())
    pip_command.parser.add_option(cmdoptions.only_binary())
    index_opts = cmdoptions.make_option_group(
        cmdoptions.index_group,
        pip_command.parser,
    )
    pip_command.parser.insert_option_group(0, index_opts)
    pip_command.parser.add_option(optparse.Option('--pre', action='store_true', default=False))

    return pip_command


@ensure_mkdir_p(mode=0o777)
def _ensure_dir(path):
    return path


@contextlib.contextmanager
def ensure_setup_py(base_dir):
    if not base_dir:
        base_dir = create_tracked_tempdir(prefix="requirementslib-setup")
    base_dir = Path(base_dir)
    setup_py = base_dir.joinpath("setup.py")
    is_new = False if setup_py.exists() else True
    if not setup_py.exists():
        setup_py.write_text(u"")
    try:
        yield
    finally:
        if is_new:
            setup_py.unlink()


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
        raise RuntimeError('unexpected iterable type: %r' % type(new_parent))
    return ret


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
            cur_val = boltons.iterutils.get_path(ret, path + (key,))
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
            remerge_visit = boltons.iterutils.default_visit

        ret = boltons.iterutils.remap(target, enter=remerge_enter, visit=remerge_visit,
                    exit=remerge_exit)

    if not sourced:
        return ret
    return ret, source_map
