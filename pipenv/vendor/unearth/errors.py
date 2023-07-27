from __future__ import annotations

from pipenv.vendor.unearth.link import Link


class URLError(ValueError):
    pass


class VCSBackendError(URLError):
    pass


class UnpackError(RuntimeError):
    pass


class HashMismatchError(UnpackError):
    def __init__(
        self, link: Link, expected: dict[str, list[str]], actual: dict[str, str]
    ) -> None:
        self.link = link
        self.expected = expected
        self.actual = actual

    def format_hash_item(self, name: str) -> str:
        expected = self.expected[name]
        actual = self.actual[name]
        expected_prefix = f"Expected({name}): "
        actual_prefix = f"  Actual({name}): "
        sep = "\n" + " " * len(expected_prefix)
        return f"{expected_prefix}{sep.join(expected)}\n{actual_prefix}{actual}"

    def __str__(self) -> str:
        return f"Hash mismatch for {self.link.redacted}:\n" + "\n".join(
            self.format_hash_item(name) for name in sorted(self.expected)
        )
