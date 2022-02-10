# Expose a limited set of classes and functions so callers outside of
# the vcs package don't need to import deeper than `pipenv.patched.notpip._internal.vcs`.
# (The test directory may still need to import from a vcs sub-package.)
# Import all vcs modules to register each VCS in the VcsSupport object.
import pipenv.patched.notpip._internal.vcs.bazaar
import pipenv.patched.notpip._internal.vcs.git
import pipenv.patched.notpip._internal.vcs.mercurial
import pipenv.patched.notpip._internal.vcs.subversion  # noqa: F401
from pipenv.patched.notpip._internal.vcs.versioncontrol import (  # noqa: F401
    RemoteNotFoundError,
    RemoteNotValidError,
    is_url,
    make_vcs_requirement_url,
    vcs,
)
