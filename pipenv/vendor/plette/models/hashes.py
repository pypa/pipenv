from .base import DataView


class Hash(DataView):
    """A hash.
    """
    __SCHEMA__ = {
        "__hash__": {
            "type": "list", "minlength": 1, "maxlength": 1,
            "schema": {
                "type": "list", "minlength": 2, "maxlength": 2,
                "schema": {"type": "string"},
            },
        },
    }

    @classmethod
    def validate(cls, data):
        super(Hash, cls).validate({"__hash__": list(data.items())})

    @classmethod
    def from_hash(cls, ins):
        """Interpolation to the hash result of `hashlib`.
        """
        return cls({ins.name: ins.hexdigest()})

    @classmethod
    def from_line(cls, value):
        try:
            name, value = value.split(":", 1)
        except ValueError:
            name = "sha256"
        return cls({name: value})

    def __eq__(self, other):
        if not isinstance(other, Hash):
            raise TypeError("cannot compare Hash with {0!r}".format(
                type(other).__name__,
            ))
        return self._data == other._data

    @property
    def name(self):
        return next(iter(self._data.keys()))

    @property
    def value(self):
        return next(iter(self._data.values()))

    def as_line(self):
        return "{0[0]}:{0[1]}".format(next(iter(self._data.items())))
