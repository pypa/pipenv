# -*- coding: utf-8 -*-
from __future__ import absolute_import
import os
import six
from attr import validators
from first import first
from .._compat import Link
from ..utils import SCHEME_LIST, VCS_LIST, is_star


HASH_STRING = " --hash={0}"


def filter_none(k, v):
    if v:
        return True
    return False


def optional_instance_of(cls):
    return validators.optional(validators.instance_of(cls))


def extras_to_string(extras):
    """Turn a list of extras into a string"""
    if isinstance(extras, six.string_types):
        if extras.startswith("["):
            return extras

        else:
            extras = [extras]
    return "[{0}]".format(",".join(extras))


def specs_to_string(specs):
    """Turn a list of specifier tuples into a string"""
    if specs:
        if isinstance(specs, six.string_types):
            return specs
        return ",".join(["".join(spec) for spec in specs])
    return ""


def build_vcs_link(vcs, uri, name=None, ref=None, subdirectory=None, extras=None):
    if extras is None:
        extras = []
    vcs_start = "{0}+".format(vcs)
    if not uri.startswith(vcs_start):
        uri = "{0}{1}".format(vcs_start, uri)
    uri = add_ssh_scheme_to_git_uri(uri)
    if ref:
        uri = "{0}@{1}".format(uri, ref)
    if name:
        uri = "{0}#egg={1}".format(uri, name)
        if extras:
            extras = extras_to_string(extras)
            uri = "{0}{1}".format(uri, extras)
    if subdirectory:
        uri = "{0}&subdirectory={1}".format(uri, subdirectory)
    return Link(uri)


def get_version(pipfile_entry):
    if str(pipfile_entry) == "{}" or is_star(pipfile_entry):
        return ""

    elif hasattr(pipfile_entry, "keys") and "version" in pipfile_entry:
        if is_star(pipfile_entry.get("version")):
            return ""
        return pipfile_entry.get("version", "")

    if isinstance(pipfile_entry, six.string_types):
        return pipfile_entry
    return ""


def strip_ssh_from_git_uri(uri):
    """Return git+ssh:// formatted URI to git+git@ format"""
    if isinstance(uri, six.string_types):
        uri = uri.replace("git+ssh://", "git+", 1)
    return uri


def add_ssh_scheme_to_git_uri(uri):
    """Cleans VCS uris from pip format"""
    if isinstance(uri, six.string_types):
        # Add scheme for parsing purposes, this is also what pip does
        if uri.startswith("git+") and "://" not in uri:
            uri = uri.replace("git+", "git+ssh://", 1)
    return uri


def split_markers_from_line(line):
    """Split markers from a dependency"""
    from packaging.markers import Marker, InvalidMarker
    if not any(line.startswith(uri_prefix) for uri_prefix in SCHEME_LIST):
        marker_sep = ";"
    else:
        marker_sep = "; "
    markers = None
    if marker_sep in line:
        line, markers = line.split(marker_sep, 1)
        markers = markers.strip() if markers else None
    return line, markers


def split_vcs_method_from_uri(uri):
    """Split a vcs+uri formatted uri into (vcs, uri)"""
    vcs_start = "{0}+"
    vcs = first([vcs for vcs in VCS_LIST if uri.startswith(vcs_start.format(vcs))])
    if vcs:
        vcs, uri = uri.split("+", 1)
    return vcs, uri


def validate_vcs(instance, attr_, value):
    if value not in VCS_LIST:
        raise ValueError("Invalid vcs {0!r}".format(value))


def validate_path(instance, attr_, value):
    if not os.path.exists(value):
        raise ValueError("Invalid path {0!r}", format(value))


def validate_markers(instance, attr_, value):
    from packaging.markers import Marker, InvalidMarker
    try:
        Marker("{0}{1}".format(attr_.name, value))
    except InvalidMarker:
        raise ValueError("Invalid Marker {0}{1}".format(attr_, value))


def validate_specifiers(instance, attr_, value):
    from packaging.specifiers import SpecifierSet, InvalidSpecifier
    if value == "":
        return True
    try:
        SpecifierSet(value)
    except (InvalidMarker, InvalidSpecifier):
        raise ValueError("Invalid Specifiers {0}".format(value))
