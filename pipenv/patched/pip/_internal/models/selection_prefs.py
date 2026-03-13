from __future__ import annotations

from pipenv.patched.pip._internal.models.format_control import FormatControl
from pipenv.patched.pip._internal.models.release_control import ReleaseControl


# TODO: This needs Python 3.10's improved slots support for dataclasses
# to be converted into a dataclass.
class SelectionPreferences:
    """
    Encapsulates the candidate selection preferences for downloading
    and installing files.
    """

    __slots__ = [
        "allow_yanked",
        "release_control",
        "format_control",
        "prefer_binary",
        "ignore_requires_python",
        "ignore_compatibility",
    ]

    # Don't include an allow_yanked default value to make sure each call
    # site considers whether yanked releases are allowed. This also causes
    # that decision to be made explicit in the calling code, which helps
    # people when reading the code.
    def __init__(
        self,
        allow_yanked: bool,
        release_control: ReleaseControl | None = None,
        format_control: FormatControl | None = None,
        prefer_binary: bool = False,
        ignore_requires_python: bool | None = None,
        ignore_compatibility: bool | None = None,
    ) -> None:
        """Create a SelectionPreferences object.

        :param allow_yanked: Whether files marked as yanked (in the sense
            of PEP 592) are permitted to be candidates for install.
        :param release_control: A ReleaseControl object or None. Used to control
            whether pre-releases are allowed for specific packages.
        :param format_control: A FormatControl object or None. Used to control
            the selection of source packages / binary packages when consulting
            the index and links.
        :param prefer_binary: Whether to prefer an old, but valid, binary
            dist over a new source dist.
        :param ignore_requires_python: Whether to ignore incompatible
            "Requires-Python" values in links. Defaults to False.
        :param ignore_compatibility: Whether to ignore compatibility checks
            and allow all package versions. Defaults to False.
        """
        if ignore_requires_python is None:
            ignore_requires_python = False
        if ignore_compatibility is None:
            ignore_compatibility = False

        self.allow_yanked = allow_yanked
        self.release_control = release_control
        self.format_control = format_control
        self.prefer_binary = prefer_binary
        self.ignore_requires_python = ignore_requires_python
        self.ignore_compatibility = ignore_compatibility
