import re as _re
import datetime as _datetime

from .base import DataModel, DataModelSequence, DataModelMapping, DataValidationError
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


_COOL_DOWN_PATTERN = _re.compile(r"^(\d+)d$")


class PipfileSection(DataModel):

    """
    Dummy pipfile validator that needs to be completed in a future PR
    Hint: many pipfile features are undocumented in  pipenv/project.py
    """

    __schema__ = {
        "sort_pipfile": bool
    }

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

    @classmethod
    def validate(cls, data):
        super().validate(data)
        if "cool-down-period" in data:
            value = data["cool-down-period"]
            if not isinstance(value, str) or not _COOL_DOWN_PATTERN.match(value):
                raise DataValidationError(
                    f"Invalid cool-down-period {value!r}: expected format '<int>d' (e.g. '30d')"
                )

    @property
    def cool_down_period(self):
        """Return the raw cool-down-period string (e.g. '30d'), or None."""
        return self._data.get("cool-down-period")

    @cool_down_period.setter
    def cool_down_period(self, value):
        if value is not None:
            if not isinstance(value, str) or not _COOL_DOWN_PATTERN.match(value):
                raise DataValidationError(
                    f"Invalid cool-down-period {value!r}: expected format '<int>d' (e.g. '30d')"
                )
        self._data["cool-down-period"] = value

    @property
    def cool_down_period_timedelta(self):
        """Return cool-down-period as a timedelta, or None if not set."""
        raw = self.cool_down_period
        if raw is None:
            return None
        days = int(_COOL_DOWN_PATTERN.match(raw).group(1))
        return _datetime.timedelta(days=days)
