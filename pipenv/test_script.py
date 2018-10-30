# -*- coding=utf-8 -*-

import os
import sys


def _patch_path():
    import site
    pipenv_libdir = os.path.dirname(os.path.abspath(__file__))
    pipenv_site_dir = os.path.dirname(pipenv_libdir)
    site.addsitedir(pipenv_site_dir)
    for _dir in ("vendor", "patched"):
        sys.path.insert(0, os.path.join(pipenv_libdir, _dir))


def test_install():
    from pipenv.vendor.vistir.contextmanagers import cd
    from pipenv.vendor.click.testing import CliRunner
    runner = CliRunner()
    with cd("/tmp/test"):
        from pipenv.core import do_lock
        locked = do_lock(system=False, clear=False, pre=False, keep_outdated=False,
                            write=True, pypi_mirror=None)
        # result = runner.invoke(cli, ["lock", "--verbose"])
        # print(result.output)
        # print(result.exit_code)
        print(locked)


if __name__ == "__main__":
    _patch_path()
    test_install()
