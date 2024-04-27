from __future__ import annotations

from abc import ABC, abstractmethod
from importlib import import_module
from importlib.metadata import Distribution, PackageNotFoundError, metadata, version
from inspect import ismodule
from typing import TYPE_CHECKING, Iterator

from pipenv.vendor.packaging.requirements import InvalidRequirement, Requirement
from pipenv.vendor.packaging.utils import canonicalize_name

if TYPE_CHECKING:
    from importlib.metadata import Distribution

from pipenv.vendor.pipdeptree._adapter import PipBaseDistributionAdapter


class InvalidRequirementError(ValueError):
    """
    An invalid requirement string was found.

    When raising an exception, this should provide just the problem requirement string.
    """


class Package(ABC):
    """Abstract class for wrappers around objects that pip returns."""

    UNKNOWN_LICENSE_STR = "(Unknown license)"

    def __init__(self, project_name: str) -> None:
        self.project_name = project_name
        self.key = canonicalize_name(project_name)

    def licenses(self) -> str:
        try:
            dist_metadata = metadata(self.key)
        except PackageNotFoundError:
            return self.UNKNOWN_LICENSE_STR

        license_strs: list[str] = []
        classifiers = dist_metadata.get_all("Classifier", [])

        for classifier in classifiers:
            line = str(classifier)
            if line.startswith("License"):
                license_str = line.split(":: ")[-1]
                license_strs.append(license_str)

        if len(license_strs) == 0:
            return self.UNKNOWN_LICENSE_STR

        return f'({", ".join(license_strs)})'

    @abstractmethod
    def render_as_root(self, *, frozen: bool) -> str:
        raise NotImplementedError

    @abstractmethod
    def render_as_branch(self, *, frozen: bool) -> str:
        raise NotImplementedError

    @abstractmethod
    def as_dict(self) -> dict[str, str]:
        raise NotImplementedError

    def render(
        self,
        parent: DistPackage | ReqPackage | None = None,
        *,
        frozen: bool = False,
    ) -> str:
        render = self.render_as_branch if parent else self.render_as_root
        return render(frozen=frozen)

    @staticmethod
    def as_frozen_repr(dist: Distribution) -> str:
        from pipenv.patched.pip._internal.operations.freeze import FrozenRequirement  # noqa: PLC0415, PLC2701 # pragma: no cover

        adapter = PipBaseDistributionAdapter(dist)
        fr = FrozenRequirement.from_dist(adapter)  # type: ignore[arg-type]

        return str(fr).strip()

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

    def requires(self) -> Iterator[Requirement]:
        """
        Return an iterator of the distribution's required dependencies.

        :raises InvalidRequirementError: If the metadata contains invalid requirement strings.
        """
        for r in self._obj.requires or []:
            try:
                req = Requirement(r)
            except InvalidRequirement:
                raise InvalidRequirementError(r) from None
            if not req.marker or req.marker.evaluate():
                # Make sure that we're either dealing with a dependency that has no environment markers or does but
                # are evaluated True against the existing environment (if it's False, it means they cannot be
                # installed). "extra" markers are always evaluated False here which is what we want when retrieving
                # only required dependencies.
                yield req

    @property
    def version(self) -> str:
        return self._obj.version

    def unwrap(self) -> Distribution:
        """Exposes the internal `importlib.metadata.Distribution` object."""
        return self._obj

    def render_as_root(self, *, frozen: bool) -> str:
        return self.as_frozen_repr(self._obj) if frozen else f"{self.project_name}=={self.version}"

    def render_as_branch(self, *, frozen: bool) -> str:
        assert self.req is not None
        if not frozen:
            parent_ver_spec = self.req.version_spec
            parent_str = self.req.project_name
            if parent_ver_spec:
                parent_str += parent_ver_spec
            return f"{self.project_name}=={self.version} [requires: {parent_str}]"
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

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "package_name": self.project_name, "installed_version": self.version}


class ReqPackage(Package):
    """
    Wrapper class for Requirement instance.

    :param obj: The `Requirement` instance to wrap over
    :param dist: optional `importlib.metadata.Distribution` instance for this requirement

    """

    UNKNOWN_VERSION = "?"

    def __init__(self, obj: Requirement, dist: DistPackage | None = None) -> None:
        super().__init__(obj.name)
        self._obj = obj
        self.dist = dist

    def render_as_root(self, *, frozen: bool) -> str:
        if not frozen:
            return f"{self.project_name}=={self.installed_version}"
        if self.dist:
            return self.as_frozen_repr(self.dist.unwrap())
        return self.project_name

    def render_as_branch(self, *, frozen: bool) -> str:
        if not frozen:
            req_ver = self.version_spec if self.version_spec else "Any"
            return f"{self.project_name} [required: {req_ver}, installed: {self.installed_version}]"
        return self.render_as_root(frozen=frozen)

    @property
    def version_spec(self) -> str | None:
        result = None
        specs = sorted(map(str, self._obj.specifier), reverse=True)  # `reverse` makes '>' prior to '<'
        if specs:
            result = ",".join(specs)
        return result

    @property
    def installed_version(self) -> str:
        if not self.dist:
            try:
                return version(self.key)
            except PackageNotFoundError:
                pass
            # Avoid AssertionError with setuptools, see https://github.com/tox-dev/pipdeptree/issues/162
            if self.key == "setuptools":
                return self.UNKNOWN_VERSION
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

    @property
    def is_missing(self) -> bool:
        return self.installed_version == self.UNKNOWN_VERSION

    def is_conflicting(self) -> bool:
        """If installed version conflicts with required version."""
        # unknown installed version is also considered conflicting
        if self.installed_version == self.UNKNOWN_VERSION:
            return True

        return self.installed_version not in self._obj.specifier

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "package_name": self.project_name,
            "installed_version": self.installed_version,
            "required_version": self.version_spec if self.version_spec is not None else "Any",
        }


__all__ = [
    "DistPackage",
    "ReqPackage",
]
