import os

from .base import DataView


class Source(DataView):
    """Information on a "simple" Python package index.

    This could be PyPI, or a self-hosted index server, etc. The server
    specified by the `url` attribute is expected to provide the "simple"
    package API.
    """
    __SCHEMA__ = {
        "name": {"type": "string", "required": True},
        "url": {"type": "string", "required": True},
        "verify_ssl": {"type": "boolean", "required": True},
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
        return self._data["verify_ssl"]

    @verify_ssl.setter
    def verify_ssl(self, value):
        self._data["verify_ssl"] = value

    @property
    def url_expanded(self):
        return os.path.expandvars(self._data["url"])
