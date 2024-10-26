import contextlib
import io
import itertools
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipenv import environments, exceptions
from pipenv.utils import console, err
from pipenv.utils.internet import get_url_name
from pipenv.utils.markers import RequirementError
from pipenv.utils.requirements import import_requirements
from pipenv.utils.requirementslib import is_editable, is_vcs, merge_items
from pipenv.utils.toml import tomlkit_value_to_python
from pipenv.vendor import tomlkit
from pipenv.vendor.plette import pipfiles

DEFAULT_NEWLINES = "\n"


def walk_up(bottom):
    """mimic os.walk, but walk 'up' instead of down the directory tree.
    From: https://gist.github.com/zdavkeos/1098474
    """

    bottom = os.path.realpath(bottom)

    # get files in current dir
    try:
        names = os.listdir(bottom)
    except Exception:
        return

    dirs, nondirs = [], []
    for name in names:
        if os.path.isdir(os.path.join(bottom, name)):
            dirs.append(name)
        else:
            nondirs.append(name)

    yield bottom, dirs, nondirs

    new_path = os.path.realpath(os.path.join(bottom, ".."))

    # see if we are at the top
    if new_path == bottom:
        return

    yield from walk_up(new_path)


def find_pipfile(max_depth=3):
    """Returns the path of a Pipfile in parent directories."""
    i = 0
    for c, _, _ in walk_up(os.getcwd()):
        i += 1

        if i < max_depth and "Pipfile":
            p = os.path.join(c, "Pipfile")
            if os.path.isfile(p):
                return p
    raise RuntimeError("No Pipfile found!")


def ensure_pipfile(
    project, validate=True, skip_requirements=False, system=False, pipfile_categories=None
):
    """Creates a Pipfile for the project, if it doesn't exist."""

    # Assert Pipfile exists.
    python = (
        project._which("python")
        if not (project.s.USING_DEFAULT_PYTHON or system)
        else None
    )
    if project.pipfile_is_empty:
        # Show an error message and exit if system is passed and no pipfile exists
        if system and not project.s.PIPENV_VIRTUALENV:
            raise exceptions.PipenvOptionsError(
                "--system",
                "--system is intended to be used for pre-existing Pipfile "
                "installation, not installation of specific packages. Aborting.",
            )
        # If there's a requirements file, but no Pipfile...
        if project.requirements_exists and not skip_requirements:
            requirements_dir_path = os.path.dirname(project.requirements_location)
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
    if validate and project.virtualenv_exists and not project.s.PIPENV_SKIP_VALIDATION:
        # Ensure that Pipfile is using proper casing.
        p = project.parsed_pipfile
        changed = project.ensure_proper_casing()
        # Write changes out to disk.
        if changed:
            err.print("Fixing package names in Pipfile...", style="bold")
            project.write_toml(p)


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


def preferred_newlines(f):
    if isinstance(f.newlines, str):
        return f.newlines
    return DEFAULT_NEWLINES


@dataclass
class ProjectFile:
    location: str
    line_ending: str
    model: Optional[Any] = field(default_factory=dict)

    @classmethod
    def read(cls, location: str, model_cls, invalid_ok: bool = False) -> "ProjectFile":
        if not os.path.exists(location) and not invalid_ok:
            raise FileNotFoundError(location)
        try:
            with open(location, encoding="utf-8") as f:
                model = model_cls.load(f)
                line_ending = preferred_newlines(f)
        except Exception:
            if not invalid_ok:
                raise
            model = {}
            line_ending = DEFAULT_NEWLINES
        return cls(location=location, line_ending=line_ending, model=model)

    def write(self) -> None:
        kwargs = {"encoding": "utf-8", "newline": self.line_ending}
        with open(self.location, "w", **kwargs) as f:
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
class Pipfile:
    path: Path
    projectfile: ProjectFile
    pipfile: Optional[PipfileLoader] = None
    _pyproject: Optional[tomlkit.TOMLDocument] = field(default_factory=tomlkit.document)
    build_system: Optional[Dict] = field(default_factory=dict)
    _requirements: Optional[List] = field(default_factory=list)
    _dev_requirements: Optional[List] = field(default_factory=list)

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
        return v or Pipfile.load_projectfile(os.curdir, create=False)

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
        check_pipfile = k in self.extended_keys or self.pipfile.__contains__(k)
        if check_pipfile:
            return True
        return False

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
            retval = super(Pipfile).__getattribute__(k)
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
    def load(cls, path: str, create: bool = False) -> "Pipfile":
        """..."""

        projectfile = cls.load_projectfile(path, create=create)
        pipfile = projectfile.model
        creation_args = {
            "projectfile": projectfile,
            "pipfile": pipfile,
            "path": Path(projectfile.location),
        }
        return cls(**creation_args)
