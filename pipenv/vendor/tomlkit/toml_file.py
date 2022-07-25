from .api import loads
from .toml_document import TOMLDocument


class TOMLFile:
    """
    Represents a TOML file.

    :param path: path to the TOML file
    """

    def __init__(self, path: str) -> None:
        self._path = path

    def read(self) -> TOMLDocument:
        """Read the file content as a :class:`tomlkit.toml_document.TOMLDocument`."""
        with open(self._path, encoding="utf-8", newline="") as f:
            return loads(f.read())

    def write(self, data: TOMLDocument) -> None:
        """Write the TOMLDocument to the file."""
        with open(self._path, "w", encoding="utf-8", newline="") as f:
            f.write(data.as_string())
