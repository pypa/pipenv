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


def _main(pre, clear, verbose, system, requirements_dir, packages):
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
    results = resolve(
        packages,
        pre=pre,
        project=project,
        sources=sources,
        clear=clear,
        system=system,
        requirements_dir=requirements_dir,
    )
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
          parsed.requirements_dir, parsed.packages)


if __name__ == "__main__":
    _patch_path()
    from pipenv.vendor import colorama
    colorama.init()
    main()
