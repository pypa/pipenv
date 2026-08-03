"""The ``Pipfile`` subsystem of :class:`pipenv.project.Project`.

Fifth (and final) of the Initiative D extractions, after ``Sources``
(T_D.2), ``Settings`` (T_D.3), ``VenvLocator`` (T_D.4), and ``Lockfile``
(T_D.5). The 38 ``Pipfile``-classified methods on
``pipenv.project.Project`` move into the :class:`Pipfile` class in this
module, accessed via a ``@cached_property`` ``Project.pipfile``.

Naming-collision note: this file already hosted a legacy plette-wrapper
dataclass called ``Pipfile`` (used by :mod:`pipenv.utils.locking`).
T_D.6 renamed that legacy class to :class:`PlettePipfile` so the
unqualified name ``Pipfile`` is now reserved for the Initiative-D
subsystem.

Behaviour is preserved verbatim from the previous in-``Project``
implementation; this is a relocation, not a rewrite. :class:`Pipfile`
owns the ``parsed_pipfile`` mtime cache (was ``_parsed_pipfile_cache``
/ ``_parsed_pipfile_mtime_ns`` on ``Project``) — the cache lives with
the subsystem that owns the file, and :meth:`Pipfile.write_toml`
invalidates it directly.

API rename (matches T_D.2 Sources / T_D.4 VenvLocator / T_D.5 Lockfile
patterns; the ``pipfile_`` and ``_pipfile`` prefixes/suffixes drop
because the subsystem itself is named ``pipfile``):

  project.parsed_pipfile                 -> project.pipfile.parsed
  project.pipfile_location               -> project.pipfile.location
  project.pipfile_exists                 -> project.pipfile.exists
  project.pipfile_is_empty               -> project.pipfile.is_empty
  project.read_pipfile()                 -> project.pipfile.read()
  project.name                           -> project.pipfile.name
  project.project_directory              -> project.pipfile.project_directory
  project.required_python_version        -> project.pipfile.required_python_version
  project.requirements_location          -> project.pipfile.requirements_location
  project.requirements_exists            -> project.pipfile.requirements_exists
  project.get_pipfile_section(...)       -> project.pipfile.get_section(...)
  project.get_package_categories(...)    -> project.pipfile.get_package_categories(...)
  project.pipfile_package_names          -> project.pipfile.package_names
  project.write_toml(...)                -> project.pipfile.write_toml(...)
  project.has_script(...)                -> project.pipfile.has_script(...)
  project.build_script(...)              -> project.pipfile.build_script(...)
  project.proper_names                   -> project.pipfile.proper_names
  project.register_proper_name(...)      -> project.pipfile.register_proper_name(...)
  project.pipfile_build_requires         -> project.pipfile.build_requires
  project.calculate_pipfile_hash()       -> project.pipfile.calculate_hash()
  project.all_packages                   -> project.pipfile.all_packages
  project.packages                       -> project.pipfile.packages
  project.dev_packages                   -> project.pipfile.dev_packages
  project.get_editable_packages(cat)     -> project.pipfile.get_editable_packages(cat)
  project.get_package_name_in_pipfile(...) -> project.pipfile.get_package_name(...)
  project.get_pipfile_entry(...)         -> project.pipfile.get_entry(...)
  project.remove_package_from_pipfile(...) -> project.pipfile.remove_package(...)
  project.remove_packages_from_pipfile(...) -> project.pipfile.remove_packages(...)
  project.reset_category_in_pipfile(...) -> project.pipfile.reset_category(...)
  project.generate_package_pipfile_entry(...) -> project.pipfile.generate_entry(...)
  project.add_package_to_pipfile(...)    -> project.pipfile.add_package(...)
  project.add_pipfile_entry_to_pipfile(...) -> project.pipfile.add_entry(...)
  project.add_packages_to_pipfile_batch(...) -> project.pipfile.add_packages_batch(...)
  project.recase_pipfile()               -> project.pipfile.recase()
  project.ensure_proper_casing()         -> project.pipfile.ensure_proper_casing()
  project.proper_case_section(...)       -> project.pipfile.proper_case_section(...)

Cross-subsystem references:

- ``Lockfile.meta()`` calls ``project.pipfile.calculate_hash()``.
- ``Sources.add_index_to_pipfile`` writes via ``project.pipfile.write_toml``.
- ``VenvLocator`` reads ``project.pipfile.exists``,
  ``project.pipfile.parsed``, ``project.pipfile.project_directory``,
  ``project.pipfile.name``, ``project.pipfile.location``.
- ``Settings.update`` writes via ``project.pipfile.write_toml``.
- ``project.proper_names`` lives on ``Pipfile`` (the conceptual owner —
  case-fixing the Pipfile) but reads the on-disk path through
  ``project.venv_locator.proper_names_db_path``.

See ``docs/dev/initiative-d-inventory.md`` (esp. §2, §3, §5, §8.5) for
the cluster boundary and lazy-init notes.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from pipenv import environments
from pipenv.utils import console, err
from pipenv.utils.constants import VCS_LIST
from pipenv.utils.dependencies import (
    determine_package_name,
    determine_path_specifier,
    determine_vcs_specifier,
    expansive_install_req_from_line,
    extract_vcs_url,
    get_canonical_names,
    import_requirements,
    is_editable,
    is_vcs,
    normalize_editable_path_for_pip,
    pep423_name,
)
from pipenv.utils.internet import get_url_name, proper_case
from pipenv.utils.markers import RequirementError
from pipenv.utils.toml import (
    cleanup_toml,
    convert_toml_outline_tables,
    tomlkit_value_to_python,
)
from pipenv.vendor import plette, tomlkit
from pipenv.vendor.plette import pipfiles
from pipenv.vendor.tomlkit.items import SingleKey, Table

DEFAULT_NEWLINES = "\n"

# Sections that are not package categories (used by ``get_package_categories``).
NON_CATEGORY_SECTIONS = {
    "build-system",
    "pipenv",
    "requires",
    "scripts",
    "source",
}


def walk_up(bottom):
    """mimic os.walk, but walk 'up' instead of down the directory tree."""
    # Convert to Path object and resolve to absolute path
    bottom_path = Path(bottom).resolve()

    # Get files in current dir
    try:
        # Path.iterdir() returns Path objects for all children
        path_objects = list(bottom_path.iterdir())
    except Exception:
        return

    # Sort into directories and non-directories
    dirs, nondirs = [], []
    for path in path_objects:
        if path.is_dir():
            dirs.append(path.name)
        else:
            nondirs.append(path.name)

    yield str(bottom_path), dirs, nondirs

    # Get parent directory
    new_path = bottom_path.parent.resolve()

    # See if we are at the top (parent is same as current)
    if new_path == bottom_path:
        return

    yield from walk_up(new_path)


def find_pipfile(max_depth=3):
    """Returns the path of a Pipfile in parent directories."""
    i = 0
    # Get current working directory as a Path object
    current_dir = Path.cwd()

    for directory, _, _ in walk_up(current_dir):
        i += 1

        if i < max_depth:
            # Create a Path object for the potential Pipfile
            pipfile_path = Path(directory) / "Pipfile"

            # Check if it's a file
            if pipfile_path.is_file():
                return str(pipfile_path)

    raise RuntimeError("No Pipfile found!")


def preferred_newlines(f):
    if isinstance(f.newlines, str):
        return f.newlines
    return DEFAULT_NEWLINES


def ensure_pipfile(
    project, validate=True, skip_requirements=False, system=False, pipfile_categories=None
):
    """Creates a Pipfile for the project, if it doesn't exist."""

    # Assert Pipfile exists.
    python = (
        project.venv_locator._which("python")
        if not (project.s.USING_DEFAULT_PYTHON or system)
        else None
    )
    if project.pipfile.is_empty:
        # If there's a requirements file, but no Pipfile...
        if project.pipfile.requirements_exists and not skip_requirements:
            # Get the directory containing the requirements file
            requirements_path = Path(project.pipfile.requirements_location)
            requirements_dir_path = requirements_path.parent

            console.print(
                f"[bold]requirements.txt[/bold] found in [bold yellow]{requirements_dir_path}"
                "[/bold yellow] instead of [bold]Pipfile[/bold]! Converting..."
            )
            # Create a Pipfile...
            project.create_pipfile(python=python)
            with console.status(
                "Importing requirements...", spinner=project.s.PIPENV_SPINNER
            ) as st:
                # Import requirements.txt.
                try:
                    import_requirements(project, categories=pipfile_categories)
                except Exception:
                    err.print(environments.PIPENV_SPINNER_FAIL_TEXT.format("Failed..."))
                else:
                    st.console.print(
                        environments.PIPENV_SPINNER_OK_TEXT.format("Success!")
                    )
            # Warn the user of side-effects.
            console.print(
                "[bold red]Warning[/bold red]: Your [bold]Pipfile[/bold] now contains pinned versions, "
                "if your [bold]requirements.txt[/bold] did. \n"
                'We recommend updating your [bold]Pipfile[/bold] to specify the [bold]"*"'
                "[/bold] version, instead."
            )
        else:
            err.print("Creating a Pipfile for this project...", style="bold")
            # Create the pipfile if it doesn't exist.
            project.create_pipfile(python=python)
    # Validate the Pipfile's contents.
    if validate and project.venv_locator.exists and not project.s.PIPENV_SKIP_VALIDATION:
        # Ensure that Pipfile is using proper casing.
        p = project.pipfile.parsed
        changed = project.pipfile.ensure_proper_casing()
        # Write changes out to disk.
        if changed:
            err.print("Fixing package names in Pipfile...", style="bold")
            project.pipfile.write_toml(p)


def reorder_source_keys(data):
    # type: (tomlkit.toml_document.TOMLDocument) -> tomlkit.toml_document.TOMLDocument
    sources = []  # type: sources_type
    for source_key in ["source", "sources"]:
        sources.extend(data.get(source_key, tomlkit.aot()).value)
    new_source_aot = tomlkit.aot()
    for entry in sources:
        table = tomlkit.table()  # type: tomlkit.items.Table
        source_entry = PipfileLoader.populate_source(entry.copy())
        for key in ["name", "url", "verify_ssl"]:
            table.update({key: source_entry[key]})
        new_source_aot.append(table)
    data["source"] = new_source_aot
    if data.get("sources", None):
        del data["sources"]
    return data


@dataclass
class ProjectFile:
    location: Path
    line_ending: str
    model: Any | None = field(default_factory=dict)

    @classmethod
    def read(cls, location: str, model_cls, invalid_ok: bool = False) -> ProjectFile:
        # Convert string location to Path
        path = Path(location)
        if not path.exists() and not invalid_ok:
            raise FileNotFoundError(location)
        try:
            with path.open(encoding="utf-8") as f:
                model = model_cls.load(f)
                line_ending = preferred_newlines(f)
        except Exception:
            if not invalid_ok:
                raise
            model = {}
            line_ending = DEFAULT_NEWLINES
        return cls(location=path, line_ending=line_ending, model=model)

    def write(self) -> None:
        kwargs = {"encoding": "utf-8", "newline": self.line_ending}
        with self.location.open("w", **kwargs) as f:
            if self.model:
                self.model.dump(f)

    def dumps(self) -> str:
        if self.model:
            strio = io.StringIO()
            self.model.dump(strio)
            return strio.getvalue()
        return ""


class PipfileLoader(pipfiles.Pipfile):
    @classmethod
    def validate(cls, data):
        # type: (tomlkit.toml_document.TOMLDocument) -> None
        for key, klass in pipfiles.PIPFILE_SECTIONS.items():
            if key not in data or key == "sources":
                continue
            with contextlib.suppress(Exception):
                klass.validate(data[key])

    @classmethod
    def ensure_package_sections(cls, data):
        # type: (tomlkit.toml_document.TOMLDocument[Text, Any]) -> tomlkit.toml_document.TOMLDocument[Text, Any]
        """Ensure that all pipfile package sections are present in the given
        toml document.

        :param :class:`~tomlkit.toml_document.TOMLDocument` data: The toml document to
            ensure package sections are present on
        :return: The updated toml document, ensuring ``packages`` and ``dev-packages``
            sections are present
        :rtype: :class:`~tomlkit.toml_document.TOMLDocument`
        """
        package_keys = (k for k in pipfiles.PIPFILE_SECTIONS if k.endswith("packages"))
        for key in package_keys:
            if key not in data:
                data.update({key: tomlkit.table()})
        return data

    @classmethod
    def populate_source(cls, source):
        """Derive missing values of source from the existing fields."""
        # Only URL pararemter is mandatory, let the KeyError be thrown.
        if "name" not in source:
            source["name"] = get_url_name(source["url"])
        if "verify_ssl" not in source:
            source["verify_ssl"] = "https://" in source["url"]
        if not isinstance(source["verify_ssl"], bool):
            source["verify_ssl"] = str(source["verify_ssl"]).lower() == "true"
        return source

    @classmethod
    def load(cls, f, encoding=None):
        # type: (Any, Text) -> PipfileLoader
        content = f.read()
        if encoding is not None:
            content = content.decode(encoding)
        _data = tomlkit.loads(content)
        should_reload = "source" not in _data
        _data = reorder_source_keys(_data)
        if should_reload:
            if "sources" in _data:
                content = tomlkit.dumps(_data)
            else:
                # HACK: There is no good way to prepend a section to an existing
                # TOML document, but there's no good way to copy non-structural
                # content from one TOML document to another either. Modify the
                # TOML content directly, and load the new in-memory document.
                sep = "" if content.startswith("\n") else "\n"
                content = pipfiles.DEFAULT_SOURCE_TOML + sep + content
        data = tomlkit.loads(content)
        data = cls.ensure_package_sections(data)
        instance = cls(data)
        instance._data = dict(instance._data)
        return instance

    def __contains__(self, key):
        # type: (Text) -> bool
        if key not in self._data:
            package_keys = self._data.get("packages", {}).keys()
            dev_package_keys = self._data.get("dev-packages", {}).keys()
            return any(key in pkg_list for pkg_list in (package_keys, dev_package_keys))
        return True

    def __getattribute__(self, key):
        # type: (Text) -> Any
        if key == "source":
            return self._data[key]
        return super().__getattribute__(key)


@dataclass
class PlettePipfile:
    """Legacy plette-wrapper Pipfile dataclass.

    Renamed from ``Pipfile`` to ``PlettePipfile`` in T_D.6 to free the
    unqualified ``Pipfile`` name for the Initiative-D subsystem class
    below. The sole consumer is
    :meth:`pipenv.utils.locking.Lockfile.lockfile_from_pipfile`.
    """

    path: Path
    projectfile: ProjectFile
    pipfile: PipfileLoader | None = None
    _pyproject: tomlkit.TOMLDocument | None = field(default_factory=tomlkit.document)
    build_system: dict | None = field(default_factory=dict)
    _requirements: list | None = field(default_factory=list)
    _dev_requirements: list | None = field(default_factory=list)

    def __post_init__(self):
        # Validators or equivalent logic here
        self.path = self._get_path(self.path)
        self.projectfile = self._get_projectfile(self.projectfile, {"path": self.path})
        self.pipfile = self._get_pipfile(self.pipfile, {"projectfile": self.projectfile})

    @staticmethod
    def _get_path(v: Path) -> Path:
        return v or Path(os.curdir).absolute()

    @staticmethod
    def _get_projectfile(v: ProjectFile, values: dict) -> ProjectFile:
        return v or PlettePipfile.load_projectfile(os.curdir, create=False)

    @staticmethod
    def _get_pipfile(v: PipfileLoader, values: dict) -> PipfileLoader:
        return v or values["projectfile"].model

    @property
    def root(self):
        return self.path.parent

    @property
    def extended_keys(self):
        return list(
            itertools.product(("packages", "dev-packages"), ("", "vcs", "editable"))
        )

    def get_deps(self, dev=False, only=True):
        from pipenv.utils.dependencies import merge_items

        deps = {}  # type: Dict[Text, Dict[Text, Union[List[Text], Text]]]
        if dev:
            deps.update(dict(self.pipfile._data.get("dev-packages", {})))
            if only:
                return deps
        return tomlkit_value_to_python(
            merge_items([deps, dict(self.pipfile._data.get("packages", {}))])
        )

    def get(self, k):
        return self.__getitem__(k)

    def __contains__(self, k):
        return k in self.extended_keys or k in self.pipfile

    def __getitem__(self, k, *args, **kwargs):
        retval = None
        pipfile = self.pipfile
        section = None
        pkg_type = None
        try:
            retval = pipfile[k]
        except KeyError:
            if "-" in k:
                section, _, pkg_type = k.rpartition("-")
                vals = getattr(pipfile.get(section, {}), "_data", {})
                vals = tomlkit_value_to_python(vals)
                if pkg_type == "vcs":
                    retval = {k: v for k, v in vals.items() if is_vcs(v)}
                elif pkg_type == "editable":
                    retval = {k: v for k, v in vals.items() if is_editable(v)}
            if retval is None:
                raise
        else:
            retval = getattr(retval, "_data", retval)
        return retval

    def __getattr__(self, k, *args, **kwargs):
        pipfile = self.pipfile
        try:
            retval = super(PlettePipfile).__getattribute__(k)
        except AttributeError:
            retval = getattr(pipfile, k, None)
        return retval

    @property
    def requires_python(self):
        # type: () -> bool
        return getattr(
            self.pipfile.requires,
            "python_version",
            getattr(self.pipfile.requires, "python_full_version", None),
        )

    @property
    def allow_prereleases(self):
        # type: () -> bool
        return self.pipfile.get("pipenv", {}).get("allow_prereleases", False)

    @classmethod
    def read_projectfile(cls, path):
        # type: (Text) -> ProjectFile
        """Read the specified project file and provide an interface for
        writing/updating.

        :param Text path: Path to the target file.
        :return: A project file with the model and location for interaction
        :rtype: :class:`~project.ProjectFile`
        """
        pf = ProjectFile.read(path, PipfileLoader, invalid_ok=True)
        return pf

    @classmethod
    def load_projectfile(cls, path: str, create: bool = False) -> ProjectFile:
        """..."""

        if not path:
            raise RuntimeError("Must pass a path to classmethod 'Pipfile.load'")
        if not isinstance(path, Path):
            path = Path(path).absolute()
        pipfile_path = path if path.is_file() else path.joinpath("Pipfile")
        project_path = pipfile_path.parent
        if not project_path.exists():
            raise RequirementError(f"{path} is not a valid project path!")
        elif (not pipfile_path.exists() or not pipfile_path.is_file()) and not create:
            raise RequirementError(f"{pipfile_path} is not a valid Pipfile")
        return cls.read_projectfile(pipfile_path)

    @classmethod
    def load(cls, path: str, create: bool = False) -> PlettePipfile:
        """..."""

        projectfile = cls.load_projectfile(path, create=create)
        pipfile = projectfile.model
        creation_args = {
            "projectfile": projectfile,
            "pipfile": pipfile,
            "path": Path(projectfile.location),
        }
        return cls(**creation_args)


# ============================================================================
# Initiative D — Pipfile subsystem of pipenv.project.Project (T_D.6)
# ============================================================================


class Pipfile:
    """``Pipfile`` subsystem of :class:`pipenv.project.Project`.

    Constructed with a back-reference to its owning ``Project``. Owns
    the previously-on-``Project`` mtime-invalidated ``parsed_pipfile``
    cache (``_parsed_pipfile_cache`` + ``_parsed_pipfile_mtime_ns``)
    and the ``_pipfile_location`` / ``_requirements_location`` /
    ``_pipfile_newlines`` lazy attributes.

    The cache is invalidated in :meth:`write_toml` whenever the on-disk
    Pipfile changes; external callers must route writes through
    :meth:`write_toml` rather than touching the cache directly.
    """

    def __init__(self, project):
        self._project = project
        self._name = None
        self._location = None
        self._requirements_location = None
        self._newlines = DEFAULT_NEWLINES
        self._parsed_cache = None
        self._parsed_mtime_ns = None

    # ---- location / existence / name -------------------------------------

    @property
    def location(self) -> str:
        """Absolute path to the on-disk Pipfile.

        Honours ``PIPENV_PIPFILE``; otherwise walks parent directories
        up to ``PIPENV_MAX_DEPTH`` looking for a Pipfile, defaulting to
        ``"Pipfile"`` (relative to ``cwd``) if none is found. Cached
        after first access — once captured the location does not
        change within a process lifetime.
        """
        project = self._project
        if project.s.PIPENV_PIPFILE:
            return project.s.PIPENV_PIPFILE

        if self._location is None:
            from pipenv.environments import normalize_pipfile_path

            try:
                loc = find_pipfile(max_depth=project.s.PIPENV_MAX_DEPTH)
            except RuntimeError:
                loc = "Pipfile"
            self._location = normalize_pipfile_path(loc)
        return self._location

    @property
    def exists(self) -> bool:
        """``True`` if a Pipfile exists at :attr:`location`."""
        return Path(self.location).is_file()

    @property
    def name(self) -> str:
        """Parent-dir name of :attr:`location` (the project's slug)."""
        if self._name is None:
            self._name = Path(self.location).parent.name
        return self._name

    @property
    def project_directory(self) -> str:
        """Absolute parent directory of :attr:`location`."""
        return str(Path(self.location).parent.absolute())

    @property
    def required_python_version(self) -> str | None:
        """Reads ``[requires] python_full_version`` or ``python_version``.

        Returns ``None`` when the Pipfile does not exist or the version
        is the wildcard ``"*"``.
        """
        if self.exists:
            required = self.parsed.get("requires", {}).get("python_full_version")
            if not required:
                required = self.parsed.get("requires", {}).get("python_version")
            if required != "*":
                return required
        return None

    # ---- requirements.txt sibling ----------------------------------------

    @property
    def requirements_location(self) -> str | None:
        """Path to a sibling ``requirements.txt`` if one exists."""
        from pipenv.utils.shell import find_requirements

        if self._requirements_location is None:
            try:
                loc = find_requirements(max_depth=self._project.s.PIPENV_MAX_DEPTH)
            except RuntimeError:
                loc = None
            self._requirements_location = loc
        return self._requirements_location

    @property
    def requirements_exists(self) -> bool:
        """``True`` if a sibling ``requirements.txt`` exists."""
        return bool(self.requirements_location)

    # ---- parsing / reading -----------------------------------------------

    @property
    def parsed(self) -> tomlkit.toml_document.TOMLDocument | dict:
        """Parse the Pipfile into a tomlkit document, mtime-cached.

        Parsing tomlkit on every access is expensive (a single ``lock``
        call hit this 500+ times in a pre-cache benchmark). The parsed
        document is cached and refreshed when the file's mtime changes
        so external edits still take effect; writes from pipenv itself
        invalidate the cache via :meth:`write_toml`.
        """
        if not self.exists:
            return self._parse("")
        try:
            mtime_ns = os.stat(self.location).st_mtime_ns
        except OSError:
            mtime_ns = None
        if (
            self._parsed_cache is not None
            and mtime_ns is not None
            and self._parsed_mtime_ns == mtime_ns
        ):
            return self._parsed_cache
        contents = self.read()
        parsed = self._parse(contents)
        self._parsed_cache = parsed
        self._parsed_mtime_ns = mtime_ns
        return parsed

    def read(self) -> str:
        """Return raw Pipfile contents (empty string if absent).

        Side-effect: records the file's newline style in
        ``self._newlines`` for round-tripping via :meth:`write_toml`.
        """
        if not self.exists:
            return ""
        with open(self.location) as f:
            contents = f.read()
            self._newlines = preferred_newlines(f)
        return contents

    @staticmethod
    def _parse(contents: str):
        try:
            return tomlkit.parse(contents)
        except Exception:
            # We lose comments here, but it's for the best.
            # Fallback to toml parser, for large files.
            try:
                import tomllib as _toml
            except ImportError:
                from pipenv.patched.pip._vendor import tomli as _toml
            return _toml.loads(contents)

    @property
    def is_empty(self) -> bool:
        """``True`` if the Pipfile is missing or empty on disk."""
        if not self.exists:
            return True
        if not self.read():
            return True
        return False

    # ---- section / category accessors ------------------------------------

    def get_section(self, section):
        """Returns the details from the named section of the Pipfile."""
        return self.parsed.get(section, {})

    def get_package_categories(self, for_lockfile=False):
        """Ensure we get only package categories and that the default
        packages section is first.
        """
        categories = set(self.parsed.keys())
        package_categories = (
            categories - NON_CATEGORY_SECTIONS - {"packages", "dev-packages"}
        )
        if for_lockfile:
            return ["default", "develop"] + list(package_categories)
        else:
            return ["packages", "dev-packages"] + list(package_categories)

    @property
    def package_names(self) -> dict[str, set[str]]:
        """Per-category canonicalized package names plus a ``combined`` set."""
        result = {}
        combined = set()
        for category in self.get_package_categories():
            packages = self.get_section(category)
            keys = get_canonical_names(packages.keys())
            combined |= keys
            result[category] = keys
        result["combined"] = combined
        return result

    @property
    def all_packages(self):
        """Flattened union of every package category in the Pipfile."""
        packages = {}
        for category in self.get_package_categories():
            packages.update(self.parsed.get(category, {}))
        return packages

    @property
    def packages(self):
        """Contents of the ``[packages]`` section."""
        return self.get_section("packages")

    @property
    def dev_packages(self):
        """Contents of the ``[dev-packages]`` section."""
        return self.get_section("dev-packages")

    def get_editable_packages(self, category):
        """Editable entries from the named category."""
        return {
            k: v
            for k, v in self.parsed.get(category, {}).items()
            if is_editable(v)
        }

    def _get_vcs_packages(self, dev=False):
        """Internal: VCS-shaped entries from packages/dev-packages."""
        section = "dev-packages" if dev else "packages"
        return {
            k: v
            for k, v in self.parsed.get(section, {}).items()
            if is_vcs(v) or is_vcs(k)
        } or {}

    # ---- build-system metadata -------------------------------------------

    @property
    def build_requires(self) -> list[str]:
        """``[build-system] requires`` list (empty if absent).

        Returns build-system requirements declared in the Pipfile that
        must be installed before other packages can be resolved (e.g.
        custom setuptools wrappers used in setup.py).

        Example Pipfile::

            [build-system]
            requires = ["stwrapper", "setuptools>=40.8.0", "wheel"]
        """
        if not self.exists:
            return []
        build_system = self.parsed.get("build-system", {})
        return list(build_system.get("requires", []))

    # ---- scripts ---------------------------------------------------------

    def has_script(self, name: str) -> bool:
        """``True`` if ``[scripts]`` defines an entry with the given name."""
        try:
            return name in self.parsed["scripts"]
        except KeyError:
            return False

    def build_script(self, name: str, extra_args=None):
        """Return a ``Script`` for the named ``[scripts]`` entry."""
        # Lazy import to avoid pulling cmdparse at module-load time.
        from pipenv.cmdparse import Script

        try:
            script = Script.parse(self.parsed["scripts"][name])
        except KeyError:
            script = Script(name)
        if extra_args:
            script.extend(extra_args)
        return script

    # ---- proper-names DB (lives under the venv, owned conceptually here) -

    @property
    def proper_names(self) -> list[str]:
        """Read the proper-names DB file (one canonical name per line)."""
        with self._project.venv_locator.proper_names_db_path.open() as f:
            return f.read().splitlines()

    def register_proper_name(self, name: str) -> None:
        """Append a name to the proper-names DB."""
        with self._project.venv_locator.proper_names_db_path.open("a") as f:
            f.write(f"{name}\n")

    # ---- writer -----------------------------------------------------------

    def write_toml(self, data, path=None) -> None:
        """Writes ``data`` out as TOML to ``path`` (defaults to the Pipfile).

        When the written file IS the Pipfile, invalidates the
        ``parsed`` cache so the next read picks up the new contents.
        """
        if path is None:
            path = self.location
        data = convert_toml_outline_tables(data, self._project)
        try:
            formatted_data = tomlkit.dumps(data).rstrip()
        except Exception:
            document = tomlkit.document()
            for category in self.get_package_categories():
                document[category] = tomlkit.table()
                # Convert things to inline tables — fancy :)
                for package in data.get(category, {}):
                    if hasattr(data[category][package], "keys"):
                        table = tomlkit.inline_table()
                        table.update(data[category][package])
                        document[category][package] = table
                    else:
                        document[category][package] = tomlkit.string(
                            data[category][package]
                        )
            formatted_data = tomlkit.dumps(document).rstrip()

        is_pipfile = Path(path).resolve() == Path(self.location).resolve()
        newlines = self._newlines if is_pipfile else DEFAULT_NEWLINES
        formatted_data = cleanup_toml(formatted_data)
        with open(path, "w", newline=newlines) as f:
            f.write(formatted_data)
        if is_pipfile:
            self._parsed_cache = None
            self._parsed_mtime_ns = None

    # ---- key lookup / casing --------------------------------------------

    def get_package_name(self, package_name, category):
        """Return the Pipfile key (preserving casing) that matches a
        canonicalised package name, or the input name if absent.
        """
        section = self.parsed.get(category, {})
        normalized_name = pep423_name(package_name)
        for name in section:
            if pep423_name(name) == normalized_name:
                return name
        return package_name

    def get_entry(self, package_name, category):
        """Return the Pipfile entry for a package, regardless of casing."""
        name = self.get_package_name(package_name, category)
        return self.parsed.get(category, {}).get(name)

    def _sort_category(self, category) -> Table:
        """Internal: produce a sorted copy of a category table."""
        # copy table or create table from dict-like object
        table = tomlkit.table()
        if isinstance(category, Table):
            table.update(category.value)
        else:
            table.update(category)

        # sort the table internally
        table._value._body.sort(key=lambda t: t[0] and t[0].key or "")
        for index, (key, _) in enumerate(table._value._body):
            assert isinstance(key, SingleKey)
            indices = table._value._map[key]
            if isinstance(indices, tuple):
                table._value._map[key] = (index,) + indices[1:]
            else:
                table._value._map[key] = index

        return table

    # ---- mutators -------------------------------------------------------

    def remove_package(self, package_name, category) -> bool:
        """Remove a package from the named category. Returns success."""
        p = self.parsed
        section = p.get(category, {})
        normalized_name = pep423_name(package_name)
        name = None
        for key in section:
            if pep423_name(key) == normalized_name:
                name = key
                break
        if name and name in section:
            del p[category][name]
            if self._project.settings.get("sort_pipfile"):
                p[category] = self._sort_category(p[category])
            self.write_toml(p)
            return True
        return False

    def reset_category(self, category) -> bool:
        """Wipe a category in the Pipfile (preserving its empty section)."""
        p = self.parsed
        if category:
            del p[category]
            p[category] = {}
            self.write_toml(p)
            return True
        return False

    def remove_packages(self, packages) -> None:
        """Remove every Pipfile entry matching the supplied package names."""
        parsed = self.parsed
        packages = {pep423_name(pkg) for pkg in packages}
        for category in self.get_package_categories():
            pipfile_section = parsed.get(category, {})
            pipfile_packages = {pep423_name(pkg_name) for pkg_name in pipfile_section}
            to_remove = packages & pipfile_packages
            for pkg in to_remove:
                pkg_name = self.get_package_name(pkg, category=category)
                if pkg_name:
                    del parsed[category][pkg_name]
        self.write_toml(parsed)

    def generate_entry(
        self, package, pip_line, category=None, index_name=None, no_binary=False
    ):
        """Build a Pipfile entry dict from an ``InstallRequirement`` and the
        raw pip-install line that produced it.
        """
        from pipenv.patched.pip._internal.req.req_install import InstallRequirement

        # Don't re-capitalize file URLs or VCSs.
        if not isinstance(package, InstallRequirement):
            package, req_name = expansive_install_req_from_line(package.strip())
        else:
            _, req_name = expansive_install_req_from_line(pip_line.strip())

        if req_name is None:
            req_name = determine_package_name(package)
        path_specifier = determine_path_specifier(package)
        vcs_specifier = determine_vcs_specifier(package)
        name = self.get_package_name(req_name, category=category)
        normalized_name = pep423_name(req_name)

        extras = package.extras
        specifier = "*"
        if package.req and package.specifier:
            specifier = str(package.specifier)

        # Construct package requirement
        entry = {}
        if extras:
            entry["extras"] = list(extras)
        if path_specifier:
            editable = pip_line.startswith("-e")
            # Strip "-e" prefix to get the raw package reference from the install line.
            raw_ref = pip_line[2:].strip() if editable else pip_line.strip()
            raw_ref = raw_ref.strip('"').strip("'")
            # Use "file" for remote HTTP/HTTPS URLs and explicit file:// URLs;
            # use "path" for plain local filesystem paths (e.g. ".", "./lib").
            is_http_url = path_specifier.startswith(("http:", "https:"))
            is_file_url = raw_ref.startswith("file:")
            key = "file" if (is_http_url or is_file_url) else "path"
            if is_file_url:
                # Preserve the original file:// URL exactly as the user typed it.
                entry[key] = unquote(raw_ref)
            else:
                entry[key] = unquote(
                    normalize_editable_path_for_pip(path_specifier)
                    if editable
                    else str(path_specifier)
                )
            if editable:
                entry["editable"] = editable
        elif vcs_specifier:
            for vcs in VCS_LIST:
                if vcs in package.link.scheme:
                    if pip_line.startswith("-e"):
                        entry["editable"] = True
                        pip_line = pip_line.replace("-e ", "")
                    if "[" in pip_line and "]" in pip_line:
                        extras_section = pip_line.split("[")[1].split("]")[0]
                        entry["extras"] = sorted(
                            [extra.strip() for extra in extras_section.split(",")]
                        )
                    if "@ " in pip_line:
                        vcs_part = pip_line.split("@ ", 1)[1]
                    else:
                        vcs_part = pip_line
                    vcs_parts = vcs_part.rsplit("@", 1)
                    if len(vcs_parts) > 1:
                        entry["ref"] = vcs_parts[1].split("#", 1)[0].strip()
                    vcs_url = vcs_parts[0].strip()
                    vcs_url = extract_vcs_url(vcs_url)
                    entry[vcs] = vcs_url

                    # Check and extract subdirectory fragment
                    if package.link.subdirectory_fragment:
                        entry["subdirectory"] = package.link.subdirectory_fragment
                    break
        else:
            entry["version"] = specifier

        if index_name:
            entry["index"] = index_name
        elif hasattr(package, "index"):
            entry["index"] = package.index

        # Include markers (e.g., sys_platform == 'win32') if present
        if package.markers:
            entry["markers"] = str(package.markers)

        # Store no_binary flag so pipenv re-applies --no-binary on future installs
        if no_binary:
            entry["no_binary"] = True

        if len(entry) == 1 and "version" in entry:
            return name, normalized_name, specifier
        else:
            return name, normalized_name, entry

    def add_package(self, package, pip_line, dev=False, category=None, no_binary=False):
        """Add a single package — generate entry + add to Pipfile."""
        category = category if category else "dev-packages" if dev else "packages"
        name, normalized_name, entry = self.generate_entry(
            package, pip_line, category=category, no_binary=no_binary
        )
        return self.add_entry(name, normalized_name, entry, category=category)

    def add_entry(self, name, normalized_name, entry, category=None):
        """Append a prepared Pipfile entry to the named category."""
        newly_added = False

        # Read and append Pipfile.
        parsed_pipfile = self.parsed

        # Set empty group if it doesn't exist yet.
        if category not in parsed_pipfile:
            parsed_pipfile[category] = {}

        section = parsed_pipfile.get(category, {})
        for entry_name in section.copy().keys():
            if entry_name.lower() == normalized_name.lower():
                del parsed_pipfile[category][entry_name]

        # Add the package to the group.
        if normalized_name not in parsed_pipfile[category]:
            newly_added = True

        parsed_pipfile[category][normalized_name] = entry

        if self._project.settings.get("sort_pipfile"):
            parsed_pipfile[category] = self._sort_category(parsed_pipfile[category])

        # Write Pipfile.
        self.write_toml(parsed_pipfile)
        return newly_added, category, normalized_name

    def add_packages_batch(self, packages_data, dev=False, categories=None):
        """Add multiple packages to the Pipfile in a single write.

        Args:
            packages_data: List of ``(package, pip_line)`` tuples, or
                list of dicts with the pre-processed ``name``,
                ``normalized_name`` and ``entry`` keys.
            dev: When ``True`` and ``categories`` is unset, target
                ``dev-packages``.
            categories: Explicit categories to target.

        Returns:
            List of ``(newly_added, category, normalized_name)`` tuples
            — one per package processed.
        """
        if not packages_data:
            return []

        # Determine target categories
        if categories is None or (isinstance(categories, list) and not categories):
            categories = ["dev-packages" if dev else "packages"]
        elif isinstance(categories, str):
            categories = [categories]

        # Read Pipfile once
        parsed_pipfile = self.parsed
        results = []

        # Ensure all categories exist
        for category in categories:
            if category not in parsed_pipfile:
                parsed_pipfile[category] = {}

        # Process all packages
        for package_data in packages_data:
            if isinstance(package_data, tuple) and len(package_data) == 2:
                package, pip_line = package_data

                # Generate entry for this package
                name, normalized_name, entry = self.generate_entry(
                    package, pip_line, category=categories[0]
                )

                # Add to each specified category
                for category in categories:
                    newly_added = False

                    # Remove any existing entries with different casing
                    section = parsed_pipfile.get(category, {})
                    for entry_name in section.copy().keys():
                        if entry_name.lower() == normalized_name.lower():
                            del parsed_pipfile[category][entry_name]

                    # Check if this is a new package
                    if normalized_name not in parsed_pipfile[category]:
                        newly_added = True

                    # Add the package
                    parsed_pipfile[category][normalized_name] = entry
                    results.append((newly_added, category, normalized_name))

            elif isinstance(package_data, dict):
                # Handle pre-processed package data
                name = package_data.get("name")
                normalized_name = package_data.get("normalized_name")
                entry = package_data.get("entry")

                if name and normalized_name and entry:
                    for category in categories:
                        newly_added = False

                        # Remove any existing entries with different casing
                        section = parsed_pipfile.get(category, {})
                        for entry_name in section.copy().keys():
                            if entry_name.lower() == normalized_name.lower():
                                del parsed_pipfile[category][entry_name]

                        # Check if this is a new package
                        if normalized_name not in parsed_pipfile[category]:
                            newly_added = True

                        # Add the package
                        parsed_pipfile[category][normalized_name] = entry
                        results.append((newly_added, category, normalized_name))

        # Sort categories if requested
        if self._project.settings.get("sort_pipfile"):
            for category in categories:
                if category in parsed_pipfile:
                    parsed_pipfile[category] = self._sort_category(
                        parsed_pipfile[category]
                    )

        # Write Pipfile once at the end
        self.write_toml(parsed_pipfile)
        return results

    # ---- casing -----------------------------------------------------------

    def recase(self) -> None:
        """Walk packages/dev-packages and fix any incorrect casing."""
        if self.ensure_proper_casing():
            self.write_toml(self.parsed)

    def ensure_proper_casing(self) -> bool:
        """Apply proper-casing across ``packages`` and ``dev-packages``."""
        pfile = self.parsed
        casing_changed = self.proper_case_section(pfile.get("packages", {}))
        casing_changed |= self.proper_case_section(pfile.get("dev-packages", {}))
        return casing_changed

    def proper_case_section(self, section) -> bool:
        """Verify proper casing is retrieved, when available, for each
        dependency in the section.
        """
        changed_values = False
        unknown_names = [k for k in section if k not in set(self.proper_names)]
        # Replace each package with proper casing.
        for dep in unknown_names:
            try:
                # Get new casing for package name.
                new_casing = proper_case(dep)
            except OSError:
                # Unable to normalize package name.
                continue

            if new_casing != dep:
                changed_values = True
                self.register_proper_name(new_casing)
                # Replace old value with new value.
                old_value = section[dep]
                section[new_casing] = old_value
                del section[dep]
        return changed_values

    # ---- hash -------------------------------------------------------------

    def calculate_hash(self) -> str:
        """Compute a SHA-256 hash of the Pipfile that is stable regardless
        of package-name casing or separator style (PEP 503 / #4699).

        ``Sphinx`` and ``sphinx``, ``my_pkg`` and ``my-pkg``, etc. all
        hash to the same value so that minor edits to a Pipfile that
        don't change the resolved environment don't trigger
        unnecessary re-locks.

        The algorithm mirrors plette's ``Pipfile.get_hash()`` exactly,
        except every package-name key in ``[packages]``,
        ``[dev-packages]`` and any custom categories is replaced by its
        PEP 503 canonical form before serialisation.
        """
        import hashlib
        import json

        from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name

        _PIPFILE_SECTIONS = frozenset(
            (
                "source",
                "packages",
                "dev-packages",
                "requires",
                "scripts",
                "pipfile",
                "pipenv",
            )
        )

        def _normalize_section(section):
            """Return a new dict with all keys canonicalized (PEP 503)."""
            return {canonicalize_name(k): v for k, v in section.items()}

        with open(self.location) as pf:
            p = plette.Pipfile.load(pf)

        raw = p._data
        data = {
            "_meta": {
                "sources": raw.get("source", {}),
                "requires": raw.get("requires", {}),
            },
            "default": _normalize_section(raw.get("packages", {})),
            "develop": _normalize_section(raw.get("dev-packages", {})),
        }
        for category, values in raw.items():
            if category in _PIPFILE_SECTIONS or category in (
                "default",
                "develop",
                "pipenv",
            ):
                continue
            data[category] = _normalize_section(values)

        content = json.dumps(data, sort_keys=True, separators=(",", ":"))
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()
