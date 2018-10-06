# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

import contextlib
import io
import itertools
import distutils.log
import os

import distlib.database
import distlib.scripts
import distlib.wheel
import packaging.utils
import pip_shims
import setuptools.dist
import six
import vistir

from ..models.caches import CACHE_DIR
from ._pip_shims import VCS_SUPPORT, build_wheel as _build_wheel, unpack_url
from .utils import filter_sources


@vistir.path.ensure_mkdir_p(mode=0o775)
def _get_src_dir():
    src = os.environ.get("PIP_SRC")
    if src:
        return src
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        return os.path.join(virtual_env, "src")
    return os.path.join(os.getcwd(), "src")     # Match pip's behavior.


def _prepare_wheel_building_kwargs(ireq):
    download_dir = os.path.join(CACHE_DIR, "pkgs")
    vistir.mkdir_p(download_dir)

    wheel_download_dir = os.path.join(CACHE_DIR, "wheels")
    vistir.mkdir_p(wheel_download_dir)

    if ireq.source_dir is not None:
        src_dir = ireq.source_dir
    elif ireq.editable:
        src_dir = _get_src_dir()
    else:
        src_dir = vistir.path.create_tracked_tempdir(prefix='passa-src')

    # This logic matches pip's behavior, although I don't fully understand the
    # intention. I guess the idea is to build editables in-place, otherwise out
    # of the source tree?
    if ireq.editable:
        build_dir = src_dir
    else:
        build_dir = vistir.path.create_tracked_tempdir(prefix="passa-build")

    return {
        "build_dir": build_dir,
        "src_dir": src_dir,
        "download_dir": download_dir,
        "wheel_download_dir": wheel_download_dir,
    }


def _get_pip_index_urls(sources):
    index_urls = []
    trusted_hosts = []
    for source in sources:
        url = source.get("url")
        if not url:
            continue
        index_urls.append(url)
        if source.get("verify_ssl", True):
            continue
        host = six.moves.urllib.parse.urlparse(source["url"]).hostname
        trusted_hosts.append(host)
    return index_urls, trusted_hosts


class _PipCommand(pip_shims.Command):
    name = "PipCommand"


def _get_pip_session(trusted_hosts):
    cmd = _PipCommand()
    options, _ = cmd.parser.parse_args([])
    options.cache_dir = CACHE_DIR
    options.trusted_hosts = trusted_hosts
    session = cmd._build_session(options)
    return session


def _get_finder(sources):
    index_urls, trusted_hosts = _get_pip_index_urls(sources)
    session = _get_pip_session(trusted_hosts)
    finder = pip_shims.PackageFinder(
        find_links=[],
        index_urls=index_urls,
        trusted_hosts=trusted_hosts,
        allow_all_prereleases=True,
        session=session,
    )
    return finder


def _get_wheel_cache():
    format_control = pip_shims.FormatControl(set(), set())
    wheel_cache = pip_shims.WheelCache(CACHE_DIR, format_control)
    return wheel_cache


def _convert_hashes(values):
    """Convert Pipfile.lock hash lines into InstallRequirement option format.

    The option format uses a str-list mapping. Keys are hash algorithms, and
    the list contains all values of that algorithm.
    """
    hashes = {}
    if not values:
        return hashes
    for value in values:
        try:
            name, value = value.split(":", 1)
        except ValueError:
            name = "sha256"
        if name not in hashes:
            hashes[name] = []
        hashes[name].append(value)
    return hashes


class WheelBuildError(RuntimeError):
    pass


def build_wheel(ireq, sources, hashes=None):
    """Build a wheel file for the InstallRequirement object.

    An artifact is downloaded (or read from cache). If the artifact is not a
    wheel, build one out of it. The dynamically built wheel is ephemeral; do
    not depend on its existence after the returned wheel goes out of scope.

    If `hashes` is truthy, it is assumed to be a list of hashes (as formatted
    in Pipfile.lock) to be checked against the download.

    Returns a `distlib.wheel.Wheel` instance. Raises a `WheelBuildError` (a
    `RuntimeError` subclass) if the wheel cannot be built.
    """
    kwargs = _prepare_wheel_building_kwargs(ireq)
    finder = _get_finder(sources)

    # Not for upgrade, hash not required. Hashes are not required here even
    # when we provide them, because pip skips local wheel cache if we set it
    # to True. Hashes are checked later if we need to download the file.
    ireq.populate_link(finder, False, False)

    # Ensure ireq.source_dir is set.
    # This is intentionally set to build_dir, not src_dir. Comments from pip:
    #   [...] if filesystem packages are not marked editable in a req, a non
    #   deterministic error occurs when the script attempts to unpack the
    #   build directory.
    # Also see comments in `_prepare_wheel_building_kwargs()` -- If the ireq
    # is editable, build_dir is actually src_dir, making the build in-place.
    ireq.ensure_has_source_dir(kwargs["build_dir"])

    # Ensure the source is fetched. For wheels, it is enough to just download
    # because we'll use them directly. For an sdist, we need to unpack so we
    # can build it.
    if not ireq.editable or not pip_shims.is_file_url(ireq.link):
        if ireq.is_wheel:
            only_download = True
            download_dir = kwargs["wheel_download_dir"]
        else:
            only_download = False
            download_dir = kwargs["download_dir"]
        ireq.options["hashes"] = _convert_hashes(hashes)
        unpack_url(
            ireq.link, ireq.source_dir, download_dir,
            only_download=only_download, session=finder.session,
            hashes=ireq.hashes(False), progress_bar="off",
        )

    if ireq.is_wheel:
        # If this is a wheel, use the downloaded thing.
        output_dir = kwargs["wheel_download_dir"]
        wheel_path = os.path.join(output_dir, ireq.link.filename)
    else:
        # Othereise we need to build an ephemeral wheel.
        wheel_path = _build_wheel(
            ireq, vistir.path.create_tracked_tempdir(prefix="ephem"),
            finder, _get_wheel_cache(), kwargs,
        )
        if wheel_path is None or not os.path.exists(wheel_path):
            raise WheelBuildError
    return distlib.wheel.Wheel(wheel_path)


def _obtrain_ref(vcs_obj, src_dir, name, rev=None):
    target_dir = os.path.join(src_dir, name)
    target_rev = vcs_obj.make_rev_options(rev)
    if not os.path.exists(target_dir):
        vcs_obj.obtain(target_dir)
    if (not vcs_obj.is_commit_id_equal(target_dir, rev) and
            not vcs_obj.is_commit_id_equal(target_dir, target_rev)):
        vcs_obj.update(target_dir, target_rev)
    return vcs_obj.get_revision(target_dir)


def get_vcs_ref(requirement):
    backend = VCS_SUPPORT.get_backend(requirement.vcs)
    vcs = backend(url=requirement.req.vcs_uri)
    src = _get_src_dir()
    name = requirement.normalized_name
    ref = _obtrain_ref(vcs, src, name, rev=requirement.req.ref)
    return ref


def find_installation_candidates(ireq, sources):
    finder = _get_finder(sources)
    return finder.find_all_candidates(ireq.name)


class RequirementUninstaller(object):
    """A context manager to remove a package for the inner block.

    This uses `UninstallPathSet` to control the workflow. If the inner block
    exits correctly, the uninstallation is committed, otherwise rolled back.
    """
    def __init__(self, ireq, auto_confirm, verbose):
        self.ireq = ireq
        self.pathset = None
        self.auto_confirm = auto_confirm
        self.verbose = verbose

    def __enter__(self):
        self.pathset = self.ireq.uninstall(
            auto_confirm=self.auto_confirm,
            verbose=self.verbose,
        )
        return self.pathset

    def __exit__(self, exc_type, exc_value, traceback):
        if self.pathset is None:
            return
        if exc_type is None:
            self.pathset.commit()
        else:
            self.pathset.rollback()


def uninstall(name, **kwargs):
    ireq = pip_shims.InstallRequirement.from_line(name)
    return RequirementUninstaller(ireq, **kwargs)


@contextlib.contextmanager
def _suppress_distutils_logs():
    """Hack to hide noise generated by `setup.py develop`.

    There isn't a good way to suppress them now, so let's monky-patch.
    See https://bugs.python.org/issue25392.
    """
    f = distutils.log.Log._log

    def _log(log, level, msg, args):
        if level >= distutils.log.ERROR:
            f(log, level, msg, args)

    distutils.log.Log._log = _log
    yield
    distutils.log.Log._log = f


class NoopInstaller(object):
    """An installer.

    This class is not designed to be instantiated by itself, but used as a
    common interface for subclassing.

    An installer has two methods, `prepare()` and `install()`. Neither takes
    arguments, and should be called in that order to prepare an installation
    operation, and to actually install things.
    """
    def prepare(self):
        pass

    def install(self):
        pass


class EditableInstaller(NoopInstaller):
    """Installer to handle editable.
    """
    def __init__(self, requirement):
        ireq = requirement.as_ireq()
        self.working_directory = ireq.setup_py_dir
        self.setup_py = ireq.setup_py

    def install(self):
        with vistir.cd(self.working_directory), _suppress_distutils_logs():
            # Access from Setuptools to ensure things are patched correctly.
            setuptools.dist.distutils.core.run_setup(
                self.setup_py, ["develop", "--no-deps"],
            )


class WheelInstaller(NoopInstaller):
    """Installer by building a wheel.

    The wheel is built during `prepare()`, and installed in `install()`.
    """
    def __init__(self, requirement, sources, paths):
        self.ireq = requirement.as_ireq()
        self.sources = filter_sources(requirement, sources)
        self.hashes = requirement.hashes or None
        self.paths = paths
        self.wheel = None

    def prepare(self):
        self.wheel = build_wheel(self.ireq, self.sources, self.hashes)

    def install(self):
        self.wheel.install(self.paths, distlib.scripts.ScriptMaker(None, None))


def _iter_egg_info_directories(root, name):
    name = packaging.utils.canonicalize_name(name)
    for parent, dirnames, filenames in os.walk(root):
        matched_indexes = []
        for i, dirname in enumerate(dirnames):
            if not dirname.lower().endswith("egg-info"):
                continue
            egg_info_name = packaging.utils.canonicalize_name(dirname[:-9])
            if egg_info_name != name:
                continue
            matched_indexes.append(i)
            yield os.path.join(parent, dirname)

        # Modify dirnames in-place to NOT look into egg-info directories.
        # This is a documented behavior in stdlib.
        for i in reversed(matched_indexes):
            del dirnames[i]


def _read_pkg_info(directory):
    path = os.path.join(directory, "PKG-INFO")
    try:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except (IOError, OSError):
        return None


def _find_egg_info(ireq):
    """Find this package's .egg-info directory.

    Due to how sdists are designed, the .egg-info directory cannot be reliably
    found without running setup.py to aggregate all configurations. This
    function instead uses some heuristics to locate the egg-info directory
    that most likely represents this package.

    The best .egg-info directory's path is returned as a string. None is
    returned if no matches can be found.
    """
    root = ireq.setup_py_dir

    directory_iterator = _iter_egg_info_directories(root, ireq.name)
    try:
        top_egg_info = next(directory_iterator)
    except StopIteration:   # No egg-info found. Wat.
        return None
    directory_iterator = itertools.chain([top_egg_info], directory_iterator)

    # Read the sdist's PKG-INFO to determine which egg_info is best.
    pkg_info = _read_pkg_info(root)

    # PKG-INFO not readable. Just return whatever comes first, I guess.
    if pkg_info is None:
        return top_egg_info

    # Walk the sdist to find the egg-info with matching PKG-INFO.
    for directory in directory_iterator:
        egg_pkg_info = _read_pkg_info(directory)
        if egg_pkg_info == pkg_info:
            return directory

    # Nothing matches...? Use the first one we found, I guess.
    return top_egg_info


def read_sdist_metadata(ireq):
    egg_info_dir = _find_egg_info(ireq)
    if not egg_info_dir:
        return None
    distribution = distlib.database.EggInfoDistribution(egg_info_dir)
    return distribution.metadata
