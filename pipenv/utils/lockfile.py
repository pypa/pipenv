"""The ``Lockfile`` subsystem of :class:`pipenv.project.Project`.

Fourth of the Initiative D extractions (after ``Sources`` in T_D.2,
``Settings`` in T_D.3, and ``VenvLocator`` in T_D.4). The 13
``Lockfile``-classified methods on ``pipenv.project.Project`` move into
this module, accessed via a ``@cached_property`` ``Project.lockfile``.

Per T_D.1 §8.1 maintainer sign-off pylock.toml (PEP 751) support is NOT
folded into this extraction. The ``Lockfile`` class handles only the
legacy ``Pipfile.lock`` format; pylock seams (in :attr:`content`,
:meth:`as_dict`, :meth:`write`, :attr:`any_exists`,
:attr:`pylock_exists`, :attr:`pylock_location`, :attr:`pylock_output_path`)
carry ``# TODO(pylock):`` tags so they remain greppable for the 2027
follow-up where the format-detection layer will be re-designed.

Behaviour is preserved verbatim from the previous in-``Project``
implementation; this is a relocation, not a rewrite. ``Lockfile`` holds
a back-reference to the owning ``Project`` because:

- ``meta()`` needs ``project.calculate_pipfile_hash()`` and
  ``project.sources.pipfile_sources()`` (cross-subsystem reads).
- ``content`` / :meth:`load` need ``project.pipfile_location`` and may
  call ``project.write_toml`` indirectly via :meth:`write` self-call.
- :attr:`package_names` reads ``project.get_package_categories(for_lockfile=True)``.

API rename (matches T_D.2 Sources / T_D.4 VenvLocator patterns):

  project.lockfile(categories=...)   -> project.lockfile.as_dict(categories=...)
  project.lockfile_location          -> project.lockfile.location
  project.lockfile_exists            -> project.lockfile.exists
  project.lockfile_content           -> project.lockfile.content
  project.lockfile_package_names     -> project.lockfile.package_names
  project.any_lockfile_exists        -> project.lockfile.any_exists
  project.pylock_location            -> project.lockfile.pylock_location
  project.pylock_exists              -> project.lockfile.pylock_exists
  project.pylock_output_path         -> project.lockfile.pylock_output_path
  project.get_lockfile_meta()        -> project.lockfile.meta()
  project.get_lockfile_hash()        -> project.lockfile.hash()
  project.load_lockfile(...)         -> project.lockfile.load(...)
  project.write_lockfile(content)    -> project.lockfile.write(content)

The orchestrating ``Project.get_or_create_lockfile`` stays on
``Project`` per T_D.1 §2 (``coordinator`` bucket — it crosses
``Lockfile`` + ``Sources`` + ``Pipfile`` boundaries).

See ``docs/dev/initiative-d-inventory.md`` for the T_D.1 inventory.
"""

from __future__ import annotations

import json
from json.decoder import JSONDecodeError
from pathlib import Path

from pipenv.utils import err
from pipenv.utils.dependencies import get_canonical_names
from pipenv.utils.exceptions import LockfileCorruptException
from pipenv.utils.locking import atomic_open_for_write
from pipenv.utils.pylock import PylockFile, find_pylock_file
from pipenv.utils.shell import expand_url_credentials
from pipenv.vendor import plette


def _preferred_newlines(f, default: str = "\n") -> str:
    if isinstance(f.newlines, str):
        return f.newlines
    return default


class Lockfile:
    """``Pipfile.lock`` subsystem of :class:`Project`.

    Constructed with a back-reference to its owning ``Project``. Holds
    no cache state of its own — every read goes through the project's
    on-disk lockfile, and writes are atomic.

    The pylock.toml (PEP 751) detection seams in this class are tagged
    ``# TODO(pylock):`` per the T_D.1 §8.1 maintainer sign-off; the
    eventual format-aware redesign happens in 2027, not here.
    """

    def __init__(self, project):
        self._project = project

    # ---- location / existence ---------------------------------------------

    @property
    def location(self) -> str:
        """Returns the canonical ``Pipfile.lock`` path (``<Pipfile>.lock``)."""
        return f"{self._project.pipfile_location}.lock"

    @property
    def exists(self) -> bool:
        """Returns True if a ``Pipfile.lock`` file exists on disk."""
        return Path(self.location).is_file()

    # TODO(pylock): pylock.toml location/existence accessors live here as
    # a transitional convenience. The 2027 redesign should separate these
    # into a dedicated pylock subsystem behind a format-detection layer.
    @property
    def pylock_location(self) -> str | None:
        """Returns the location of the ``pylock.toml`` file, if it exists."""
        pylock_path = find_pylock_file(self._project.project_directory)
        if pylock_path:
            return str(pylock_path)
        return None

    @property
    def pylock_exists(self) -> bool:
        """Returns True if a ``pylock.toml`` file exists."""
        return self.pylock_location is not None

    @property
    def any_exists(self) -> bool:
        """Returns True if either ``Pipfile.lock`` or ``pylock.toml`` exists."""
        # TODO(pylock): merge into a single ``exists`` once the format-
        # detection layer subsumes pylock.
        return self.exists or self.pylock_exists

    @property
    def pylock_output_path(self) -> str:
        """Returns the path where ``pylock.toml`` should be written.

        Defaults to ``<project>/pylock.toml``; can be overridden by
        ``[pipenv] pylock_name = "..."`` to produce
        ``pylock.<name>.toml``.
        """
        # TODO(pylock): move to the future pylock subsystem.
        pylock_name = self._project.settings.get("pylock_name")
        if pylock_name:
            return str(
                Path(self._project.project_directory) / f"pylock.{pylock_name}.toml"
            )
        return str(Path(self._project.project_directory) / "pylock.toml")

    # ---- content readers --------------------------------------------------

    @property
    def content(self):
        """Returns the lockfile content, checking ``pylock.toml`` first.

        Was ``Project.lockfile_content`` before T_D.5.
        """
        # TODO(pylock): format-detection seam. The pylock-vs-Pipfile.lock
        # dispatch will move into a dedicated format layer in 2027.
        if self.pylock_exists or self._project.settings.use_pylock:
            try:
                if self.pylock_exists:
                    pylock = PylockFile.from_path(self.pylock_location)
                    return pylock.convert_to_pipenv_lockfile()
            except Exception as e:
                err.print(f"[bold yellow]Error loading pylock.toml: {e}[/bold yellow]")
        return self.load()

    def as_dict(self, categories=None):
        """Returns the lockfile data dict, divided by category.

        Was ``Project.lockfile(categories=...)`` before T_D.5. Falls
        back to deriving meta from the Pipfile when neither a
        ``Pipfile.lock`` nor a ``pylock.toml`` can be read.
        """
        project = self._project
        lockfile_loaded = False
        lockfile = None
        if self.exists:
            try:
                lockfile = self.load(expand_env_vars=False)
                lockfile_loaded = True
            except LockfileCorruptException:
                raise
            except Exception:
                pass
        # TODO(pylock): format-detection seam — pylock fallback.
        if not lockfile_loaded and self.pylock_exists:
            try:
                pylock = PylockFile.from_path(self.pylock_location)
                lockfile = pylock.convert_to_pipenv_lockfile()
                lockfile_loaded = True
            except Exception:
                pass
        if not lockfile_loaded:
            with open(project.pipfile_location) as pf:
                plette_lock = plette.Lockfile.with_meta_from(
                    plette.Pipfile.load(pf), categories=categories
                )
                lockfile = plette_lock._data

        if categories is None:
            categories = project.get_package_categories(for_lockfile=True)
        for category in categories:
            lock_section = lockfile.get(category)
            if lock_section is None:
                lockfile[category] = {}

        return lockfile

    def load(self, expand_env_vars: bool = True):
        """Read ``Pipfile.lock`` from disk, repairing missing ``_meta``.

        Was ``Project.load_lockfile`` before T_D.5.
        """
        project = self._project
        lockfile_modified = False
        lockfile_path = Path(self.location)
        pipfile_path = Path(project.pipfile_location)

        try:
            with lockfile_path.open(encoding="utf-8") as lock:
                try:
                    j = json.load(lock)
                    project._lockfile_newlines = _preferred_newlines(lock)
                except JSONDecodeError as e:
                    raise LockfileCorruptException(str(lockfile_path)) from e
        except FileNotFoundError:
            j = {}

        if not j.get("_meta"):
            if pipfile_path.exists():
                with pipfile_path.open() as pf:
                    default_lockfile = plette.Lockfile.with_meta_from(
                        plette.Pipfile.load(pf), categories=[]
                    )
                    j["_meta"] = default_lockfile._data["_meta"]
                    lockfile_modified = True
            else:
                # No Pipfile available; provide minimal _meta so callers
                # don't break. This can happen when only pylock.toml exists.
                j["_meta"] = {
                    "hash": {"sha256": ""},
                    "pipfile-spec": 6,
                    "requires": {},
                    "sources": [],
                }
                lockfile_modified = True

        if j.get("default") is None:
            j["default"] = {}
            lockfile_modified = True

        if j.get("develop") is None:
            j["develop"] = {}
            lockfile_modified = True

        if lockfile_modified:
            self.write(j)

        if expand_env_vars:
            # Expand environment variables in Pipfile.lock at runtime.
            # Use expand_url_credentials() so that passwords with special
            # characters are URL-encoded after expansion (#4868).
            for i, _ in enumerate(j["_meta"].get("sources", {})):
                j["_meta"]["sources"][i]["url"] = expand_url_credentials(
                    j["_meta"]["sources"][i]["url"]
                )

        return j

    # ---- writer -----------------------------------------------------------

    def write(self, content) -> None:
        """Write out the lockfile (atomic).

        Was ``Project.write_lockfile`` before T_D.5. Always writes the
        legacy ``Pipfile.lock``; additionally writes a ``pylock.toml`` if
        ``[pipenv] use_pylock = true`` is set.
        """
        project = self._project
        # Always write the Pipfile.lock first.
        s = project._lockfile_encoder.encode(content)
        open_kwargs = {"newline": project._lockfile_newlines, "encoding": "utf-8"}
        with atomic_open_for_write(self.location, **open_kwargs) as f:
            f.write(s)
            # Write newline at end of document. GH-319.
            if not s.endswith("\n"):
                f.write("\n")

        # TODO(pylock): pylock side-write. Future redesign will move this
        # to the pylock subsystem and key it off explicit caller intent
        # rather than the [pipenv] use_pylock flag.
        if project.settings.use_pylock:
            try:
                pylock = PylockFile.from_lockfile(
                    lockfile_path=self.location,
                    pylock_path=self.pylock_output_path,
                )
                pylock.write()
                err.print(
                    f"[bold green]Generated pylock.toml at {self.pylock_output_path}[/bold green]"
                )
            except Exception as e:
                err.print(f"[bold red]Error generating pylock.toml: {e}[/bold red]")

    # ---- derived accessors -----------------------------------------------

    @property
    def package_names(self) -> dict[str, set[str]]:
        """Returns a per-category dict of canonicalized lockfile package
        names plus a ``combined`` aggregate.

        Was ``Project.lockfile_package_names`` before T_D.5.
        """
        project = self._project
        results: dict[str, set[str]] = {
            "combined": set(),
        }
        for category in project.get_package_categories(for_lockfile=True):
            category_packages = get_canonical_names(
                self.content[category].keys()
            )
            results[category] = set(category_packages)
            results["combined"] = results["combined"] | category_packages
        return results

    def meta(self) -> dict:
        """Build the ``_meta`` block for the lockfile from the Pipfile.

        Was ``Project.get_lockfile_meta`` before T_D.5.
        """
        # Imported lazily to avoid a top-level vendor import.
        from pipenv.utils.sources import Sources
        from pipenv.vendor.plette.lockfiles import PIPFILE_SPEC_CURRENT

        project = self._project
        if "source" in project.parsed_pipfile:
            sources = [dict(source) for source in project.parsed_pipfile["source"]]
        else:
            sources = project.sources.pipfile_sources(expand_vars=False)
        if not isinstance(sources, list):
            sources = [sources]
        return {
            "hash": {"sha256": project.calculate_pipfile_hash()},
            "pipfile-spec": PIPFILE_SPEC_CURRENT,
            "sources": [Sources.populate_source(s) for s in sources],
            "requires": project.parsed_pipfile.get("requires", {}),
        }

    def hash(self) -> str | None:
        """Return the cached ``_meta.hash.sha256`` from the lockfile.

        Was ``Project.get_lockfile_hash`` before T_D.5. Returns ``None``
        when no lockfile exists; returns the empty string when the
        lockfile is present but corrupted or has no hash.
        """
        lockfile_path = Path(self.location)
        if not lockfile_path.exists():
            return None

        try:
            lockfile = self.load(expand_env_vars=False)
        except LockfileCorruptException:
            return ""
        if "_meta" in lockfile and hasattr(lockfile, "keys"):
            return lockfile["_meta"].get("hash", {}).get("sha256") or ""
        return ""
