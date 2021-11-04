from typing import Callable, List

from pipenv.patched.notpip._internal.req.req_install import InstallRequirement
from pipenv.patched.notpip._internal.req.req_set import RequirementSet

InstallRequirementProvider = Callable[[str, InstallRequirement], InstallRequirement]


class BaseResolver:
    def resolve(
        self, root_reqs: List[InstallRequirement], check_supported_wheels: bool
    ) -> RequirementSet:
        raise NotImplementedError()

    def get_installation_order(
        self, req_set: RequirementSet
    ) -> List[InstallRequirement]:
        raise NotImplementedError()
