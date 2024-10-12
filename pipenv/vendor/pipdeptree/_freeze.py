from __future__ import annotations

import locale
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pipenv.patched.pip._internal.models.direct_url import (
    DirectUrl,  # noqa: PLC2701
    DirectUrlValidationError,  # noqa: PLC2701
)
from pipenv.patched.pip._internal.utils.egg_link import egg_link_path_from_sys_path  # noqa: PLC2701
from pipenv.patched.pip._vendor.packaging.version import Version  # noqa: PLC2701

if TYPE_CHECKING:
    from importlib.metadata import Distribution


def dist_to_frozen_repr(dist: Distribution) -> str:
    """Return the frozen requirement repr of a `importlib.metadata.Distribution` object."""
    from pipenv.patched.pip._internal.operations.freeze import FrozenRequirement  # noqa: PLC0415, PLC2701

    adapter = PipBaseDistributionAdapter(dist)
    fr = FrozenRequirement.from_dist(adapter)  # type: ignore[arg-type]

    return str(fr).strip()


class PipBaseDistributionAdapter:
    """
    An adapter class for pip's `pipenv.patched.pip._internal.metadata.BaseDistribution` abstract class.

    It essentially wraps over an importlib.metadata.Distribution object and provides just enough fields/methods found in
    pip's `BaseDistribution` so that we can use `pipenv.patched.pip._internal.operations.freeze.FrozenRequirement.from_dist()`.

    :param dist: Represents an `importlib.metadata.Distribution` object.
    """

    DIRECT_URL_METADATA_NAME = "direct_url.json"

    def __init__(self, dist: Distribution) -> None:
        self._dist = dist
        self._raw_name = dist.metadata["Name"]
        self._version = Version(dist.version)

    @property
    def raw_name(self) -> str | Any:
        return self._raw_name

    @property
    def version(self) -> Version:
        return self._version

    @property
    def editable(self) -> bool:
        return self.editable_project_location is not None

    @property
    def direct_url(self) -> DirectUrl | None:
        result = None
        json_str = self._dist.read_text(self.DIRECT_URL_METADATA_NAME)
        try:
            if json_str:
                result = DirectUrl.from_json(json_str)
        except (
            UnicodeDecodeError,
            JSONDecodeError,
            DirectUrlValidationError,
        ):
            return result
        return result

    @property
    def editable_project_location(self) -> str | None:
        direct_url = self.direct_url
        if direct_url and direct_url.is_local_editable():
            from pipenv.patched.pip._internal.utils.urls import url_to_path  # noqa: PLC2701, PLC0415

            return url_to_path(direct_url.url)

        result = None
        egg_link_path = egg_link_path_from_sys_path(self.raw_name)
        if egg_link_path:
            with Path(egg_link_path).open("r", encoding=locale.getpreferredencoding(False)) as f:  # noqa: FBT003
                result = f.readline().rstrip()
        return result


__all__ = ["dist_to_frozen_repr"]
