from __future__ import annotations

from abc import ABC, abstractmethod
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from inspect import ismodule
from typing import TYPE_CHECKING

from pipenv.patched.pip._vendor.pkg_resources import Requirement

if TYPE_CHECKING:
    from pipenv.patched.pip._internal.metadata import BaseDistribution
    from pipenv.patched.pip._vendor.pkg_resources import DistInfoDistribution


class Package(ABC):
    """Abstract class for wrappers around objects that pip returns."""

    def __init__(self, obj: DistInfoDistribution) -> None:
        self._obj: DistInfoDistribution = obj

    @property
    def key(self) -> str:
        return self._obj.key  # type: ignore[no-any-return]

    @property
    def project_name(self) -> str:
        return self._obj.project_name  # type: ignore[no-any-return]

    @abstractmethod
    def render_as_root(self, *, frozen: bool) -> str:
        raise NotImplementedError

    @abstractmethod
    def render_as_branch(self, *, frozen: bool) -> str:
        raise NotImplementedError

    @abstractmethod
    def as_dict(self) -> dict[str, str | None]:
        raise NotImplementedError

    @property
    def version_spec(self) -> None | str:
        return None

    def render(
        self,
        parent: DistPackage | ReqPackage | None = None,
        *,
        frozen: bool = False,
    ) -> str:
        render = self.render_as_branch if parent else self.render_as_root
        return render(frozen=frozen)

    @staticmethod
    def as_frozen_repr(obj: DistInfoDistribution) -> str:
        # The `pipenv.patched.pip._internal.metadata` modules were introduced in 21.1.1
        # and the `pipenv.patched.pip._internal.operations.freeze.FrozenRequirement`
        # class now expects dist to be a subclass of
        # `pipenv.patched.pip._internal.metadata.BaseDistribution`, however the
        # `pipenv.patched.pip._internal.utils.misc.get_installed_distributions` continues
        # to return objects of type
        # pipenv.patched.pip._vendor.pkg_resources.DistInfoDistribution.
        #
        # This is a hacky backward compatible (with older versions of pip) fix.
        try:
            from pipenv.patched.pip._internal.operations.freeze import FrozenRequirement
        except ImportError:
            from pipenv.patched.pip import FrozenRequirement  # type: ignore[attr-defined, no-redef]

        try:
            from pipenv.patched.pip._internal import metadata
        except ImportError:
            our_dist: BaseDistribution = obj  # type: ignore[assignment]
        else:
            our_dist = metadata.pkg_resources.Distribution(obj)

        try:
            fr = FrozenRequirement.from_dist(our_dist)
        except TypeError:
            fr = FrozenRequirement.from_dist(our_dist, [])  # type: ignore[call-arg]
        return str(fr).strip()

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}("{self.key}")>'

    def __lt__(self, rhs: Package) -> bool:
        return self.key < rhs.key


class DistPackage(Package):
    """Wrapper class for pkg_resources.Distribution instances.

    :param obj: pkg_resources.Distribution to wrap over
    :param req: optional ReqPackage object to associate this DistPackage with. This is useful for displaying the tree in
        reverse

    """

    def __init__(self, obj: DistInfoDistribution, req: ReqPackage | None = None) -> None:
        super().__init__(obj)
        self.req = req

    def requires(self) -> list[Requirement]:
        return self._obj.requires()  # type: ignore[no-untyped-call,no-any-return]

    @property
    def version(self) -> str:
        return self._obj.version  # type: ignore[no-any-return]

    def render_as_root(self, *, frozen: bool) -> str:
        if not frozen:
            return f"{self.project_name}=={self.version}"
        return self.as_frozen_repr(self._obj)

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
        return ReqPackage(self._obj.as_requirement(), dist=self)  # type: ignore[no-untyped-call]

    def as_parent_of(self, req: ReqPackage | None) -> DistPackage:
        """Return a DistPackage instance associated to a requirement.

        This association is necessary for reversing the PackageDAG.
        If `req` is None, and the `req` attribute of the current instance is also None, then the same instance will be
        returned.

        :param ReqPackage req: the requirement to associate with
        :returns: DistPackage instance

        """
        if req is None and self.req is None:
            return self
        return self.__class__(self._obj, req)

    def as_dict(self) -> dict[str, str | None]:
        return {"key": self.key, "package_name": self.project_name, "installed_version": self.version}


class ReqPackage(Package):
    """Wrapper class for Requirements instance.

    :param obj: The `Requirements` instance to wrap over
    :param dist: optional `pkg_resources.Distribution` instance for this requirement

    """

    UNKNOWN_VERSION = "?"

    def __init__(self, obj: Requirement, dist: DistPackage | None = None) -> None:
        super().__init__(obj)
        self.dist = dist

    def render_as_root(self, *, frozen: bool) -> str:
        if not frozen:
            return f"{self.project_name}=={self.installed_version}"
        if self.dist:
            return self.as_frozen_repr(self.dist._obj)  # noqa: SLF001
        return self.project_name

    def render_as_branch(self, *, frozen: bool) -> str:
        if not frozen:
            req_ver = self.version_spec if self.version_spec else "Any"
            return f"{self.project_name} [required: {req_ver}, installed: {self.installed_version}]"
        return self.render_as_root(frozen=frozen)

    @property
    def version_spec(self) -> str | None:
        specs = sorted(self._obj.specs, reverse=True)  # `reverse` makes '>' prior to '<'
        return ",".join(["".join(sp) for sp in specs]) if specs else None

    @property
    def installed_version(self) -> str:
        if not self.dist:
            try:
                return version(self.key)
            except PackageNotFoundError:
                pass
            # Avoid AssertionError with setuptools, see https://github.com/tox-dev/pipdeptree/issues/162
            if self.key in {"setuptools"}:
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
        ver_spec = self.version_spec if self.version_spec else ""
        req_version_str = f"{self.project_name}{ver_spec}"
        req_obj = Requirement.parse(req_version_str)  # type: ignore[no-untyped-call]
        return self.installed_version not in req_obj

    def as_dict(self) -> dict[str, str | None]:
        return {
            "key": self.key,
            "package_name": self.project_name,
            "installed_version": self.installed_version,
            "required_version": self.version_spec,
        }


__all__ = [
    "DistPackage",
    "ReqPackage",
]
