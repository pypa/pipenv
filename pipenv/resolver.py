import os
import sys
import json
import logging

os.environ['PIP_PYTHON_PATH'] = sys.executable

for _dir in ('vendor', 'patched', '..'):
    dirpath = os.path.sep.join([os.path.dirname(__file__), _dir])
    sys.path.insert(0, dirpath)


def which(*args, **kwargs):
    return sys.executable

def main():
    is_verbose = '--verbose' in ' '.join(sys.argv)
    do_pre = '--pre' in ' '.join(sys.argv)
    do_clear = '--clear' in ' '.join(sys.argv)
    is_debug = '--debug' in ' '.join(sys.argv)

    new_sys_argv = []
    for v in sys.argv:
        if v.startswith('--'):
            continue
        else:
            new_sys_argv.append(v)

    sys.argv = new_sys_argv

    import pipenv.core

    if is_verbose:
        logging.getLogger('pip').setLevel(logging.INFO)
    if is_debug:
        # Shit's getting real at this point.
        logging.getLogger('pip').setLevel(logging.DEBUG)

    if 'PIPENV_PACKAGES' in os.environ:
        packages = os.environ['PIPENV_PACKAGES'].strip().split('\n')
    else:
        packages = sys.argv[1:]

        for i, package in enumerate(packages):
            if package.startswith('--'):
                del packages[i]

    project = pipenv.core.project

    def resolve(packages, pre, sources, verbose, clear):
        import pipenv.utils
        return pipenv.utils.resolve_deps(packages, which, project=project, pre=pre, sources=sources, clear=clear, verbose=verbose)

    results = resolve(packages, pre=do_pre, sources=project.sources, verbose=is_verbose, clear=do_clear)


    print('RESULTS:')

    if results:
        print(json.dumps(results))
    else:
        print(json.dumps([]))


if __name__ == '__main__':
    main()
