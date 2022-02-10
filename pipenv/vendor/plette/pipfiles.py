from __future__ import unicode_literals

import hashlib
import json

import pipenv.vendor.six as six
import pipenv.vendor.tomlkit as tomlkit

from .models import (
    DataView, Hash, Requires,
    PackageCollection, ScriptCollection, SourceCollection,
)


PIPFILE_SECTIONS = {
    "source": SourceCollection,
    "packages": PackageCollection,
    "dev-packages": PackageCollection,
    "requires": Requires,
    "scripts": ScriptCollection,
}

DEFAULT_SOURCE_TOML = """\
[[source]]
name = "pypi"
url = "https://pypi.org/simple"
verify_ssl = true
"""


class Pipfile(DataView):
    """Representation of a Pipfile.
    """
    __SCHEMA__ = {}

    @classmethod
    def validate(cls, data):
        # HACK: DO NOT CALL `super().validate()` here!!
        # Cerberus seems to break TOML Kit's inline table preservation if it
        # is not at the top-level. Fortunately the spec doesn't have nested
        # non-inlined tables, so we're OK as long as validation is only
        # performed at section-level. validation is performed.
        for key, klass in PIPFILE_SECTIONS.items():
            if key not in data:
                continue
            klass.validate(data[key])

    @classmethod
    def load(cls, f, encoding=None):
        content = f.read()
        if encoding is not None:
            content = content.decode(encoding)
        data = tomlkit.loads(content)
        if "source" not in data:
            # HACK: There is no good way to prepend a section to an existing
            # TOML document, but there's no good way to copy non-structural
            # content from one TOML document to another either. Modify the
            # TOML content directly, and load the new in-memory document.
            sep = "" if content.startswith("\n") else "\n"
            content = DEFAULT_SOURCE_TOML + sep + content
        data = tomlkit.loads(content)
        return cls(data)

    def __getitem__(self, key):
        value = self._data[key]
        try:
            return PIPFILE_SECTIONS[key](value)
        except KeyError:
            return value

    def __setitem__(self, key, value):
        if isinstance(value, DataView):
            self._data[key] = value._data
        else:
            self._data[key] = value

    def get_hash(self):
        data = {
            "_meta": {
                "sources": self._data["source"],
                "requires": self._data.get("requires", {}),
            },
            "default": self._data.get("packages", {}),
            "develop": self._data.get("dev-packages", {}),
        }
        content = json.dumps(data, sort_keys=True, separators=(",", ":"))
        if isinstance(content, six.text_type):
            content = content.encode("utf-8")
        return Hash.from_hash(hashlib.sha256(content))

    def dump(self, f, encoding=None):
        content = tomlkit.dumps(self._data)
        if encoding is not None:
            content = content.encode(encoding)
        f.write(content)

    @property
    def sources(self):
        try:
            return self["source"]
        except KeyError:
            raise AttributeError("sources")

    @sources.setter
    def sources(self, value):
        self["source"] = value

    @property
    def source(self):
        try:
            return self["source"]
        except KeyError:
            raise AttributeError("source")

    @source.setter
    def source(self, value):
        self["source"] = value

    @property
    def packages(self):
        try:
            return self["packages"]
        except KeyError:
            raise AttributeError("packages")

    @packages.setter
    def packages(self, value):
        self["packages"] = value

    @property
    def dev_packages(self):
        try:
            return self["dev-packages"]
        except KeyError:
            raise AttributeError("dev-packages")

    @dev_packages.setter
    def dev_packages(self, value):
        self["dev-packages"] = value

    @property
    def requires(self):
        try:
            return self["requires"]
        except KeyError:
            raise AttributeError("requires")

    @requires.setter
    def requires(self, value):
        self["requires"] = value

    @property
    def scripts(self):
        try:
            return self["scripts"]
        except KeyError:
            raise AttributeError("scripts")

    @scripts.setter
    def scripts(self, value):
        self["scripts"] = value
