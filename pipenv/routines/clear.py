import shutil

from pipenv import environments
from pipenv.vendor import click, vistir


def do_clear(project):
    from pipenv.patched.pip._internal import locations

    click.secho("Clearing caches...", bold=True)
    try:
        shutil.rmtree(
            project.s.PIPENV_CACHE_DIR, onerror=vistir.path.handle_remove_readonly
        )
        # Other processes may be writing into this directory simultaneously.
        shutil.rmtree(
            locations.USER_CACHE_DIR,
            ignore_errors=environments.PIPENV_IS_CI,
            onerror=vistir.path.handle_remove_readonly,
        )
    except OSError as e:
        # Ignore FileNotFoundError. This is needed for Python 2.7.
        import errno

        if e.errno == errno.ENOENT:
            pass
        raise
