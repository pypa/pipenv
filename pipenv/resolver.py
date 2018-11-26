import os
import sys
import json
import logging

os.environ["PIP_PYTHON_PATH"] = str(sys.executable)


def _patch_path():
    import site
    pipenv_libdir = os.path.dirname(os.path.abspath(__file__))
    pipenv_site_dir = os.path.dirname(pipenv_libdir)
    site.addsitedir(pipenv_site_dir)
    for _dir in ("vendor", "patched"):
        sys.path.insert(0, os.path.join(pipenv_libdir, _dir))


def get_parser():
    from argparse import ArgumentParser
    parser = ArgumentParser("pipenv-resolver")
    parser.add_argument("--pre", action="store_true", default=False)
    parser.add_argument("--clear", action="store_true", default=False)
    parser.add_argument("--verbose", "-v", action="count", default=False)
    parser.add_argument("--dev", action="store_true", default=False)
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("--system", action="store_true", default=False)
    parser.add_argument("--requirements-dir", metavar="requirements_dir", action="store",
                            default=os.environ.get("PIPENV_REQ_DIR"))
    parser.add_argument("packages", nargs="*")
    return parser


def which(*args, **kwargs):
    return sys.executable


def handle_parsed_args(parsed):
    if parsed.debug:
        parsed.verbose = max(parsed.verbose, 2)
    if parsed.verbose > 1:
        logging.getLogger("notpip").setLevel(logging.DEBUG)
    elif parsed.verbose > 0:
        logging.getLogger("notpip").setLevel(logging.INFO)
    if "PIPENV_PACKAGES" in os.environ:
        parsed.packages += os.environ.get("PIPENV_PACKAGES", "").strip().split("\n")
    return parsed


class Entry(object):
    """A resolved entry from a resolver run"""

    def __init__(self, name, entry_dict, project, resolver, reverse_deps=None, dev=False):
        super(Entry, self).__init__()
        self.name = name
        if isinstance(entry_dict, dict):
            self.entry_dict = self.clean_initial_dict(entry_dict)
        else:
            self.entry_dict = entry_dict
        self.project = project
        section = "develop" if dev else "default"
        pipfile_section = "dev-packages" if dev else "packages"
        self.dev = dev
        self.pipfile = project.parsed_pipfile.get(pipfile_section, {})
        self.lockfile = project.lockfile_content.get(section, {})
        self.pipfile_dict = self.pipfile.get(self.pipfile_name, {})
        self.lockfile_dict = self.lockfile.get(name, entry_dict)
        self.resolver = resolver
        self.reverse_deps = reverse_deps
        self._entry = None
        self._lockfile_entry = None
        self._pipfile_entry = None
        self._parent_deps = []
        self._flattened_parents = []
        self._requires = None
        self._deptree = None
        self._parents_in_pipfile = []

    @staticmethod
    def make_requirement(name=None, entry=None, from_ireq=False):
        from pipenv.vendor.requirementslib.models.requirements import Requirement
        if from_ireq:
            return Requirement.from_ireq(entry)
        return Requirement.from_pipfile(name, entry)

    @classmethod
    def clean_initial_dict(cls, entry_dict):
        if not entry_dict.get("version", "").startswith("=="):
            entry_dict["version"] = cls.clean_specifier(entry_dict.get("version", ""))
        if "name" in entry_dict:
            del entry_dict["name"]
        return entry_dict

    def get_cleaned_dict(self):
        if self.is_updated:
            self.validate_constraint()
        if self.entry.extras != self.lockfile_entry.extras:
            self._entry.req.extras.extend(self.lockfile_entry.req.extras)
            self.entry_dict["extras"] = self.entry.extras
        entry_hashes = set(self.entry.hashes)
        locked_hashes = set(self.lockfile_entry.hashes)
        if entry_hashes != locked_hashes and not self.is_updated:
            self.entry_dict["hashes"] = list(entry_hashes | locked_hashes)
        self.entry_dict["name"] = self.name
        self.entry_dict["version"] = self.strip_version(self.entry_dict["version"])
        return self.entry_dict

    @property
    def lockfile_entry(self):
        if self._lockfile_entry is None:
            self._lockfile_entry = self.make_requirement(self.name, self.lockfile_dict)
        return self._lockfile_entry

    @property
    def pipfile_entry(self):
        if self._pipfile_entry is None:
            self._pipfile_entry = self.make_requirement(self.pipfile_name, self.pipfile_dict)
        return self._pipfile_entry

    @property
    def entry(self):
        if self._entry is None:
            self._entry = self.make_requirement(self.name, self.entry_dict)
        return self._entry

    @property
    def normalized_name(self):
        return self.entry.normalized_name

    @property
    def pipfile_name(self):
        return self.project.get_package_name_in_pipfile(self.name, dev=self.dev)

    @property
    def is_in_pipfile(self):
        return True if self.pipfile_name else False

    @property
    def pipfile_packages(self):
        return self.project.pipfile_package_names["dev" if self.dev else "default"]

    def create_parent(self, name, specifier):
        parent = self.create(name, specifier, self.project, self.resolver,
                             self.reverse_deps, self.dev)
        parent._deptree = self.deptree
        return parent

    @property
    def deptree(self):
        if not self._deptree:
            self._deptree = self.project.environment.get_package_requirements()
        return self._deptree

    @classmethod
    def create(cls, name, entry_dict, project, resolver, reverse_deps=None, dev=False):
        return cls(name, entry_dict, project, resolver, reverse_deps, dev)

    @staticmethod
    def clean_specifier(specifier):
        from pipenv.vendor.packaging.specifiers import Specifier
        if not any(specifier.startswith(k) for k in Specifier._operators.keys()):
            specifier = "=={0}".format(specifier)
        elif specifier.startswith("==") and specifier.count("=") > 2:
            specifier = "=={0}".format(specifier.lstrip("="))
        return specifier

    @staticmethod
    def strip_version(specifier):
        from pipenv.vendor.packaging.specifiers import Specifier
        op = next(iter(
            k for k in Specifier._operators.keys() if specifier.startswith(k)
        ), None)
        if op:
            specifier = specifier[len(op):]
        while op:
            op = next(iter(
                k for k in Specifier._operators.keys() if specifier.startswith(k)
            ), None)
            if op:
                specifier = specifier[len(op):]
        return specifier

    @property
    def parent_deps(self):
        if not self._parent_deps:
            self._parent_deps = self.get_parent_deps(unnest=False)
        return self._parent_deps

    @property
    def flattened_parents(self):
        if not self._flattened_parents:
            self._flattened_parents = self.get_parent_deps(unnest=True)
        return self._flattened_parents

    @property
    def parents_in_pipfile(self):
        if not self._parents_in_pipfile:
            self._parents_in_pipfile = [
                p for p in self.flattened_parents
                if p.normalized_name in self.pipfile_packages
            ]
        return self._parents_in_pipfile

    @property
    def is_updated(self):
        return self.entry.specifiers != self.lockfile_entry.specifiers

    @property
    def requirements(self):
        if not self._requires:
            self._requires = next(iter(
                self.project.environment.get_package_requirements(self.name)
            ), None)
        return self._requires

    @property
    def updated_version(self):
        version = self.entry.specifiers
        return self.strip_version(version)

    @property
    def updated_specifier(self):
        return self.entry.specifiers

    def validate_specifiers(self):
        if self.is_in_pipfile:
            return self.pipfile_entry.requirement.specifier.contains(self.updated_version)
        return True

    def get_dependency(self, name):
        return next(iter(
            dep for dep in self.requirements.get("dependencies", [])
            if dep.get("package_name", "") == name
        ), {})

    def get_parent_deps(self, unnest=False):
        parents = []
        for k, v in self.reverse_deps.get(self.normalized_name, {}).get("parents", {}).items():
            specifier = self.clean_specifier(v)
            parent = self.create_parent(k, specifier)
            parents.append(parent)
            if not unnest or parent.pipfile_name is not None:
                continue
            if self.reverse_deps.get(parent.normalized_name, {}).get("parents", {}):
                parents.extend(parent.flattened_parents)
        return parents

    def get_constraint(self):
        constraint = next(iter(
            c for c in self.resolver.parsed_constraints if c.name == self.entry.name
        ), None)
        if constraint:
            return constraint
        return self.get_pipfile_constraint()

    def get_pipfile_constraint(self):
        if self.is_in_pipfile:
            return self.pipfile_entry.as_ireq()
        return self.constraint_from_parent_conflicts()

    def constraint_from_parent_conflicts(self):
        # ensure that we satisfy the parent dependencies of this dep
        from pipenv.vendor.packaging.specifiers import Specifier
        for p in self.parent_deps:
            if parent.is_updated:
                continue
            if not p.requirements:
                continue
            needed = p.requirements.get("dependencies", [])
            entry_ref = p.get_dependency(self.name)
            required = entry_ref.get("required_version", "")
            self.clean_specifier(required)
            parent_requires = self.make_requirement(name, required)
            if not parent_requires.requirement.specifier.contains(self.updated_version):
                from pipenv.exceptions import DependencyConflict
                msg = "Cannot resolve {0} due to conflicting parent dependency: {1}".format(
                    entry.name, parent.name
                )
                raise DependencyConflict(msg)
        return self.entry.as_ireq()

    def validate_constraint(self):
        constraint = self.get_constraint()
        try:
            constraint.check_if_exists(False)
        except Exception:
            from pipenv.exceptions import DependencyConflict
            msg = "Cannot resolve conflicting version {0}{1}".format(
                self.name, self.updated_specifiers
            )
            msg = "{0} while {1}{2} is locked.".format(
                self.old_name, self.old_specifiers
            )
            raise DependencyConflict(msg)
        else:
            if getattr(constraint, "satisfied_by", None):
                # Use the already installed version if we can
                satisfied_by = "{0}".format(self.clean_specifier(
                    str(constraint.satisfied_by.version)
                ))
                if self.updated_specifiers != satisfied_by:
                    self.entry_dict["version"] = satisfied_by
                    self.entry_dict["hashes"] = []
                    self._entry.hashes = set()
                    if self.lockfile_entry.specifiers == satisfied_by:
                        self._entry.hashes = self.lockfile_entry.hashes
            else:
                # check for any parents, since they depend on this and the current
                # installed versions are not compatible with the new version, so
                # we will need to update the top level dependency if possible
                self.check_flattened_parents()
        return True

    def check_flattened_parents(self):
        for parent in self.parents_in_pipfile:
            if not parent.updated_specifier:
                continue
            if not parent.validate_specifiers():
                from pipenv.exceptions import DependencyConflict
                msg = (
                    "Cannot resolve conflicting versions: (Root: {0}) {1}{2} (Pipfile) "
                    "Incompatible with {3}{4} (resolved)\n".format(
                        self.name, parent.pipfile_name,
                        parent.pipfile_entry.requirement.specifiers, parent.name,
                        parent.updated_specifiers
                    )
                )
                raise DependencyConflict(msg)

    def __getattribute__(self, key):
        result = None
        old_version = ["was_", "had_", "old_"]
        new_version = ["is_", "has_", "new_"]
        if any(key.startswith(v) for v in new_version):
            entry = Entry.__getattribute__(self, "entry")
            try:
                keystart = key.index("_") + 1
                try:
                    result = getattr(entry, key[keystart:])
                except AttributeError:
                    result = getattr(entry, key)
            except AttributeError:
                result = super(Entry, self).__getattribute__(key)
            return result
        if any(key.startswith(v) for v in old_version):
            lockfile_entry = Entry.__getattribute__(self, "lockfile_entry")
            try:
                keystart = key.index("_") + 1
                try:
                    result = getattr(lockfile_entry, key[keystart:])
                except AttributeError:
                    result = getattr(lockfile_entry, key)
            except AttributeError:
                result = super(Entry, self).__getattribute__(key)
            return result
        return super(Entry, self).__getattribute__(key)


def clean_outdated(results, resolver, project, dev=False):
    from pipenv.vendor.requirementslib.models.requirements import Requirement
    if not project.lockfile_exists:
        return results
    lockfile = project.lockfile_content
    section = "develop" if dev else "default"
    pipfile_section = "dev-packages" if dev else "packages"
    pipfile = project.parsed_pipfile[pipfile_section]
    reverse_deps = project.environment.reverse_dependencies()
    deptree = project.environment.get_package_requirements()
    overlapping_results = [r for r in results if r["name"] in lockfile[section]]
    new_results = [r for r in results if r["name"] not in lockfile[section]]
    for result in results:
        name = result.get("name")
        entry_dict = result.copy()
        entry = Entry(name, entry_dict, project, resolver, reverse_deps=reverse_deps, dev=dev)
        # The old entry was editable but this one isnt; prefer the old one
        # TODO: Should this be the case for all locking?
        if entry.was_editable and not entry.is_editable:
            continue
        # don't introduce new markers since that is more restrictive
        if entry.has_markers and not entry.had_markers:
            del entry.entry_dict["markers"]
            entry._entry.req.req.marker = None
            entry._entry.markers = ""
        entry_dict = entry.get_cleaned_dict()
        new_results.append(entry_dict)
    return new_results


def _main(pre, clear, verbose, system, requirements_dir, dev, packages):
    os.environ["PIP_PYTHON_VERSION"] = ".".join([str(s) for s in sys.version_info[:3]])
    os.environ["PIP_PYTHON_PATH"] = str(sys.executable)

    from pipenv.utils import create_mirror_source, resolve_deps, replace_pypi_sources

    pypi_mirror_source = (
        create_mirror_source(os.environ["PIPENV_PYPI_MIRROR"])
        if "PIPENV_PYPI_MIRROR" in os.environ
        else None
    )

    def resolve(packages, pre, project, sources, clear, system, requirements_dir=None):
        return resolve_deps(
            packages,
            which,
            project=project,
            pre=pre,
            sources=sources,
            clear=clear,
            allow_global=system,
            req_dir=requirements_dir
        )

    from pipenv.core import project
    sources = (
        replace_pypi_sources(project.pipfile_sources, pypi_mirror_source)
        if pypi_mirror_source
        else project.pipfile_sources
    )
    keep_outdated = os.environ.get("PIPENV_KEEP_OUTDATED", False)
    results, resolver = resolve(
        packages,
        pre=pre,
        project=project,
        sources=sources,
        clear=clear,
        system=system,
        requirements_dir=requirements_dir,
    )
    if keep_outdated:
        results = clean_outdated(results, resolver, project)
    print("RESULTS:")
    if results:
        print(json.dumps(results))
    else:
        print(json.dumps([]))


def main():
    _patch_path()
    import warnings
    from pipenv.vendor.vistir.compat import ResourceWarning
    warnings.simplefilter("ignore", category=ResourceWarning)
    import io
    import six
    if six.PY3:
        import atexit
        stdout_wrapper = io.TextIOWrapper(sys.stdout.buffer, encoding='utf8')
        atexit.register(stdout_wrapper.close)
        stderr_wrapper = io.TextIOWrapper(sys.stderr.buffer, encoding='utf8')
        atexit.register(stderr_wrapper.close)
        sys.stdout = stdout_wrapper
        sys.stderr = stderr_wrapper
    else:
        from pipenv._compat import force_encoding
        force_encoding()
    os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = str("1")
    os.environ["PYTHONIOENCODING"] = str("utf-8")
    parser = get_parser()
    parsed, remaining = parser.parse_known_args()
    # sys.argv = remaining
    parsed = handle_parsed_args(parsed)
    _main(parsed.pre, parsed.clear, parsed.verbose, parsed.system,
          parsed.requirements_dir, parsed.dev, parsed.packages)


if __name__ == "__main__":
    _patch_path()
    from pipenv.vendor import colorama
    colorama.init()
    main()
