from .base import DataModel, DataValidationError


class Hash(DataModel):
    """A hash.
    """
    item_class = "Hash"

    __SCHEMA__ = {
    }

    __OPTIONAL__ = {
        "name": str,
        "md5": str,
        "sha256": str,
        "digest": str,
    }

    def __init__(self, data):
        self.validate(data)
        self._data = data
        if "name" in data:
            self.name = data["name"]
            try:
                self.digest = data["digest"]
            except KeyError:
                self.digest = data["value"]
        elif "md5" in data:
            self.name = "md5"
            self.digest = data["md5"]
        elif "sha256" in data:
            self.name = "sha256"
            self.digest = data["sha256"]

    @classmethod
    def validate(cls, data):
        for k, v in cls.__SCHEMA__.items():
            if k not in data:
                raise DataValidationError(f"Missing required field: {k}")
            if not isinstance(data[k], v):
                raise DataValidationError(f"Invalid type for field {k}: {type(data[k])}")

    @classmethod
    def from_hash(cls, ins):
        """Interpolation to the hash result of `hashlib`.
        """
        return cls(data={ins.name: ins.hexdigest()})

    @classmethod
    def from_line(cls, value):
        try:
            name, value = value.split(":", 1)
        except ValueError:
            name = "sha256"
        return cls(data={"name":name, "value": value})

    def __eq__(self, other):
        if not isinstance(other, Hash):
            raise TypeError("cannot compare Hash with {0!r}".format(
                type(other).__name__,
            ))
        return self._data == other._data

    @property
    def value(self):
        return self.digest

    def as_line(self):
        return "{0[0]}:{0[1]}".format(next(iter(self._data.items())))
