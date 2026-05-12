"""The ``VenvLocator`` subsystem of :class:`pipenv.project.Project`.

Third of the Initiative D extractions (after ``Sources`` in T_D.2 and
``Settings`` in T_D.3). The 13 ``VenvLocator``-classified methods on
``pipenv.project.Project`` move into a dedicated ``VenvLocator`` class
accessed via the ``@cached_property`` ``Project.venv_locator``.

``VenvLocator`` is *read-only* against the venv (creation happens in
``pipenv/utils/virtualenv.py``). Per T_D.1 §6.1 maintainer sign-off no
split into ``Locator`` + ``Bootstrap`` is needed — there are no writers
in this bucket.

Behaviour is preserved verbatim from the previous in-``Project``
implementation; this is a relocation, not a rewrite. ``VenvLocator``
holds a back-reference to the owning ``Project`` so it can read
``project.s.*`` (the ``Settings`` proper), ``project.pipfile.parsed``,
``project.pipfile.project_directory``, ``project.pipfile.name``, and
``project.pipfile.location`` without redefining their lazy-init
semantics.

API rename (per the T_D.2 Sources pattern): the ``virtualenv_`` prefix
on the old ``Project`` surface is dropped because the subsystem itself
is named ``venv_locator``. ``project.virtualenv_location`` becomes
``project.venv_locator.location``; ``project.is_venv_in_project()``
becomes ``project.venv_locator.is_venv_in_project()``; etc.

See ``docs/dev/initiative-d-inventory.md`` for the T_D.1 inventory and
``docs/dev/modernization-plan.md`` for the T_D.4 task spec.
"""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import operator
import os
import re
import sys
from pathlib import Path

from pipenv.utils.shell import (
    find_windows_executable,
    get_workon_home,
    is_virtual_environment,
    looks_like_dir,
    system_which,
)
from pipenv.utils.virtualenv import virtualenv_scripts_dir


class VenvLocator:
    """Virtualenv discovery / path-resolution subsystem of :class:`Project`.

    Constructed with a back-reference to its owning ``Project``. Owns the
    cached ``_location`` / ``_download_location`` / ``_proper_names_db_path``
    state that previously lived as ``__init__``-set attributes on
    ``Project``.
    """

    def __init__(self, project):
        self._project = project
        self._location = None
        self._download_location = None
        self._proper_names_db_path = None

    # ---- pipfile-derived venv-in-project flag -----------------------------

    def _pipfile_venv_in_project(self) -> bool | None:
        """Check the [pipenv] section of the Pipfile for venv_in_project setting.

        Returns True/False if explicitly set, None if not set.
        """
        project = self._project
        if project.pipfile.exists:
            value = project.pipfile.parsed.get("pipenv", {}).get("venv_in_project")
            if value is not None:
                return bool(value)
        return None

    def is_venv_in_project(self) -> bool:
        project = self._project
        # Environment variable takes precedence over Pipfile setting.
        if project.s.PIPENV_VENV_IN_PROJECT is False:
            return False
        if project.s.PIPENV_VENV_IN_PROJECT is True:
            return True
        # If env var is not set, check Pipfile [pipenv] section.
        pipfile_setting = self._pipfile_venv_in_project()
        if pipfile_setting is not None:
            return pipfile_setting
        # Fall back to auto-detection of .venv directory.
        return bool(
            project.pipfile.project_directory
            and Path(project.pipfile.project_directory, ".venv").is_dir()
        )

    # ---- venv existence ---------------------------------------------------

    @property
    def exists(self) -> bool:
        """``True`` if the venv has an ``activate`` script.

        Was ``Project.virtualenv_exists`` prior to T_D.4.
        """
        venv_path = Path(self.location)

        scripts_dir = self.scripts_location

        if venv_path.exists():
            # existence of active.bat is dependent on the platform path prefix
            # scheme, not platform itself. This handles special cases such as
            # Cygwin/MinGW identifying as 'nt' platform, yet preferring a
            # 'posix' path prefix scheme.
            if scripts_dir.name == "Scripts":
                activate_path = scripts_dir / "activate.bat"
            else:
                activate_path = scripts_dir / "activate"
            return activate_path.is_file()

        return False

    # ---- venv path resolution --------------------------------------------

    def get_location(self) -> Path:
        """Resolve the path where the venv should live.

        Was ``Project.get_location_for_virtualenv`` prior to T_D.4.
        """
        project = self._project
        # If there's no project yet, set location based on config.
        if not project.pipfile.project_directory:
            if self.is_venv_in_project():
                return Path(".venv").absolute()
            return get_workon_home().joinpath(self.name)

        dot_venv = Path(project.pipfile.project_directory) / ".venv"

        # If there's no .venv in project root or it is a folder, set location based on config.
        if not dot_venv.exists() or dot_venv.is_dir():
            if self.is_venv_in_project():
                # When PIPENV_VENV_IN_PROJECT is not explicitly set, the .venv dir
                # was detected automatically. If a pipenv-managed virtualenv already
                # exists in WORKON_HOME (e.g. created before the user independently
                # ran `python -m venv .venv`), prefer that one so that `pipenv --rm`
                # does not accidentally remove the user-created .venv directory.
                if (
                    not project.s.PIPENV_VENV_IN_PROJECT
                    and not self._pipfile_venv_in_project()
                ):
                    workon_home_venv = get_workon_home() / self.name
                    if workon_home_venv.exists():
                        return workon_home_venv
                return dot_venv
            return get_workon_home().joinpath(self.name)

        # Now we assume .venv in project root is a file. Use its content.
        name = dot_venv.read_text().strip()

        # If .venv file is empty, set location based on config.
        if not name:
            return get_workon_home().joinpath(self.name)

        # If content looks like a path, use it as a relative path.
        # Otherwise, use directory named after content in WORKON_HOME.
        if looks_like_dir(name):
            path = Path(project.pipfile.project_directory) / name
            return path.absolute()
        return get_workon_home().joinpath(name)

    # ---- venv naming / hashing -------------------------------------------

    @classmethod
    def _sanitize(cls, name: str) -> str:
        # Replace dangerous characters into '_'. The length of the sanitized
        # project name is limited as 42 because of the limit of linux kernel
        #
        # 42 = 127 - len('/home//.local/share/virtualenvs//bin/python2') - 32 - len('-HASHHASH')
        #
        #      127 : BINPRM_BUF_SIZE - 1
        #       32 : Maximum length of username
        #
        # References:
        #   https://www.gnu.org/software/bash/manual/html_node/Double-Quotes.html
        #   http://www.tldp.org/LDP/abs/html/special-chars.html#FIELDREF
        #   https://github.com/torvalds/linux/blob/2bfe01ef/include/uapi/linux/binfmts.h#L18
        return re.sub(r'[ &$`!*@"()\[\]\\\r\n\t]', "_", name)[0:42]

    def _get_virtualenv_hash(self, name: str) -> tuple[str, str]:
        """Get the name of the virtualenv adjusted for windows if needed

        Returns (name, encoded_hash)
        """
        project = self._project

        def get_name(name, location):
            name = self._sanitize(name)
            hash = hashlib.sha256(location.encode()).digest()[:6]
            encoded_hash = base64.urlsafe_b64encode(hash).decode()
            return name, encoded_hash[:8]

        clean_name, encoded_hash = get_name(name, project.pipfile.location)
        venv_name = f"{clean_name}-{encoded_hash}"

        # This should work most of the time for
        #   Case-sensitive filesystems,
        #   In-project venv
        #   "Proper" path casing (on non-case-sensitive filesystems).
        if (
            not fnmatch.fnmatch("A", "a")
            or self.is_venv_in_project()
            or get_workon_home().joinpath(venv_name).exists()
        ):
            return clean_name, encoded_hash

        # Check for different capitalization of the same project.
        for path in get_workon_home().iterdir():
            if not is_virtual_environment(path):
                continue
            try:
                env_name, hash_ = path.name.rsplit("-", 1)
            except ValueError:
                continue
            if len(hash_) != 8 or env_name.lower() != name.lower():
                continue
            return get_name(env_name, project.pipfile.location.replace(name, env_name))

        # Use the default if no matching env exists.
        return clean_name, encoded_hash

    @property
    def name(self) -> str:
        """The slug-and-hash name of the venv directory.

        Was ``Project.virtualenv_name`` prior to T_D.4.
        """
        project = self._project
        custom_name = project.s.PIPENV_CUSTOM_VENV_NAME
        if custom_name:
            return custom_name
        sanitized, encoded_hash = self._get_virtualenv_hash(project.pipfile.name)
        suffix = ""
        if project.s.PIPENV_PYTHON:
            if Path(project.s.PIPENV_PYTHON).is_absolute():
                suffix = f"-{Path(project.s.PIPENV_PYTHON).name}"
            else:
                suffix = f"-{project.s.PIPENV_PYTHON}"

        # If the pipfile was located at '/home/user/MY_PROJECT/Pipfile',
        # the name of its virtualenv will be 'my-project-wyUfYPqE'
        return sanitized + "-" + encoded_hash + suffix

    @property
    def location(self) -> Path:
        """Resolved (and cached) absolute path to the venv.

        Was ``Project.virtualenv_location`` prior to T_D.4.
        """
        project = self._project
        # if VIRTUAL_ENV is set, use that.
        virtualenv_env = os.getenv("VIRTUAL_ENV")
        if (
            "PIPENV_ACTIVE" not in os.environ
            and not project.s.PIPENV_IGNORE_VIRTUALENVS
            and virtualenv_env
        ):
            return Path(virtualenv_env)

        if not self._location:  # Use cached version, if available.
            if not project.pipfile.project_directory:
                raise RuntimeError("Project location not created nor specified")
            location = self.get_location()
            self._location = Path(location)
        return self._location

    @property
    def src_location(self) -> Path:
        """The ``src`` subdir of the venv, created on access.

        Was ``Project.virtualenv_src_location`` prior to T_D.4.
        """
        project = self._project
        if self.location:
            loc = Path(self.location) / "src"
        else:
            loc = Path(project.pipfile.project_directory) / "src"
        loc.mkdir(parents=True, exist_ok=True)
        return loc

    @property
    def scripts_location(self) -> Path:
        """``bin`` / ``Scripts`` dir of the resolved venv.

        Was ``Project.virtualenv_scripts_location`` prior to T_D.4.
        """
        return virtualenv_scripts_dir(self.location)

    @property
    def download_location(self) -> Path:
        """``<venv>/downloads`` dir, created on access.

        Was ``Project.download_location`` prior to T_D.4.
        """
        if self._download_location is None:
            loc = Path(self.location) / "downloads"
            self._download_location = loc
        # Create the directory, if it doesn't exist.
        self._download_location.mkdir(parents=True, exist_ok=True)
        return self._download_location

    @property
    def proper_names_db_path(self) -> Path:
        """Path to the ``pipenv-proper-names.txt`` file under the venv.

        Created on access. Was ``Project.proper_names_db_path`` prior to
        T_D.4. The ``proper_names`` list and ``register_proper_name``
        method (which read/write this file) stay on ``Project`` per the
        T_D.1 inventory — they're classified ``Pipfile``-bucket because
        their purpose is package-name casing, not venv plumbing.
        """
        if self._proper_names_db_path is None:
            self._proper_names_db_path = Path(
                self.location, "pipenv-proper-names.txt"
            )
        # Ensure the parent directory exists before touching the file
        self._proper_names_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._proper_names_db_path.touch()  # Ensure the file exists.
        return self._proper_names_db_path

    # ---- pythonfinder integration ----------------------------------------

    @property
    def finders(self):
        """List of ``Finder`` instances rooted at the venv scripts dir.

        Cached per-instance (so the first access materialises the list
        and subsequent accesses return the same list — was a
        ``@cached_property`` on ``Project`` prior to T_D.4). Because
        ``VenvLocator`` itself is cached on ``Project`` via
        ``@cached_property``, the underlying list survives for the
        process lifetime.
        """
        if "_finders" not in self.__dict__:
            from pipenv.vendor.pythonfinder import Finder

            self._finders = [
                Finder(
                    path=str(self.scripts_location), global_search=gs, system=False
                )
                for gs in (False, True)
            ]
        return self._finders

    @property
    def finder(self):
        """First :class:`Finder` of :attr:`finders` (or ``None``).

        Was ``Project.finder`` prior to T_D.4.
        """
        return next(iter(self.finders), None)

    # ---- executable lookup -----------------------------------------------

    def which(self, search):
        """Locate ``search`` via :attr:`finders`, falling back to :meth:`_which`.

        Was ``Project.which`` prior to T_D.4.
        """
        find = operator.methodcaller("which", search)
        result = next(
            iter(filter(None, (find(finder) for finder in self.finders))), None
        )
        if not result:
            result = self._which(search)
        return result

    def python(self, system=False) -> str:
        """Path to the project python.

        Was ``Project.python`` prior to T_D.4.
        """
        from pipenv.utils.shell import project_python

        # ``project_python`` calls back into ``project._which`` — preserve
        # the existing API by forwarding the project reference.
        return project_python(self._project, system=system)

    def _which(self, command, location=None, allow_global=False):
        """Resolve ``command`` to an absolute path within the venv (or globally).

        Was ``Project._which`` prior to T_D.4.
        """
        if not allow_global and location is None:
            if self.exists:
                location = self.location
            else:
                location = os.environ.get("VIRTUAL_ENV", None)

        location_path = Path(location) if location else None

        if not (location_path and location_path.exists()) and not allow_global:
            raise RuntimeError("location not created nor specified")

        version_str = f"python{'.'.join([str(v) for v in sys.version_info[:2]])}"
        is_python = command in ("python", Path(sys.executable).name, version_str)

        if not allow_global:
            scripts_location = virtualenv_scripts_dir(location_path)

            if os.name == "nt":
                p = find_windows_executable(str(scripts_location), command)
                # Convert to Path object if it's a string
                p = Path(p) if isinstance(p, str) else p
            else:
                p = scripts_location / command
        elif is_python:
            p = Path(sys.executable)
        else:
            p = None

        if p is None or not p.exists():
            if is_python:
                p = (
                    Path(sys.executable)
                    if sys.executable
                    else Path(system_which("python"))
                )
            else:
                p = Path(system_which(command)) if system_which(command) else None

        return p
