# -*- coding=utf-8 -*-

from __future__ import absolute_import, unicode_literals

import functools
import os
import sys

import packaging.specifiers
import packaging.utils
import packaging.version
import requests
import requirementslib
import six

from ..models.caches import DependencyCache, RequiresPythonCache
from ._pip import WheelBuildError, build_wheel, read_sdist_metadata
from .markers import contains_extra, get_contained_extras, get_without_extra
from .utils import get_pinned_version, is_pinned


DEPENDENCY_CACHE = DependencyCache()
REQUIRES_PYTHON_CACHE = RequiresPythonCache()


def _cached(f, **kwargs):

    @functools.wraps(f)
    def wrapped(ireq):
        result = f(ireq, **kwargs)
        if result is not None and is_pinned(ireq):
            deps, requires_python = result
            DEPENDENCY_CACHE[ireq] = deps
            REQUIRES_PYTHON_CACHE[ireq] = requires_python
        return result

    return wrapped


def _is_cache_broken(line, parent_name):
    dep_req = requirementslib.Requirement.from_line(line)
    if contains_extra(dep_req.markers):
        return True     # The "extra =" marker breaks everything.
    elif dep_req.normalized_name == parent_name:
        return True     # A package cannot depend on itself.
    return False


def _get_dependencies_from_cache(ireq):
    """Retrieves dependencies for the requirement from the dependency cache.
    """
    if os.environ.get("PASSA_IGNORE_LOCAL_CACHE"):
        return
    if ireq.editable:
        return
    try:
        deps = DEPENDENCY_CACHE[ireq]
        pyrq = REQUIRES_PYTHON_CACHE[ireq]
    except KeyError:
        return

    # Preserving sanity: Run through the cache and make sure every entry if
    # valid. If this fails, something is wrong with the cache. Drop it.
    try:
        packaging.specifiers.SpecifierSet(pyrq)
        ireq_name = packaging.utils.canonicalize_name(ireq.name)
        if any(_is_cache_broken(line, ireq_name) for line in deps):
            broken = True
        else:
            broken = False
    except Exception:
        broken = True

    if broken:
        print("dropping broken cache for {0}".format(ireq.name))
        del DEPENDENCY_CACHE[ireq]
        del REQUIRES_PYTHON_CACHE[ireq]
        return

    return deps, pyrq


def _get_dependencies_from_json_url(url, session):
    response = session.get(url)
    response.raise_for_status()
    info = response.json()["info"]

    requires_python = info["requires_python"] or ""
    try:
        requirement_lines = info["requires_dist"]
    except KeyError:
        requirement_lines = info["requires"]

    # The JSON API returns null both when there are not requirements, or the
    # requirement list cannot be retrieved. We can't safely assume, so it's
    # better to drop it and fall back to downloading the package.
    try:
        dependency_requirements_iterator = (
            requirementslib.Requirement.from_line(line)
            for line in requirement_lines
        )
    except TypeError:
        return

    dependencies = [
        dep_req.as_line(include_hashes=False)
        for dep_req in dependency_requirements_iterator
        if not contains_extra(dep_req.markers)
    ]
    return dependencies, requires_python


def _get_dependencies_from_json(ireq, sources):
    """Retrieves dependencies for the install requirement from the JSON API.

    :param ireq: A single InstallRequirement
    :type ireq: :class:`~pip._internal.req.req_install.InstallRequirement`
    :return: A set of dependency lines for generating new InstallRequirements.
    :rtype: set(str) or None
    """
    if os.environ.get("PASSA_IGNORE_JSON_API"):
        return

    # It is technically possible to parse extras out of the JSON API's
    # requirement format, but it is such a chore let's just use the simple API.
    if ireq.extras:
        return

    try:
        version = get_pinned_version(ireq)
    except ValueError:
        return

    url_prefixes = [
        proc_url[:-7]   # Strip "/simple".
        for proc_url in (
            raw_url.rstrip("/")
            for raw_url in (source.get("url", "") for source in sources)
        )
        if proc_url.endswith("/simple")
    ]

    session = requests.session()

    for prefix in url_prefixes:
        url = "{prefix}/pypi/{name}/{version}/json".format(
            prefix=prefix,
            name=packaging.utils.canonicalize_name(ireq.name),
            version=version,
        )
        try:
            dependencies = _get_dependencies_from_json_url(url, session)
            if dependencies is not None:
                return dependencies
        except Exception as e:
            print("unable to read dependencies via {0} ({1})".format(url, e))
    session.close()
    return


def _read_requirements(metadata, extras):
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
    requirements = []
    for entry in metadata.run_requires:
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
                contained = get_contained_extras(r.markers)
                if (contained and not any(e in contained for e in extras)):
                    continue
                marker = get_without_extra(r.markers)
                r.markers = str(marker) if marker else None
                line = r.as_line(include_hashes=False)
            requirements.append(line)
    return requirements


def _read_requires_python(metadata):
    """Read wheel metadata to know the value of Requires-Python.

    This is surprisingly poorly supported in Distlib. This function tries
    several ways to get this information:

    * Metadata 2.0: metadata.dictionary.get("requires_python") is not None
    * Metadata 2.1: metadata._legacy.get("Requires-Python") is not None
    * Metadata 1.2: metadata._legacy.get("Requires-Python") != "UNKNOWN"
    """
    # TODO: Support more metadata formats.
    value = metadata.dictionary.get("requires_python")
    if value is not None:
        return value
    if metadata._legacy:
        value = metadata._legacy.get("Requires-Python")
        if value is not None and value != "UNKNOWN":
            return value
    return ""


def _get_dependencies_from_pip(ireq, sources):
    """Retrieves dependencies for the requirement from pipenv.patched.notpip internals.

    The current strategy is to try the followings in order, returning the
    first successful result.

    1. Try to build a wheel out of the ireq, and read metadata out of it.
    2. Read metadata out of the egg-info directory if it is present.
    """
    extras = ireq.extras or ()
    try:
        wheel = build_wheel(ireq, sources)
    except WheelBuildError:
        # XXX: This depends on a side effect of `build_wheel`. This block is
        # reached when it fails to build an sdist, where the sdist would have
        # been downloaded, extracted into `ireq.source_dir`, and partially
        # built (hopefully containing .egg-info).
        metadata = read_sdist_metadata(ireq)
        if not metadata:
            raise
    else:
        metadata = wheel.metadata
    requirements = _read_requirements(metadata, extras)
    requires_python = _read_requires_python(metadata)
    return requirements, requires_python


def get_dependencies(requirement, sources):
    """Get all dependencies for a given install requirement.

    :param requirement: A requirement
    :param sources: Pipfile-formatted sources
    :type sources: list[dict]
    """
    getters = [
        _get_dependencies_from_cache,
        _cached(_get_dependencies_from_json, sources=sources),
        _cached(_get_dependencies_from_pip, sources=sources),
    ]
    ireq = requirement.as_ireq()
    last_exc = None
    for getter in getters:
        try:
            result = getter(ireq)
        except Exception as e:
            last_exc = sys.exc_info()
            continue
        if result is not None:
            deps, pyreq = result
            reqs = [requirementslib.Requirement.from_line(d) for d in deps]
            return reqs, pyreq
    if last_exc:
        six.reraise(*last_exc)
    raise RuntimeError("failed to get dependencies for {}".format(
        requirement.as_line(),
    ))
