import os

from .base import DataModel


class Source(DataModel):
    """Information on a "simple" Python package index.

    This could be PyPI, or a self-hosted index server, etc. The server
    specified by the `url` attribute is expected to provide the "simple"
    package API.

    ``verify_ssl`` is optional. It is meaningless for non-HTTP(S) sources
    (e.g. a local ``file://`` index), so those are not required to specify
    it.
    """
    __SCHEMA__ = {
        "name": str,
        "url": str,
    }
    __OPTIONAL__ = {
        "verify_ssl": bool,
    }

    @property
    def name(self):
        return self._data["name"]

    @name.setter
    def name(self, value):
        self._data["name"] = value

    @property
    def url(self):
        return self._data["url"]

    @url.setter
    def url(self, value):
        self._data["url"] = value

    @property
    def verify_ssl(self):
        return self._data.get("verify_ssl")

    @verify_ssl.setter
    def verify_ssl(self, value):
        self._data["verify_ssl"] = value

    @property
    def url_expanded(self):
        return os.path.expandvars(self._data["url"])
