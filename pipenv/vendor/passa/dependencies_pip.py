import importlib
import os

import distlib.wheel
import packaging.version
import pip_shims
import requirementslib
import six

from .caches import CACHE_DIR
from .markers import get_contained_extras, get_without_extra
from .utils import cheesy_temporary_directory, mkdir_p


# HACK: Can we get pip_shims to support these in time?
def _import_module_of(obj):
    return importlib.import_module(obj.__module__)


WheelBuilder = _import_module_of(pip_shims.Wheel).WheelBuilder
unpack_url = _import_module_of(pip_shims.is_file_url).unpack_url


def _prepare_wheel_building_kwargs():
    format_control = pip_shims.FormatControl(set(), set())
    wheel_cache = pip_shims.WheelCache(CACHE_DIR, format_control)

    download_dir = os.path.join(CACHE_DIR, "pkgs")
    mkdir_p(download_dir)

    build_dir = cheesy_temporary_directory(prefix="build")
    src_dir = cheesy_temporary_directory(prefix="source")

    return {
        "wheel_cache": wheel_cache,
        "build_dir": build_dir,
        "src_dir": src_dir,
        "download_dir": download_dir,
        "wheel_download_dir": download_dir,
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
    name = 'PipCommand'


def _get_pip_session(trusted_hosts):
    cmd = _PipCommand()
    options, _ = cmd.parser.parse_args([])
    options.cache_dir = CACHE_DIR
    options.trusted_hosts = trusted_hosts
    session = cmd._build_session(options)
    return session


def _get_internal_objects(sources):
    index_urls, trusted_hosts = _get_pip_index_urls(sources)
    session = _get_pip_session(trusted_hosts)
    finder = pip_shims.PackageFinder(
        find_links=[],
        index_urls=index_urls,
        trusted_hosts=trusted_hosts,
        allow_all_prereleases=True,
        session=session,
    )
    return finder, session


def _build_wheel_pre10(ireq, output_dir, finder, session, kwargs):
    reqset = pip_shims.RequirementSet(**kwargs)
    builder = WheelBuilder(reqset, finder)
    return builder._build_one(ireq, output_dir)


def _build_wheel_10x(ireq, output_dir, finder, session, kwargs):
    kwargs.update({"progress_bar": "off", "build_isolation": False})
    wheel_cache = kwargs.pop("wheel_cache")
    preparer = pip_shims.RequirementPreparer(**kwargs)
    builder = WheelBuilder(finder, preparer, wheel_cache)
    return builder._build_one(ireq, output_dir)


def _build_wheel_modern(ireq, output_dir, finder, session, kwargs):
    kwargs.update({"progress_bar": "off", "build_isolation": False})
    wheel_cache = kwargs.pop("wheel_cache")
    with pip_shims.RequirementTracker() as req_tracker:
        kwargs["req_tracker"] = req_tracker
        preparer = pip_shims.RequirementPreparer(**kwargs)
        builder = WheelBuilder(finder, preparer, wheel_cache)
        return builder._build_one(ireq, output_dir)


def _build_wheel(*args):
    pip_version = packaging.version.parse(pip_shims.pip_version)
    if pip_version < packaging.version.parse("10"):
        return _build_wheel_pre10(*args)
    elif pip_version < packaging.version.parse("18"):
        return _build_wheel_10x(*args)
    return _build_wheel_modern(*args)


def _read_requirements(wheel_path, extras):
    """Read wheel metadata to know what it depends on.

    The `run_requires` attribute contains a list of dict or str specifying
    requirements. For dicts, it may contain an "extra" key to specify these
    requirements are for a specific extra. Unfortunately, not all fields are
    specificed like this (I don't know why); some are specified with markers.
    So we jump though these terrible hoops to know exactly what we need.

    The extra extraction is not comprehensive. Tt assumes the marker is NEVER
    something like `extra == "foo" and extra == "bar"`. I guess this never
    makes sense anyway? Markers are just terrible.
    """
    extras = extras or ()
    wheel = distlib.wheel.Wheel(wheel_path)
    requirements = []
    for entry in wheel.metadata.run_requires:
        if isinstance(entry, six.text_type):
            entry = {"requires": [entry]}
            extra = None
        else:
            extra = entry.get("extra")
        if extra is not None and extra not in extras:
            continue
        for line in entry.get("requires", []):
            r = requirementslib.Requirement.from_line(line)
            if r.markers:
                contained_extras = get_contained_extras(r.markers)
                if (contained_extras and
                        not any(e in contained_extras for e in extras)):
                    continue
                marker = get_without_extra(r.markers)
                r.markers = str(marker) if marker else None
                line = r.as_line(include_hashes=False)
            requirements.append(line)
    return requirements


def _get_dependencies_from_pip(ireq, sources):
    """Retrieves dependencies for the requirement from pip internals.

    The current strategy is to build a wheel out of the ireq, and read metadata
    out of it.
    """
    kwargs = _prepare_wheel_building_kwargs()
    finder, session = _get_internal_objects(sources)

    # Not for upgrade, hash not required.
    ireq.populate_link(finder, False, False)
    ireq.ensure_has_source_dir(kwargs["src_dir"])
    if not pip_shims.is_file_url(ireq.link):
        # This makes sure the remote artifact is downloaded locally. For
        # wheels, it is enough to just download because we'll use them
        # directly. For an sdist, we need to unpack so we can build it.
        unpack_url(
            ireq.link, ireq.source_dir, kwargs["download_dir"],
            only_download=ireq.is_wheel, session=session,
            hashes=ireq.hashes(True), progress_bar=False,
        )

    if ireq.is_wheel:   # If this is a wheel, use the downloaded thing.
        output_dir = kwargs["download_dir"]
        wheel_path = os.path.join(output_dir, ireq.link.filename)
    else:               # Othereise we need to build an ephemeral wheel.
        output_dir = cheesy_temporary_directory(prefix="ephem")
        wheel_path = _build_wheel(ireq, output_dir, finder, session, kwargs)

    if not wheel_path or not os.path.exists(wheel_path):
        raise RuntimeError("failed to build wheel from {}".format(ireq))
    requirements = _read_requirements(wheel_path, ireq.extras)
    return requirements
