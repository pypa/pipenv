# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import collections
import io
import os

import pipenv.vendor.attr as attr
import packaging.markers
import packaging.utils
import pipenv.vendor.plette as plette
import plette.models
import pipenv.vendor.tomlkit as tomlkit

SectionDifference = collections.namedtuple("SectionDifference", ["inthis", "inthat"])
FileDifference = collections.namedtuple("FileDifference", ["default", "develop"])


def _are_pipfile_entries_equal(a, b):
    a = {k: v for k, v in a.items() if k not in ("markers", "hashes", "hash")}
    b = {k: v for k, v in b.items() if k not in ("markers", "hashes", "hash")}
    if a != b:
        return False
    try:
        marker_eval_a = packaging.markers.Marker(a["markers"]).evaluate()
    except (AttributeError, KeyError, TypeError, ValueError):
        marker_eval_a = True
    try:
        marker_eval_b = packaging.markers.Marker(b["markers"]).evaluate()
    except (AttributeError, KeyError, TypeError, ValueError):
        marker_eval_b = True
    return marker_eval_a == marker_eval_b


DEFAULT_NEWLINES = "\n"


def preferred_newlines(f):
    if isinstance(f.newlines, str):
        return f.newlines
    return DEFAULT_NEWLINES


@attr.s
class ProjectFile(object):
    """A file in the Pipfile project."""

    location = attr.ib()
    line_ending = attr.ib()
    model = attr.ib()

    @classmethod
    def read(cls, location, model_cls, invalid_ok=False):
        if not os.path.exists(location) and not invalid_ok:
            raise FileNotFoundError(location)
        try:
            with io.open(location, encoding="utf-8") as f:
                model = model_cls.load(f)
                line_ending = preferred_newlines(f)
        except Exception:
            if not invalid_ok:
                raise
            model = None
            line_ending = DEFAULT_NEWLINES
        return cls(location=location, line_ending=line_ending, model=model)

    def write(self):
        kwargs = {"encoding": "utf-8", "newline": self.line_ending}
        with io.open(self.location, "w", **kwargs) as f:
            self.model.dump(f)

    def dumps(self):
        strio = io.StringIO()
        self.model.dump(strio)
        return strio.getvalue()


@attr.s
class Project(object):

    root = attr.ib()
    _p = attr.ib(init=False)
    _l = attr.ib(init=False)

    def __attrs_post_init__(self):
        self.root = root = os.path.abspath(self.root)
        self._p = ProjectFile.read(os.path.join(root, "Pipfile"), plette.Pipfile)
        self._l = ProjectFile.read(
            os.path.join(root, "Pipfile.lock"), plette.Lockfile, invalid_ok=True
        )

    @property
    def pipfile(self):
        return self._p.model

    @property
    def pipfile_location(self):
        return self._p.location

    @property
    def lockfile(self):
        return self._l.model

    @property
    def lockfile_location(self):
        return self._l.location

    @lockfile.setter
    def lockfile(self, new):
        self._l.model = new

    def is_synced(self):
        return self.lockfile and self.lockfile.is_up_to_date(self.pipfile)

    def _get_pipfile_section(self, develop, insert=True):
        name = "dev-packages" if develop else "packages"
        try:
            section = self.pipfile[name]
        except KeyError:
            section = plette.models.PackageCollection(tomlkit.table())
            if insert:
                self.pipfile[name] = section
        return section

    def contains_key_in_pipfile(self, key):
        sections = [
            self._get_pipfile_section(develop=False, insert=False),
            self._get_pipfile_section(develop=True, insert=False),
        ]
        return any(
            (
                packaging.utils.canonicalize_name(name)
                == packaging.utils.canonicalize_name(key)
            )
            for section in sections
            for name in section
        )

    def add_line_to_pipfile(self, line, develop):
        from pipenv.vendor.requirementslib import Requirement

        requirement = Requirement.from_line(line)
        section = self._get_pipfile_section(develop=develop)
        key = requirement.normalized_name
        entry = next(iter(requirement.as_pipfile().values()))
        if isinstance(entry, dict):
            # HACK: TOMLKit prefers to expand tables by default, but we
            # always want inline tables here. Also tomlkit.inline_table
            # does not have `update()`.
            table = tomlkit.inline_table()
            for k, v in entry.items():
                table[k] = v
            entry = table
        section[key] = entry

    def remove_keys_from_pipfile(self, keys, default, develop):
        keys = {packaging.utils.canonicalize_name(key) for key in keys}
        sections = []
        if default:
            sections.append(self._get_pipfile_section(develop=False, insert=False))
        if develop:
            sections.append(self._get_pipfile_section(develop=True, insert=False))
        for section in sections:
            removals = set()
            for name in section:
                if packaging.utils.canonicalize_name(name) in keys:
                    removals.add(name)
            for key in removals:
                del section._data[key]

    def remove_keys_from_lockfile(self, keys):
        keys = {packaging.utils.canonicalize_name(key) for key in keys}
        removed = False
        for section_name in ("default", "develop"):
            try:
                section = self.lockfile[section_name]
            except KeyError:
                continue
            removals = set()
            for name in section:
                if packaging.utils.canonicalize_name(name) in keys:
                    removals.add(name)
            removed = removed or bool(removals)
            for key in removals:
                del section._data[key]

        if removed:
            # HACK: The lock file no longer represents the Pipfile at this
            # point. Set the hash to an arbitrary invalid value.
            self.lockfile.meta.hash = plette.models.Hash({"__invalid__": ""})

    def difference_lockfile(self, lockfile):
        """Generate a difference between the current and given lockfiles.

        Returns a 2-tuple containing differences in default in develop
        sections.

        Each element is a 2-tuple of dicts. The first, `inthis`, contains
        entries only present in the current lockfile; the second, `inthat`,
        contains entries only present in the given one.

        If a key exists in both this and that, but the values differ, the key
        is present in both dicts, pointing to values from each file.
        """
        diff_data = {
            "default": SectionDifference({}, {}),
            "develop": SectionDifference({}, {}),
        }
        for section_name, section_diff in diff_data.items():
            try:
                this = self.lockfile[section_name]._data
            except (KeyError, TypeError):
                this = {}
            try:
                that = lockfile[section_name]._data
            except (KeyError, TypeError):
                that = {}
            for key, this_value in this.items():
                try:
                    that_value = that[key]
                except KeyError:
                    section_diff.inthis[key] = this_value
                    continue
                if not _are_pipfile_entries_equal(this_value, that_value):
                    section_diff.inthis[key] = this_value
                    section_diff.inthat[key] = that_value
            for key, that_value in that.items():
                if key not in this:
                    section_diff.inthat[key] = that_value
        return FileDifference(**diff_data)
