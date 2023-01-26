from .base import DataView


class Package(DataView):
    """A package requirement specified in a Pipfile.

    This is the base class of variants appearing in either `[packages]` or
    `[dev-packages]` sections of a Pipfile.
    """
    # The extra layer is intentional. Cerberus does not allow top-level keys
    # to have oneof_schema (at least I can't do it), so we wrap this in a
    # top-level key. The Requirement model class implements extra hacks to
    # make this work.
    __SCHEMA__ = {
        "__package__": {
            "oneof_type": ["string", "dict"],
        },
    }

    @classmethod
    def validate(cls, data):
        # HACK: Make this validatable for Cerberus. See comments in validation
        # side for more information.
        super(Package, cls).validate({"__package__": data})
        if isinstance(data, dict):
            PackageSpecfiers.validate({"__specifiers__": data})

    def __getattr__(self, key):
        if isinstance(self._data, str):
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
            super(Package, self).__setattr__(key, value)
        elif key == "version" and isinstance(self._data, str):
            self._data = value
        else:
            self._data[key] = value

class PackageSpecfiers(DataView):
    # TODO: one could add here more validation for path editable
    # and more stuff which is currently allowed and undocumented
    __SCHEMA__ = {
        "__specifiers__": {
            "type": "dict",
            "schema":{
                "version": {"type": "string"},
                "extras": {"type": "list"},
                }
            }
        }
