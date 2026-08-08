from __future__ import annotations

import logging
import sys
import textwrap
from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager as ContextManager
from contextlib import nullcontext
from io import StringIO
from typing import TYPE_CHECKING

from pipenv.patched.pip._internal.build_env.base import Prefix
from pipenv.patched.pip._internal.cli.spinners import open_rich_spinner, open_spinner
from pipenv.patched.pip._internal.exceptions import (
    BuildDependencyInstallError,
    DiagnosticPipError,
    InstallWheelBuildError,
    PipError,
)
from pipenv.patched.pip._internal.metadata import get_environment
from pipenv.patched.pip._internal.utils.logging import VERBOSE, capture_logging
from pipenv.patched.pip._internal.utils.misc import get_runnable_pip
from pipenv.patched.pip._internal.utils.subprocess import call_subprocess
from pipenv.patched.pip._internal.utils.temp_dir import TempDirectory

if TYPE_CHECKING:
    from pipenv.patched.pip._internal.cache import WheelCache
    from pipenv.patched.pip._internal.index.package_finder import PackageFinder
    from pipenv.patched.pip._internal.operations.build.build_tracker import BuildTracker
    from pipenv.patched.pip._internal.req.req_install import InstallRequirement
    from pipenv.patched.pip._internal.resolution.base import BaseResolver


logger = logging.getLogger(__name__)


class SubprocessBuildEnvironmentInstaller:
    """
    Install build dependencies by calling pip in a subprocess.
    """

    def __init__(
        self,
        finder: PackageFinder,
        build_constraints: list[str] | None = None,
    ) -> None:
        self.finder = finder
        self._build_constraints = build_constraints or []

    def install(
        self,
        requirements: Iterable[str],
        prefix: Prefix,
        *,
        kind: str,
        for_req: InstallRequirement | None,
    ) -> None:
        finder = self.finder
        args: list[str] = [
            get_runnable_pip(),
            "install",
            # HACK: --prefix shouldn't be necessary for venv environments, but
            # we set it anyway so if it's set via an envvar or configuration
            # file, it won't break things, *sigh*.
            "--prefix",
            prefix.path,
            "--no-user",
            "--no-warn-script-location",
            "--disable-pip-version-check",
            # As the build environment is ephemeral, it's wasteful to
            # pre-compile everything, especially as not every Python
            # module will be used/compiled in most cases.
            "--no-compile",
            # The prefix specified two lines above, thus
            # target from config file or env var should be ignored
            "--target",
            "",
        ]
        if prefix.venv_executable:
            args.insert(0, prefix.venv_executable)
        else:
            args.insert(0, sys.executable)
            args.append("--ignore-installed")

        if logger.getEffectiveLevel() <= logging.DEBUG:
            args.append("-vv")
        elif logger.getEffectiveLevel() <= VERBOSE:
            args.append("-v")
        for format_control in ("no_binary", "only_binary"):
            formats = getattr(finder.format_control, format_control)
            args.extend(
                (
                    "--" + format_control.replace("_", "-"),
                    ",".join(sorted(formats or {":none:"})),
                )
            )

        if finder.release_control is not None:
            # Use ordered args to preserve the user's original command-line order
            # This is important because later flags can override earlier ones
            for attr_name, value in finder.release_control.get_ordered_args():
                args.extend(("--" + attr_name.replace("_", "-"), value))

        index_urls = finder.index_urls
        if index_urls:
            args.extend(["-i", index_urls[0]])
            for extra_index in index_urls[1:]:
                args.extend(["--extra-index-url", extra_index])
        else:
            args.append("--no-index")
        for link in finder.find_links:
            args.extend(["--find-links", link])

        # is not None: forward an empty --proxy "" (disable proxying) too.
        if finder.proxy is not None:
            args.extend(["--proxy", finder.proxy])
        if finder.no_proxy_env:
            args.append("--no-proxy-env")
        for host in finder.trusted_hosts:
            args.extend(["--trusted-host", host])
        if finder.custom_cert:
            args.extend(["--cert", finder.custom_cert])
        if finder.client_cert:
            args.extend(["--client-cert", finder.client_cert])
        if finder.prefer_binary:
            args.append("--prefer-binary")
        if finder.refresh_package:
            args.extend(["--refresh-package", ",".join(finder.refresh_package)])

        # Only build constraints apply in the isolated build environment.
        # _PIP_IN_BUILD_IGNORE_CONSTRAINTS tells the subprocess to ignore the
        # regular constraints it inherits (via PIP_CONSTRAINT or config files).
        # Build constraints reach it through --build-constraint, which also
        # constrains any nested builds.
        for constraint_file in self._build_constraints:
            args.extend(["--build-constraint", constraint_file])

        if finder.uploaded_prior_to:
            args.extend(["--uploaded-prior-to", finder.uploaded_prior_to.isoformat()])
        args.append("--")
        args.extend(requirements)

        identify_requirement = (
            f" for {for_req.name}" if for_req and for_req.name else ""
        )
        with open_spinner(f"Installing {kind}") as spinner:
            call_subprocess(
                args,
                command_desc=f"installing {kind}{identify_requirement}",
                spinner=spinner,
                extra_environ={"_PIP_IN_BUILD_IGNORE_CONSTRAINTS": "1"},
            )


class InprocessBuildEnvironmentInstaller:
    """
    Install build dependencies via the already running pip process.

    This contains a stripped down version of the install command with
    only the logic necessary for installing build dependencies. The
    finder, session, build tracker, and wheel cache are reused, but new
    instances of everything else are created as needed.

    Options are inherited from the parent install command unless
    they don't make sense for build dependencies (in which case, they
    are hard-coded, see comments below).
    """

    # TODO: this plays poorly with venv-based build environments, but cannot be
    # fixed until pip gains better support for operating within a Python
    # environment that isn't the running environment.

    def __init__(
        self,
        *,
        finder: PackageFinder,
        build_tracker: BuildTracker,
        wheel_cache: WheelCache,
        build_constraints: Sequence[InstallRequirement] = (),
        verbosity: int = 0,
    ) -> None:
        from pipenv.patched.pip._internal.operations.prepare import RequirementPreparer

        self._finder = finder
        self._build_constraints = build_constraints
        self._wheel_cache = wheel_cache
        self._level = 0

        build_dir = TempDirectory(kind="build-env-install", globally_managed=True)
        self._preparer = RequirementPreparer(
            build_isolation_installer=self,
            # Inherited options or state.
            finder=finder,
            session=finder._link_collector.session,
            build_dir=build_dir.path,
            build_tracker=build_tracker,
            verbosity=verbosity,
            # This is irrelevant as it only applies to editable requirements.
            src_dir="",
            # Hard-coded options (that should NOT be inherited).
            download_dir=None,
            build_isolation="virtual",
            check_build_deps=False,
            progress_bar="off",
            # TODO: hash-checking should be extended to build deps, but that is
            # deferred for later as it'd be a breaking change.
            require_hashes=False,
            use_user_site=False,
            lazy_wheel=False,
            legacy_resolver=False,
            allow_editables=True,
        )

    def install(
        self,
        requirements: Iterable[str],
        prefix: Prefix,
        *,
        kind: str,
        for_req: InstallRequirement | None,
    ) -> None:
        """Install entrypoint. Manages output capturing and error handling."""
        capture_logs = not logger.isEnabledFor(VERBOSE) and self._level == 0
        if capture_logs:
            # Hide the logs from the installation of build dependencies.
            # They will be shown only if an error occurs.
            capture_ctx: ContextManager[StringIO] = capture_logging()
            spinner: ContextManager[None] = open_rich_spinner(f"Installing {kind}")
        else:
            # Otherwise, pass-through all logs (with a header).
            capture_ctx, spinner = nullcontext(StringIO()), nullcontext()
            logger.info("Installing %s ...", kind)

        try:
            self._level += 1
            with spinner, capture_ctx as stream:
                self._install_impl(requirements, prefix)

        except DiagnosticPipError as exc:
            # Format similar to a nested subprocess error, where the
            # causing error is shown first, followed by the build error.
            logger.info(textwrap.dedent(stream.getvalue()))
            logger.error("%s", exc, extra={"rich": True})
            logger.info("")
            raise BuildDependencyInstallError(
                for_req, requirements, cause=exc, log_lines=None
            )

        except Exception as exc:
            logs: list[str] | None = textwrap.dedent(stream.getvalue()).splitlines()
            if not capture_logs:
                # If logs aren't being captured, then display the error inline
                # with the rest of the logs.
                logs = None
                if isinstance(exc, PipError):
                    logger.error("%s", exc)
                else:
                    logger.exception("pip crashed unexpectedly")
            raise BuildDependencyInstallError(
                for_req, requirements, cause=exc, log_lines=logs
            )

        finally:
            self._level -= 1

    def _install_impl(self, requirements: Iterable[str], prefix: Prefix) -> None:
        """Core build dependency install logic."""
        from pipenv.patched.pip._internal.commands.install import installed_packages_summary
        from pipenv.patched.pip._internal.req import install_given_reqs
        from pipenv.patched.pip._internal.req.constructors import install_req_from_line
        from pipenv.patched.pip._internal.wheel_builder import build

        ireqs = [install_req_from_line(req, user_supplied=True) for req in requirements]
        ireqs.extend(self._build_constraints)

        resolver = self._make_resolver()
        resolved_set = resolver.resolve(ireqs, check_supported_wheels=True)
        self._preparer.prepare_linked_requirements_more(
            resolved_set.requirements.values()
        )

        reqs_to_build = [
            r for r in resolved_set.requirements_to_install if not r.is_wheel
        ]
        _, build_failures = build(
            reqs_to_build, self._wheel_cache, verify=True, allow_editables=True
        )
        if build_failures:
            raise InstallWheelBuildError(build_failures)

        installed = install_given_reqs(
            resolver.get_installation_order(resolved_set),
            prefix=prefix.path,
            # Hard-coded options (that should NOT be inherited).
            root=None,
            home=None,
            warn_script_location=False,
            use_user_site=False,
            # As the build environment is ephemeral, it's wasteful to
            # pre-compile everything since not all modules will be used.
            pycompile=False,
            progress_bar="off",
            # Link console scripts to the build env's interpreter, not pip's.
            script_executable=prefix.venv_executable,
        )

        env = get_environment(list(prefix.lib_dirs))
        if summary := installed_packages_summary(installed, env):
            logger.info(summary)

    def _make_resolver(self) -> BaseResolver:
        """Create a new resolver for one time use."""
        # Legacy installer never used the legacy resolver so create a
        # resolvelib resolver directly. Yuck.
        from pipenv.patched.pip._internal.req.constructors import install_req_from_req_string
        from pipenv.patched.pip._internal.resolution.resolvelib.resolver import Resolver

        return Resolver(
            make_install_req=install_req_from_req_string,
            # Inherited state.
            preparer=self._preparer,
            finder=self._finder,
            wheel_cache=self._wheel_cache,
            # Hard-coded options (that should NOT be inherited).
            ignore_requires_python=False,
            use_user_site=False,
            ignore_dependencies=False,
            only_dependencies=False,
            ignore_installed=True,
            force_reinstall=False,
            upgrade_strategy="to-satisfy-only",
            py_version_info=None,
        )
