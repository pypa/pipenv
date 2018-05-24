"""Build Environment used for isolation during sdist building
"""

import os
from distutils.sysconfig import get_python_lib
from sysconfig import get_paths

from pipenv.patched.notpip._internal.utils.temp_dir import TempDirectory


class BuildEnvironment(object):
    """Creates and manages an isolated environment to install build deps
    """

    def __init__(self, no_clean):
        self._temp_dir = TempDirectory(kind="build-env")
        self._no_clean = no_clean

    @property
    def path(self):
        return self._temp_dir.path

    def __enter__(self):
        self._temp_dir.create()

        self.save_path = os.environ.get('PATH', None)
        self.save_pythonpath = os.environ.get('PYTHONPATH', None)
        self.save_nousersite = os.environ.get('PYTHONNOUSERSITE', None)

        install_scheme = 'nt' if (os.name == 'nt') else 'posix_prefix'
        install_dirs = get_paths(install_scheme, vars={
            'base': self.path,
            'platbase': self.path,
        })

        scripts = install_dirs['scripts']
        if self.save_path:
            os.environ['PATH'] = scripts + os.pathsep + self.save_path
        else:
            os.environ['PATH'] = scripts + os.pathsep + os.defpath

        # Note: prefer distutils' sysconfig to get the
        # library paths so PyPy is correctly supported.
        purelib = get_python_lib(plat_specific=0, prefix=self.path)
        platlib = get_python_lib(plat_specific=1, prefix=self.path)
        if purelib == platlib:
            lib_dirs = purelib
        else:
            lib_dirs = purelib + os.pathsep + platlib
        if self.save_pythonpath:
            os.environ['PYTHONPATH'] = lib_dirs + os.pathsep + \
                self.save_pythonpath
        else:
            os.environ['PYTHONPATH'] = lib_dirs

        os.environ['PYTHONNOUSERSITE'] = '1'

        return self.path

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self._no_clean:
            self._temp_dir.cleanup()

        def restore_var(varname, old_value):
            if old_value is None:
                os.environ.pop(varname, None)
            else:
                os.environ[varname] = old_value

        restore_var('PATH', self.save_path)
        restore_var('PYTHONPATH', self.save_pythonpath)
        restore_var('PYTHONNOUSERSITE', self.save_nousersite)

    def cleanup(self):
        self._temp_dir.cleanup()


class NoOpBuildEnvironment(BuildEnvironment):
    """A no-op drop-in replacement for BuildEnvironment
    """

    def __init__(self, no_clean):
        pass

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def cleanup(self):
        pass
