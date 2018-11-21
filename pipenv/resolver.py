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


def clean_outdated(results, resolver, project, dev=False):
    from .vendor.requirementslib.models.requirements import Requirement
    if not project.lockfile_exists:
        return results
    lockfile = project.lockfile_content
    section = "develop" if dev else "default"
    pipfile_section = "dev-packages" if dev else "packages"
    overlapping_results = [r["name"] for r in results if r["name"] in lockfile[section]]
    new_results = []
    constraint_names = [r.name for r in constraints]
    for result in results:
        if result["name"] not in overlapping_results:
            new_results.append(result)
            continue

        name = result["name"]
        entry_dict = result.copy()
        entry_dict["version"] = "=={0}".format(entry_dict["version"])
        del entry_dict["name"]
        entry = Requirement.from_pipfile(name, entry_dict)
        lockfile_entry = Requirement.from_pipfile(name, lockfile[section][name])
        # TODO: Should this be the case for all locking?
        if lockfile_entry.editable and not entry.editable:
            continue
        # don't introduce new markers since that is more restrictive
        if entry.markers and not lockfile_entry.markers:
            del entry_dict["markers"]
        if entry.specifiers != lockfile_entry.specifiers:
            constraint = next(iter(
                c for c in resolver.parsed_constraints if c.name == entry.name
            ), None)
            if constraint:
                try:
                    constraint.check_if_exists(False)
                except Exception:
                    from .exceptions import DependencyConflict
                    msg = "Cannot resolve conflicting version {0}{1}".format(
                        entry.name, entry.specifiers
                    )
                    msg = "{0} while {1}{2} is locked.".format(
                        lockfile_entry.name, lockfile_entry.specifiers
                    )
                    raise DependencyConflict(msg)
                else:
                    entry_dict["version"] = constraint.satisfied_by.version
        if entry.extras != entry.extras:
            entry.req.extras.extend(lockfile_entry.req.extras)
            entry_dict["extras"] = entry.extras
        entry_hashes = set(entry.hashes)
        locked_hashes = set(lockfile_entry.hashes)
        if entry_hashes != locked_hashes:
            entry_dict["hashes"] = list(entry_hashes | locked_hashes)
        entry_dict["name"] = name
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
