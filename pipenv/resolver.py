import json
import logging
import os
import sys


os.environ["PIP_PYTHON_PATH"] = str(sys.executable)


def find_site_path(pkg, site_dir=None):
    import pkg_resources
    if site_dir is not None:
        site_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    working_set = pkg_resources.WorkingSet([site_dir] + sys.path[:])
    for dist in working_set:
        root = dist.location
        base_name = dist.project_name if dist.project_name else dist.key
        name = None
        if "top_level.txt" in dist.metadata_listdir(""):
            name = next(iter([l.strip() for l in dist.get_metadata_lines("top_level.txt") if l is not None]), None)
        if name is None:
            name = pkg_resources.safe_name(base_name).replace("-", "_")
        if not any(pkg == _ for _ in [base_name, name]):
            continue
        path_options = [name, "{0}.py".format(name)]
        path_options = [os.path.join(root, p) for p in path_options if p is not None]
        path = next(iter(p for p in path_options if os.path.exists(p)), None)
        if path is not None:
            return (dist, path)
    return (None, None)


def _patch_path(pipenv_site=None):
    import site
    pipenv_libdir = os.path.dirname(os.path.abspath(__file__))
    pipenv_site_dir = os.path.dirname(pipenv_libdir)
    pipenv_dist = None
    if pipenv_site is not None:
        pipenv_dist, pipenv_path = find_site_path("pipenv", site_dir=pipenv_site)
    else:
        pipenv_dist, pipenv_path = find_site_path("pipenv", site_dir=pipenv_site_dir)
    if pipenv_dist is not None:
        pipenv_dist.activate()
    else:
        site.addsitedir(next(iter(
            sitedir for sitedir in (pipenv_site, pipenv_site_dir)
            if sitedir is not None
        ), None))
    if pipenv_path is not None:
        pipenv_libdir = pipenv_path
    for _dir in ("vendor", "patched", pipenv_libdir):
        sys.path.insert(0, os.path.join(pipenv_libdir, _dir))


def get_parser():
    from argparse import ArgumentParser
    parser = ArgumentParser("pipenv-resolver")
    parser.add_argument("--pre", action="store_true", default=False)
    parser.add_argument("--clear", action="store_true", default=False)
    parser.add_argument("--verbose", "-v", action="count", default=False)
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("--system", action="store_true", default=False)
    parser.add_argument("--parse-only", action="store_true", default=False)
    parser.add_argument("--pipenv-site", metavar="pipenv_site_dir", action="store",
                        default=os.environ.get("PIPENV_SITE_DIR"))
    parser.add_argument("--requirements-dir", metavar="requirements_dir", action="store",
                        default=os.environ.get("PIPENV_REQ_DIR"))
    parser.add_argument("--write", metavar="write", action="store",
                        default=os.environ.get("PIPENV_RESOLVER_FILE"))
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
    os.environ["PIPENV_VERBOSITY"] = str(parsed.verbose)
    if "PIPENV_PACKAGES" in os.environ:
        parsed.packages += os.environ.get("PIPENV_PACKAGES", "").strip().split("\n")
    return parsed


def parse_packages(packages, pre, clear, system, requirements_dir=None):
    from pipenv.vendor.requirementslib.models.requirements import Requirement
    from pipenv.vendor.vistir.contextmanagers import cd, temp_path
    from pipenv.utils import parse_indexes
    parsed_packages = []
    for package in packages:
        indexes, trusted_hosts, line = parse_indexes(package)
        line = " ".join(line)
        pf = dict()
        req = Requirement.from_line(line)
        if not req.name:
            with temp_path(), cd(req.req.setup_info.base_dir):
                sys.path.insert(0, req.req.setup_info.base_dir)
                req.req._setup_info.get_info()
                req.update_name_from_path(req.req.setup_info.base_dir)
        print(os.listdir(req.req.setup_info.base_dir))
        try:
            name, entry = req.pipfile_entry
        except Exception:
            continue
        else:
            if name is not None and entry is not None:
                pf[name] = entry
                parsed_packages.append(pf)
    print("RESULTS:")
    if parsed_packages:
        print(json.dumps(parsed_packages))
    else:
        print(json.dumps([]))


def resolve_packages(pre, clear, verbose, system, write, requirements_dir, packages):
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
    results = resolve(packages, pre=pre, project=project, sources=sources, clear=clear,
                      system=system, requirements_dir=requirements_dir)
    if write:
        with open(write, "w") as fh:
            if not results:
                json.dump([], fh)
            else:
                json.dump(results, fh)
    else:
        print("RESULTS:")
        if results:
            print(json.dumps(results))
        else:
            print(json.dumps([]))


def _main(pre, clear, verbose, system, write, requirements_dir, packages, parse_only=False):
    os.environ["PIP_PYTHON_VERSION"] = ".".join([str(s) for s in sys.version_info[:3]])
    os.environ["PIP_PYTHON_PATH"] = str(sys.executable)
    if parse_only:
        parse_packages(
            packages,
            pre=pre,
            clear=clear,
            system=system,
            requirements_dir=requirements_dir,
        )
    else:
        resolve_packages(pre, clear, verbose, system, write, requirements_dir, packages)


def main():
    parser = get_parser()
    parsed, remaining = parser.parse_known_args()
    _patch_path(pipenv_site=parsed.pipenv_site)
    import warnings
    from pipenv.vendor.vistir.compat import ResourceWarning
    from pipenv.vendor.vistir.misc import get_wrapped_stream
    warnings.simplefilter("ignore", category=ResourceWarning)
    import six
    if six.PY3:
        stdout = sys.stdout.buffer
        stderr = sys.stderr.buffer
    else:
        stdout = sys.stdout
        stderr = sys.stderr
    sys.stderr = get_wrapped_stream(stderr)
    sys.stdout = get_wrapped_stream(stdout)
    from pipenv.vendor import colorama
    if os.name == "nt" and (
        all(getattr(stream, method, None) for stream in [sys.stdout, sys.stderr] for method in ["write", "isatty"]) and
        all(stream.isatty() for stream in [sys.stdout, sys.stderr])
    ):
        stderr_wrapper = colorama.AnsiToWin32(sys.stderr, autoreset=False, convert=None, strip=None)
        stdout_wrapper = colorama.AnsiToWin32(sys.stdout, autoreset=False, convert=None, strip=None)
        sys.stderr = stderr_wrapper.stream
        sys.stdout = stdout_wrapper.stream
        colorama.init(wrap=False)
    elif os.name != "nt":
        colorama.init()
    os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = str("1")
    os.environ["PYTHONIOENCODING"] = str("utf-8")
    os.environ["PYTHONUNBUFFERED"] = str("1")
    parsed = handle_parsed_args(parsed)
    _main(parsed.pre, parsed.clear, parsed.verbose, parsed.system, parsed.write,
          parsed.requirements_dir, parsed.packages, parse_only=parsed.parse_only)


if __name__ == "__main__":
    main()
