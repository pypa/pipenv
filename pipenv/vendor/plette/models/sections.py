from .base import DataModel, DataModelSequence, DataModelMapping
from .hashes import Hash
from .packages import Package
from .scripts import Script
from .sources import Source


class PackageCollection(DataModelMapping):
    item_class = Package


class ScriptCollection(DataModelMapping):
    item_class = Script


class SourceCollection(DataModelSequence):
    item_class = Source


class Requires(DataModel):
    """Representation of the `[requires]` section in a Pipfile."""

    __SCHEMA__ = {}

    __OPTIONAL__ = {
        "python_version": str,
        "python_full_version": str,
    }

    @property
    def python_version(self):
        try:
            return self._data["python_version"]
        except KeyError:
            raise AttributeError("python_version")

    @property
    def python_full_version(self):
        try:
            return self._data["python_full_version"]
        except KeyError:
            raise AttributeError("python_full_version")


META_SECTIONS = {
    "hash": Hash,
    "requires": Requires,
    "sources": SourceCollection,
}


class PipfileSection(DataModel):

    """
    Dummy pipfile validator that needs to be completed in a future PR
    Hint: many pipfile features are undocumented in  pipenv/project.py
    """

    @classmethod
    def validate(cls, data):
        pass


class Meta(DataModel):
    """Representation of the `_meta` section in a Pipfile.lock."""

    __SCHEMA__ = {
        "hash": "dict",
        "pipfile-spec": "integer",
        "requires": "dict",
        "sources": "list"
    }

    @classmethod
    def validate(cls, data):
        for key, klass in META_SECTIONS.items():
            klass.validate(data[key])

    def __getitem__(self, key):
        value = super().__getitem__(key)
        try:
            return META_SECTIONS[key](value)
        except KeyError:
            return value

    def __setitem__(self, key, value):
        if isinstance(value, DataModel):
            self._data[key] = value._data
        else:
            self._data[key] = value

    @property
    def hash_(self):
        return self["hash"]

    @hash_.setter
    def hash_(self, value):
        self["hash"] = value

    @property
    def hash(self):
        return self["hash"]

    @hash.setter
    def hash(self, value):
        self["hash"] = value

    @property
    def pipfile_spec(self):
        return self["pipfile-spec"]

    @pipfile_spec.setter
    def pipfile_spec(self, value):
        self["pipfile-spec"] = value

    @property
    def requires(self):
        return self["requires"]

    @requires.setter
    def requires(self, value):
        self["requires"] = value

    @property
    def sources(self):
        return self["sources"]

    @sources.setter
    def sources(self, value):
        self["sources"] = value


class Pipenv(DataModel):
    """Represent the [pipenv] section in Pipfile"""
    __SCHEMA__ = {}
    __OPTIONAL__ = {
        "allow_prereleases": bool,
    }
