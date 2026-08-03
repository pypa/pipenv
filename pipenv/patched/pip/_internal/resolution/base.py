from collections.abc import Callable

from pipenv.patched.pip._internal.req.req_install import InstallRequirement
from pipenv.patched.pip._internal.req.req_set import RequirementSet

InstallRequirementProvider = Callable[
    [str, InstallRequirement | None], InstallRequirement
]


class BaseResolver:
    def resolve(
        self, root_reqs: list[InstallRequirement], check_supported_wheels: bool
    ) -> RequirementSet:
        raise NotImplementedError()

    def get_installation_order(
        self, req_set: RequirementSet
    ) -> list[InstallRequirement]:
        raise NotImplementedError()
