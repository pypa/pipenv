import pipenv.vendor.tomlkit as tomlkit

from .base import DataModel, DataValidationError

class PackageSpecfiers(DataModel):
    # TODO: one could add here more validation for path editable
    # and more stuff which is currently allowed and undocumented
    __SCHEMA__ = {}
    __OPTIONAL__ = {
        "editable": bool,
        "version": str,
        "extras": list
    }


class Package(DataModel):
    """A package requirement specified in a Pipfile.

    This is the base class of variants appearing in either `[packages]` or
    `[dev-packages]` sections of a Pipfile.
    """
    # The extra layer is intentional. Cerberus does not allow top-level keys
    # to have oneof_schema (at least I can't do it), so we wrap this in a
    # top-level key. The Requirement model class implements extra hacks to
    # make this work.
    __OPTIONAL__ = {
        "PackageSpecfiers":  (str, dict)
    }

    @classmethod
    def validate(cls, data):
        if isinstance(data, (str, tomlkit.items.Float, tomlkit.items.Integer)):
            return
        if isinstance(data, dict):
            PackageSpecfiers.validate(data)
        else:
            raise DataValidationError(f"invalid type for package data: {type(data)}")

    def __getattr__(self, key):
        if isinstance(self._data, (str, tomlkit.items.Float, tomlkit.items.Integer)):
            if key == "version":
                return self._data
            raise AttributeError(key)
        try:
            return self._data[key]
        except KeyError:
            pass
        raise AttributeError(key)

    def __setattr__(self, key, value):
        if key == "_data":
            super().__setattr__(key, value)
        elif key == "version" and isinstance(self._data, str):
            self._data = value
        else:
            self._data[key] = value
