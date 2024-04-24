from __future__ import unicode_literals

from pipenv.patched.pip._vendor.packaging.version import parse as parse_version
from pipenv.patched.pip._vendor.packaging.specifiers import SpecifierSet
import pipenv.patched.pip._vendor.requests as requests

from datetime import datetime
from pipenv.vendor.dparse import parse, parser, updater, filetypes
from pipenv.vendor.dparse.dependencies import Dependency
from pipenv.vendor.dparse.parser import setuptools_parse_requirements_backport as parse_requirements


class RequirementFile(object):
    def __init__(self, path, content, sha=None):
        self.path = path
        self.content = content
        self.sha = sha
        self._requirements = None
        self._other_files = None
        self._is_valid = None
        self.is_pipfile = False
        self.is_pipfile_lock = False
        self.is_setup_cfg = False

    def __str__(self):
        return "RequirementFile(path='{path}', sha='{sha}', content='{content}')".format(
            path=self.path,
            content=self.content[:30] + "[truncated]" if len(self.content) > 30 else self.content,
            sha=self.sha
        )

    @property
    def is_valid(self):
        if self._is_valid is None:
            self._parse()
        return self._is_valid

    @property
    def requirements(self):
        if not self._requirements:
            self._parse()
        return self._requirements

    @property
    def other_files(self):
        if not self._other_files:
            self._parse()
        return self._other_files

    @staticmethod
    def parse_index_server(line):
        return parser.Parser.parse_index_server(line)

    def _hash_parser(self, line):
        return parser.Parser.parse_hashes(line)

    def _parse_requirements_txt(self):
        self.parse_dependencies(filetypes.requirements_txt)

    def _parse_conda_yml(self):
        self.parse_dependencies(filetypes.conda_yml)

    def _parse_tox_ini(self):
        self.parse_dependencies(filetypes.tox_ini)

    def _parse_pipfile(self):
        self.parse_dependencies(filetypes.pipfile)
        self.is_pipfile = True

    def _parse_pipfile_lock(self):
        self.parse_dependencies(filetypes.pipfile_lock)
        self.is_pipfile_lock = True

    def _parse_setup_cfg(self):
        self.parse_dependencies(filetypes.setup_cfg)
        self.is_setup_cfg = True

    def _parse(self):
        self._requirements, self._other_files = [], []
        if self.path.endswith('.yml') or self.path.endswith(".yaml"):
            self._parse_conda_yml()
        elif self.path.endswith('.ini'):
            self._parse_tox_ini()
        elif self.path.endswith("Pipfile"):
            self._parse_pipfile()
        elif self.path.endswith("Pipfile.lock"):
            self._parse_pipfile_lock()
        elif self.path.endswith('setup.cfg'):
            self._parse_setup_cfg()
        else:
            self._parse_requirements_txt()
        self._is_valid = len(self._requirements) > 0 or len(self._other_files) > 0

    def parse_dependencies(self, file_type):
        result = parse(
            self.content,
            path=self.path,
            sha=self.sha,
            file_type=file_type,
            marker=(
                ("pyup: ignore file", "pyup:ignore file"),  # file marker
                ("pyup: ignore", "pyup:ignore"),  # line marker
            )
        )
        for dep in result.dependencies:
            req = Requirement(
                name=dep.name,
                specs=dep.specs,
                line=dep.line,
                lineno=dep.line_numbers[0] if dep.line_numbers else 0,
                extras=dep.extras,
                file_type=file_type,
            )
            req.index_server = dep.index_server
            if self.is_pipfile:
                req.pipfile = self.path
            req.hashes = dep.hashes
            self._requirements.append(req)
        self._other_files = result.resolved_files

    def iter_lines(self, lineno=0):
        for line in self.content.splitlines()[lineno:]:
            yield line

    @classmethod
    def resolve_file(cls, file_path, line):
        return parser.Parser.resolve_file(file_path, line)


class Requirement(object):
    def __init__(self, name, specs, line, lineno, extras, file_type):
        self.name = name
        self.key = name.lower()
        self.specs = specs
        self.line = line
        self.lineno = lineno
        self.index_server = None
        self.extras = extras
        self.hashes = []
        self.file_type = file_type
        self.pipfile = None

        self.hashCmp = (
            self.key,
            self.specs,
            frozenset(self.extras),
        )

        self._is_insecure = None
        self._changelog = None

        if len(self.specs._specs) == 1 and next(iter(self.specs._specs))._spec[0] == "~=":
            # convert compatible releases to something more easily consumed,
            # e.g. '~=1.2.3' is equivalent to '>=1.2.3,<1.3.0', while '~=1.2'
            # is equivalent to '>=1.2,<2.0'
            min_version = next(iter(self.specs._specs))._spec[1]
            max_version = list(parse_version(min_version).release)
            max_version[-1] = 0
            max_version[-2] = max_version[-2] + 1
            max_version = '.'.join(str(x) for x in max_version)

            self.specs = SpecifierSet('>=%s,<%s' % (min_version, max_version))

    def __eq__(self, other):
        return (
            isinstance(other, Requirement) and
            self.hashCmp == other.hashCmp
        )

    def __ne__(self, other):
        return not self == other

    def __str__(self):
        return "Requirement.parse({line}, {lineno})".format(line=self.line, lineno=self.lineno)

    def __repr__(self):
        return self.__str__()

    @property
    def is_pinned(self):
        if len(self.specs._specs) == 1 and next(iter(self.specs._specs))._spec[0] == "==":
            return True
        return False

    @property
    def is_open_ranged(self):
        if len(self.specs._specs) == 1 and next(iter(self.specs._specs))._spec[0] == ">=":
            return True
        return False

    @property
    def is_ranged(self):
        return len(self.specs._specs) >= 1 and not self.is_pinned

    @property
    def is_loose(self):
        return len(self.specs._specs) == 0

    @staticmethod
    def convert_semver(version):
        semver = {'major': 0, "minor": 0, "patch": 0}
        version = version.split(".")
        # don't be overly clever here. repitition makes it more readable and works exactly how
        # it is supposed to
        try:
            semver['major'] = int(version[0])
            semver['minor'] = int(version[1])
            semver['patch'] = int(version[2])
        except (IndexError, ValueError):
            pass
        return semver

    @property
    def can_update_semver(self):
        # return early if there's no update filter set
        if "pyup: update" not in self.line:
            return True
        update = self.line.split("pyup: update")[1].strip().split("#")[0]
        current_version = Requirement.convert_semver(next(iter(self.specs._specs))._spec[1])
        next_version = Requirement.convert_semver(self.latest_version)
        if update == "major":
            if current_version['major'] < next_version['major']:
                return True
        elif update == 'minor':
            if current_version['major'] < next_version['major'] \
                    or current_version['minor'] < next_version['minor']:
                return True
        return False

    @property
    def filter(self):
        rqfilter = False
        if "rq.filter:" in self.line:
            rqfilter = self.line.split("rq.filter:")[1].strip().split("#")[0]
        elif "pyup:" in self.line:
            if "pyup: update" not in self.line:
                rqfilter = self.line.split("pyup:")[1].strip().split("#")[0]
                # unset the filter once the date set in 'until' is reached
                if "until" in rqfilter:
                    rqfilter, until = [l.strip() for l in rqfilter.split("until")]
                    try:
                        until = datetime.strptime(until, "%Y-%m-%d")
                        if until < datetime.now():
                            rqfilter = False
                    except ValueError:
                        # wrong date formatting
                        pass
        if rqfilter:
            try:
                rqfilter, = parse_requirements("filter " + rqfilter)
                if len(rqfilter.specifier._specs) > 0:
                    return rqfilter.specifier
            except ValueError:
                pass
        return False

    @property
    def version(self):
        if self.is_pinned:
            return next(iter(self.specs._specs))._spec[1]

        specs = self.specs
        if self.filter:
            specs = SpecifierSet(
                ",".join(["".join(s._spec) for s in list(specs._specs) + list(self.filter._specs)])
            )
        return self.get_latest_version_within_specs(
            specs,
            versions=self.package.versions,
            prereleases=self.prereleases
        )

    def get_hashes(self, version):
        r = requests.get('https://pypi.org/pypi/{name}/{version}/json'.format(
            name=self.key,
            version=version
        ))
        hashes = []
        data = r.json()

        for item in data.get("urls", {}):
            sha256 = item.get("digests", {}).get("sha256", False)
            if sha256:
                hashes.append({"hash": sha256, "method": "sha256"})
        return hashes

    def update_version(self, content, version, update_hashes=True):
        if self.file_type == filetypes.tox_ini:
            updater_class = updater.ToxINIUpdater
        elif self.file_type == filetypes.conda_yml:
            updater_class = updater.CondaYMLUpdater
        elif self.file_type == filetypes.requirements_txt:
            updater_class = updater.RequirementsTXTUpdater
        elif self.file_type == filetypes.pipfile:
            updater_class = updater.PipfileUpdater
        elif self.file_type == filetypes.pipfile_lock:
            updater_class = updater.PipfileLockUpdater
        elif self.file_type == filetypes.setup_cfg:
            updater_class = updater.SetupCFGUpdater
        else:
            raise NotImplementedError

        dep = Dependency(
            name=self.name,
            specs=self.specs,
            line=self.line,
            line_numbers=[self.lineno, ] if self.lineno != 0 else None,
            dependency_type=self.file_type,
            hashes=self.hashes,
            extras=self.extras
        )
        hashes = []
        if self.hashes and update_hashes:
            hashes = self.get_hashes(version)

        return updater_class.update(
            content=content,
            dependency=dep,
            version=version,
            hashes=hashes,
            spec="=="
        )

    @classmethod
    def parse(cls, s, lineno, file_type=filetypes.requirements_txt):
        # setuptools requires a space before the comment. If this isn't the case, add it.
        if "\t#" in s:
            parsed, = parse_requirements(s.replace("\t#", "\t #"))
        else:
            parsed, = parse_requirements(s)

        return cls(
            name=parsed.name,
            specs=parsed.specifier,
            line=s,
            lineno=lineno,
            extras=parsed.extras,
            file_type=file_type
        )
