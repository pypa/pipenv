import os
import sys
import json
import logging

os.environ['PIP_PYTHON_PATH'] = sys.executable


def _patch_path():
    pipenv_libdir = os.path.dirname(os.path.abspath(__file__))
    for _dir in ('vendor', 'patched'):
        sys.path.insert(0, os.path.join(pipenv_libdir, _dir))
    site_packages_dir = os.path.dirname(pipenv_libdir)
    if site_packages_dir not in sys.path:
        sys.path.append(site_packages_dir)


def which(*args, **kwargs):
    return sys.executable


def main():
    is_verbose = '--verbose' in ' '.join(sys.argv)
    do_pre = '--pre' in ' '.join(sys.argv)
    do_clear = '--clear' in ' '.join(sys.argv)
    is_debug = '--debug' in ' '.join(sys.argv)
    system = '--system' in ' '.join(sys.argv)
    new_sys_argv = []
    for v in sys.argv:
        if v.startswith('--'):
            continue

        else:
            new_sys_argv.append(v)
    sys.argv = new_sys_argv

    import pipenv.core

    if is_verbose:
        logging.getLogger('pip9').setLevel(logging.INFO)
        logging.getLogger('notpip').setLevel(logging.INFO)
    if is_debug:
        # Shit's getting real at this point.
        logging.getLogger('pip9').setLevel(logging.DEBUG)
        logging.getLogger('notpip').setLevel(logging.DEBUG)
    if 'PIPENV_PACKAGES' in os.environ:
        packages = os.environ['PIPENV_PACKAGES'].strip().split('\n')
    else:
        packages = sys.argv[1:]
        for i, package in enumerate(packages):
            if package.startswith('--'):
                del packages[i]
    project = pipenv.core.project

    def resolve(packages, pre, sources, verbose, clear, system):
        import pipenv.utils
        return pipenv.utils.resolve_deps(
            packages,
            which,
            project=project,
            pre=pre,
            sources=sources,
            clear=clear,
            verbose=verbose,
            allow_global=system,
        )

    results = resolve(
        packages,
        pre=do_pre,
        sources=project.sources,
        verbose=is_verbose,
        clear=do_clear,
        system=system,
    )
    print('RESULTS:')
    if results:
        print(json.dumps(results))
    else:
        print(json.dumps([]))


if __name__ == '__main__':
    _patch_path()
    main()
