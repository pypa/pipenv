"""Hash-checking related pip exceptions."""

from __future__ import annotations

from itertools import chain, groupby, repeat
from typing import TYPE_CHECKING

from pipenv.patched.pip._internal.exceptions._base import InstallationError

if TYPE_CHECKING:
    from hashlib import _Hash

    from pipenv.patched.pip._internal.req.req_install import InstallRequirement


class HashErrors(InstallationError):
    """Multiple HashError instances rolled into one for reporting"""

    def __init__(self) -> None:
        self.errors: list[HashError] = []

    def append(self, error: HashError) -> None:
        self.errors.append(error)

    def __str__(self) -> str:
        lines = []
        self.errors.sort(key=lambda e: e.order)
        for cls, errors_of_cls in groupby(self.errors, lambda e: e.__class__):
            lines.append(cls.head)
            lines.extend(e.body() for e in errors_of_cls)
        if lines:
            return "\n".join(lines)
        return ""

    def __bool__(self) -> bool:
        return bool(self.errors)


class HashError(InstallationError):
    """
    A failure to verify a package against known-good hashes

    :cvar order: An int sorting hash exception classes by difficulty of
        recovery (lower being harder), so the user doesn't bother fretting
        about unpinned packages when he has deeper issues, like VCS
        dependencies, to deal with. Also keeps error reports in a
        deterministic order.
    :cvar head: A section heading for display above potentially many
        exceptions of this kind
    :ivar req: The InstallRequirement that triggered this error. This is
        pasted on after the exception is instantiated, because it's not
        typically available earlier.

    """

    req: InstallRequirement | None = None
    head = ""
    order: int = -1

    def body(self) -> str:
        """Return a summary of me for display under the heading.

        This default implementation simply prints a description of the
        triggering requirement.

        :param req: The InstallRequirement that provoked this error, with
            its link already populated by the resolver's _populate_link().

        """
        return f"    {self._requirement_name()}"

    def __str__(self) -> str:
        return f"{self.head}\n{self.body()}"

    def _requirement_name(self) -> str:
        """Return a description of the requirement that triggered me.

        This default implementation returns long description of the req, with
        line numbers

        """
        return str(self.req) if self.req else "unknown package"


class VcsHashUnsupported(HashError):
    """A hash was provided for a version-control-system-based requirement, but
    we don't have a method for hashing those."""

    order = 0
    head = (
        "Can't verify hashes for these requirements because we don't "
        "have a way to hash version control repositories:"
    )


class DirectoryUrlHashUnsupported(HashError):
    """A hash was provided for a version-control-system-based requirement, but
    we don't have a method for hashing those."""

    order = 1
    head = (
        "Can't verify hashes for these file:// requirements because they "
        "point to directories:"
    )


class HashMissing(HashError):
    """A hash was needed for a requirement but is absent."""

    order = 2
    head = (
        "Hashes are required in --require-hashes mode, but they are "
        "missing from some requirements. Here is a list of those "
        "requirements along with the hashes their downloaded archives "
        "actually had. Add lines like these to your requirements files to "
        "prevent tampering. (If you did not enable --require-hashes "
        "manually, note that it turns on automatically when any package "
        "has a hash.)"
    )

    def __init__(self, gotten_hash: str) -> None:
        """
        :param gotten_hash: The hash of the (possibly malicious) archive we
            just downloaded
        """
        self.gotten_hash = gotten_hash

    def body(self) -> str:
        # Dodge circular import.
        from pipenv.patched.pip._internal.utils.hashes import FAVORITE_HASH

        package = None
        if self.req:
            # In the case of URL-based requirements, display the original URL
            # seen in the requirements file rather than the package name,
            # so the output can be directly copied into the requirements file.
            package = (
                self.req.original_link
                if self.req.is_direct
                # In case someone feeds something downright stupid
                # to InstallRequirement's constructor.
                else getattr(self.req, "req", None)
            )
        return "    {} --hash={}:{}".format(
            package or "unknown package", FAVORITE_HASH, self.gotten_hash
        )


class HashUnpinned(HashError):
    """A requirement had a hash specified but was not pinned to a specific
    version."""

    order = 3
    head = (
        "In --require-hashes mode, all requirements must have their "
        "versions pinned with ==. These do not:"
    )


class HashMismatch(HashError):
    """
    Distribution file hash values don't match.

    :ivar package_name: The name of the package that triggered the hash
        mismatch. Feel free to write to this after the exception is raise to
        improve its error message.

    """

    order = 4
    head = (
        "THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS "
        "FILE. If you have updated the package versions, please update "
        "the hashes. Otherwise, examine the package contents carefully; "
        "someone may have tampered with them."
    )

    def __init__(self, allowed: dict[str, list[str]], gots: dict[str, _Hash]) -> None:
        """
        :param allowed: A dict of algorithm names pointing to lists of allowed
            hex digests
        :param gots: A dict of algorithm names pointing to hashes we
            actually got from the files under suspicion
        """
        self.allowed = allowed
        self.gots = gots

    def body(self) -> str:
        return f"    {self._requirement_name()}:\n{self._hash_comparison()}"

    def _hash_comparison(self) -> str:
        """
        Return a comparison of actual and expected hash values.

        Example::

               Expected sha256 abcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcde
                            or 123451234512345123451234512345123451234512345
                    Got        bcdefbcdefbcdefbcdefbcdefbcdefbcdefbcdefbcdef

        """

        def hash_then_or(hash_name: str) -> chain[str]:
            # For now, all the decent hashes have 6-char names, so we can get
            # away with hard-coding space literals.
            return chain([hash_name], repeat("    or"))

        lines: list[str] = []
        for hash_name, expecteds in self.allowed.items():
            prefix = hash_then_or(hash_name)
            lines.extend((f"        Expected {next(prefix)} {e}") for e in expecteds)
            lines.append(
                f"             Got        {self.gots[hash_name].hexdigest()}\n"
            )
        return "\n".join(lines)
