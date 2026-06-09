from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property
from importlib import import_module
from importlib.metadata import Distribution, PackageMetadata, PackageNotFoundError, metadata, version
from inspect import ismodule
from typing import TYPE_CHECKING, Literal

from pipenv.vendor.packaging.requirements import InvalidRequirement, Requirement
from pipenv.vendor.packaging.utils import canonicalize_name

from pipenv.vendor.pipdeptree._parser import distribution_to_specifier

if TYPE_CHECKING:
    from collections.abc import Iterator

RenderMode = Literal["default", "resolved"]


class InvalidRequirementError(ValueError):
    """
    An invalid requirement string was found.

    When raising an exception, this should provide just the problem requirement string.
    """


class Package(ABC):
    """Abstract class for wrappers around objects that pip returns."""

    NA = "N/A"
    UNKNOWN_LICENSE_STR = f"({NA})"

    def __init__(self, project_name: str) -> None:
        self.project_name = project_name
        self.key = canonicalize_name(project_name)

    def _get_dist_metadata(self) -> PackageMetadata | None:
        try:
            return metadata(self.key)
        except PackageNotFoundError:
            return None

    def licenses(self) -> str:
        if (dist_metadata := self._get_dist_metadata()) is None:
            return self.UNKNOWN_LICENSE_STR

        if license_str := dist_metadata["License-Expression"]:
            return f"({license_str})"

        license_strs: list[str] = []
        for classifier in dist_metadata.get_all("Classifier", []):
            line = str(classifier)
            if line.startswith("License"):
                license_strs.append(line.rsplit(":: ", 1)[-1])

        return f"({', '.join(license_strs)})" if license_strs else self.UNKNOWN_LICENSE_STR

    def get_metadata(self, field: str) -> str | list[str]:
        if field == "license":
            raw = self.licenses().strip("()")
            return raw if "license" in raw.lower() else f"{raw} License"
        if (dist_metadata := self._get_dist_metadata()) is None:
            return self.NA
        values = dist_metadata.get_all(field)
        if not values:
            return self.NA
        if len(values) == 1:
            return str(values[0])
        return [str(v) for v in values]

    def get_metadata_values(self, fields: list[str]) -> list[str]:
        result: list[str] = []
        for f in fields:
            value = self.get_metadata(f)
            if isinstance(value, list):
                result.extend(value)
            else:
                result.append(value)
        return [r"\n".join(" ".join(line.split()) for line in v.splitlines()) for v in result]

    def get_metadata_dict(self, fields: list[str]) -> dict[str, str | list[str]]:
        return {field: self.get_metadata(field) for field in fields}

    @abstractmethod
    def render_as_root(self, *, frozen: bool) -> str:
        raise NotImplementedError

    @abstractmethod
    def render_as_branch(self, *, frozen: bool, mode: RenderMode = "default") -> str:
        raise NotImplementedError

    @abstractmethod
    def as_dict(self, *, mode: RenderMode = "default") -> dict[str, str]:
        raise NotImplementedError

    def render(
        self,
        parent: DistPackage | ReqPackage | None = None,
        *,
        frozen: bool = False,
        mode: RenderMode = "default",
    ) -> str:
        if parent:
            return self.render_as_branch(frozen=frozen, mode=mode)
        return self.render_as_root(frozen=frozen)

    @staticmethod
    def as_frozen_repr(distribution: Distribution) -> str:
        return distribution_to_specifier(distribution)

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}("{self.key}")>'

    def __lt__(self, rhs: Package) -> bool:
        return self.key < rhs.key


class DistPackage(Package):
    """
    Wrapper class for importlib.metadata.Distribution instances.

    :param obj: importlib.metadata.Distribution to wrap over
    :param req: optional ReqPackage object to associate this DistPackage with. This is useful for displaying the tree in
        reverse

    """

    def __init__(self, obj: Distribution, req: ReqPackage | None = None) -> None:
        super().__init__(obj.metadata["Name"])
        self._obj = obj
        self.req = req

    def _get_dist_metadata(self) -> PackageMetadata:
        return self._obj.metadata

    @cached_property
    def _parsed_requires(self) -> list[Requirement | str]:
        # Shared between requires() and _extras_index so PEP 508 parsing happens at most once per
        # raw entry. str entries preserve the raw text of invalid requirements so requires() can
        # still surface them via InvalidRequirementError, matching the original semantics.
        return [_try_parse_requirement(raw_req) for raw_req in self._obj.requires or []]

    def requires(self) -> Iterator[Requirement]:
        """
        Return an iterator of the distribution's required dependencies.

        :raises InvalidRequirementError: If the metadata contains invalid requirement strings.
        """
        for entry in self._parsed_requires:
            if isinstance(entry, str):
                raise InvalidRequirementError(entry) from None
            if not entry.marker or entry.marker.evaluate():
                # "extra" markers always evaluate False here, which is what excludes extras-gated
                # reqs from this mandatory-only iterator.
                yield entry

    @cached_property
    def provides_extras(self) -> frozenset[str]:
        return frozenset(self._obj.metadata.get_all("Provides-Extra") or ())

    @cached_property
    def _extras_index(self) -> list[tuple[Requirement, list[str], str]]:
        # Cached because requires_for_extras is called many times per package across the
        # satisfaction and resolution passes; without this, PEP 508 parsing and marker evaluation
        # dominate --extras runtime. dep_key is precomputed alongside since canonicalize_name
        # otherwise shows up as the next-largest contributor in the hot path.
        extras = sorted(self.provides_extras)
        if not extras:
            return []
        result: list[tuple[Requirement, list[str], str]] = []
        for entry in self._parsed_requires:
            if isinstance(entry, str):
                continue
            if not entry.marker or entry.marker.evaluate():
                continue
            if matching := [e for e in extras if entry.marker.evaluate({"extra": e})]:
                result.append((entry, matching, canonicalize_name(entry.name)))
        return result

    def requires_for_extras(self, extras: frozenset[str]) -> Iterator[tuple[Requirement, str, str]]:
        """Yield (requirement, extra_name, dep_key) for requirements gated behind the given extras."""
        for req, matching, dep_key in self._extras_index:
            for extra in matching:
                if extra in extras:
                    yield req, extra, dep_key
                    break

    @cached_property
    def version(self) -> str:
        # Cached because each access reparses the METADATA file on the underlying Distribution and
        # the renderer reads it once per occurrence in the tree (tens of thousands of times for
        # large environments under --extras).
        return self._obj.version

    def unwrap(self) -> Distribution:
        """Exposes the internal `importlib.metadata.Distribution` object."""
        return self._obj

    def render_as_root(self, *, frozen: bool) -> str:
        return self.as_frozen_repr(self._obj) if frozen else f"{self.project_name}=={self.version}"

    def render_as_branch(self, *, frozen: bool, mode: RenderMode = "default") -> str:  # noqa: ARG002
        # resolved mode only relabels ReqPackage branches; a DistPackage branch appears in reverse mode
        # where the "[requires: parent]" label describes the parent edge, so it is left unchanged.
        assert self.req is not None
        if not frozen:
            parent_ver_spec = self.req.version_spec
            parent_str = self.req.project_name
            if parent_ver_spec:
                parent_str += parent_ver_spec
            extra_str = f", extra: {self.req.extra}" if self.req.extra else ""
            return f"{self.project_name}=={self.version} [requires: {parent_str}{extra_str}]"
        return self.render_as_root(frozen=frozen)

    def as_requirement(self) -> ReqPackage:
        """Return a ReqPackage representation of this DistPackage."""
        spec = f"{self.project_name}=={self.version}"
        return ReqPackage(Requirement(spec), dist=self)

    def as_parent_of(self, req: ReqPackage | None) -> DistPackage:
        """
        Return a DistPackage instance associated to a requirement.

        This association is necessary for reversing the PackageDAG.
        If `req` is None, and the `req` attribute of the current instance is also None, then the same instance will be
        returned.

        :param ReqPackage req: the requirement to associate with
        :returns: DistPackage instance

        """
        if req is None and self.req is None:
            return self
        return self.__class__(self._obj, req)

    @property
    def edge_label(self) -> str:
        version = (self.req.version_spec if self.req is not None else None) or "any"
        if self.req is not None and self.req.extra:
            return f"[{self.req.extra}] {version}"
        return version

    def as_dict(self, *, mode: RenderMode = "default") -> dict[str, str]:
        version_key = "candidate_version" if mode == "resolved" else "installed_version"
        return {"key": self.key, "package_name": self.project_name, version_key: self.version}


class ReqPackage(Package):
    """
    Wrapper class for Requirement instance.

    :param obj: The `Requirement` instance to wrap over
    :param dist: optional `importlib.metadata.Distribution` instance for this requirement

    """

    UNKNOWN_VERSION = "?"

    def __init__(self, obj: Requirement, dist: DistPackage | None = None, extra: str | None = None) -> None:
        super().__init__(obj.name)
        self._obj = obj
        self.dist = dist
        self.extra = extra

    def render_as_root(self, *, frozen: bool) -> str:
        if not frozen:
            return f"{self.project_name}=={self.installed_version}"
        if self.dist:
            return self.as_frozen_repr(self.dist.unwrap())
        return self.project_name

    def render_as_branch(self, *, frozen: bool, mode: RenderMode = "default") -> str:
        if not frozen:
            extra_str = f", extra: {self.extra}" if self.extra else ""
            if mode == "resolved":
                # nab resolves one version per package and discards the per-edge range, so there is no
                # "required" to show; surface only the selected candidate.
                return f"{self.project_name} [candidate: {self.installed_version}{extra_str}]"
            req_ver = self.version_spec or "Any"
            return f"{self.project_name} [required: {req_ver}, installed: {self.installed_version}{extra_str}]"
        return self.render_as_root(frozen=frozen)

    @property
    def version_spec(self) -> str | None:
        specs = sorted(map(str, self._obj.specifier), reverse=True)  # `reverse` makes '>' prior to '<'
        return ",".join(specs) if specs else None

    @property
    def edge_label(self) -> str:
        version = self.version_spec or "any"
        if self.extra:
            return f"[{self.extra}] {version}"
        return version

    @property
    def installed_version(self) -> str:
        if not self.dist:
            try:
                return version(self.key)
            except PackageNotFoundError:
                pass
            try:
                m = import_module(self.key)
            except ImportError:
                return self.UNKNOWN_VERSION
            else:
                v = getattr(m, "__version__", self.UNKNOWN_VERSION)
                if ismodule(v):
                    return getattr(v, "__version__", self.UNKNOWN_VERSION)
                return v
        return self.dist.version

    def is_conflicting(self) -> bool:
        """If installed version conflicts with required version."""
        # unknown installed version is also considered conflicting
        if self.is_missing:
            return True

        return not self._obj.specifier.contains(self.installed_version, prereleases=True)

    @property
    def is_missing(self) -> bool:
        return self.installed_version == self.UNKNOWN_VERSION

    def as_dict(self, *, mode: RenderMode = "default") -> dict[str, str]:
        if mode == "resolved":
            # nab discards the per-edge range, so drop required_version and report the single resolved
            # version under candidate_version.
            result = {
                "key": self.key,
                "package_name": self.project_name,
                "candidate_version": self.installed_version,
            }
        else:
            result = {
                "key": self.key,
                "package_name": self.project_name,
                "installed_version": self.installed_version,
                "required_version": self.version_spec if self.version_spec is not None else "Any",
            }
        if self.extra:
            result["extra"] = self.extra
        return result


def _try_parse_requirement(raw_req: str) -> Requirement | str:
    try:
        return Requirement(raw_req)
    except InvalidRequirement:
        return raw_req


__all__ = [
    "DistPackage",
    "RenderMode",
    "ReqPackage",
]
