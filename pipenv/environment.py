# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import contextlib
import importlib
import io
import json
import operator
import os
import site
import sys

from sysconfig import get_paths, get_python_version

import itertools
import pkg_resources
import six

import pipenv

from .vendor.cached_property import cached_property
from .vendor.packaging.utils import canonicalize_name
from .vendor import vistir

from .utils import normalize_path, make_posix


if False:
    import pip_shims.shims
    import tomlkit
    from typing import ContextManager, Dict, Generator, List, Optional, Set, Union
    from types import ModuleType
    from .project import TSource, TPipfile, Project
    from .vendor.packaging.version import Version

BASE_WORKING_SET = pkg_resources.WorkingSet(sys.path)
# TODO: Unittests for this class


class Environment(object):
    def __init__(
        self,
        prefix=None,  # type: Optional[str]
        python=None,  # type: Optional[str]
        is_venv=False,  # type: bool
        base_working_set=None,  # type: pkg_resources.WorkingSet
        pipfile=None,  # type: Optional[Union[tomlkit.toml_document.TOMLDocument, TPipfile]]
        sources=None,  # type: Optional[List[TSource]]
        project=None  # type: Optional[Project]
    ):
        super(Environment, self).__init__()
        self._modules = {'pkg_resources': pkg_resources, 'pipenv': pipenv}
        self.base_working_set = base_working_set if base_working_set else BASE_WORKING_SET
        prefix = normalize_path(prefix)
        self._python = None
        if python is not None:
            self._python = vistir.compat.Path(python).absolute().as_posix()
        self.is_venv = is_venv or prefix != normalize_path(sys.prefix)
        if not sources:
            sources = []
        self.project = project
        if project and not sources:
            sources = project.sources
        self.sources = sources
        if project and not pipfile:
            pipfile = project.parsed_pipfile
        self.pipfile = pipfile
        self.extra_dists = []
        prefix = prefix if prefix else sys.prefix
        self.prefix = vistir.compat.Path(prefix)
        self._base_paths = {}
        if self.is_venv:
            self._base_paths = self.get_paths()
        self.sys_paths = get_paths()

    def safe_import(self, name):
        # type: (str) -> ModuleType
        """Helper utility for reimporting previously imported modules while inside the env"""
        module = None
        if name not in self._modules:
            self._modules[name] = importlib.import_module(name)
        module = self._modules[name]
        if not module:
            dist = next(iter(
                dist for dist in self.base_working_set if dist.project_name == name
            ), None)
            if dist:
                dist.activate()
            module = importlib.import_module(name)
        if name in sys.modules:
            try:
                six.moves.reload_module(module)
                six.moves.reload_module(sys.modules[name])
            except TypeError:
                del sys.modules[name]
                sys.modules[name] = self._modules[name]
                return self._modules[name]
        return module

    @classmethod
    def resolve_dist(cls, dist, working_set):
        # type: (pkg_resources.Distribution, pkg_resources.WorkingSet) -> Set[pkg_resources.Distribution]
        """Given a local distribution and a working set, returns all dependencies from the set.

        :param dist: A single distribution to find the dependencies of
        :type dist: :class:`pkg_resources.Distribution`
        :param working_set: A working set to search for all packages
        :type working_set: :class:`pkg_resources.WorkingSet`
        :return: A set of distributions which the package depends on, including the package
        :rtype: set(:class:`pkg_resources.Distribution`)
        """

        deps = set()
        deps.add(dist)
        try:
            reqs = dist.requires()
        # KeyError = limited metadata can be found
        except (KeyError, AttributeError, OSError, IOError):  # The METADATA file can't be found
            return deps
        for req in reqs:
            dist = working_set.find(req)
            deps |= cls.resolve_dist(dist, working_set)
        return deps

    def extend_dists(self, dist):
        # type: (pkg_resources.Distribution) -> None
        extras = self.resolve_dist(dist, self.base_working_set)
        self.extra_dists.append(dist)
        if extras:
            self.extra_dists.extend(extras)

    def add_dist(self, dist_name):
        # type: (str) -> None
        dist = pkg_resources.get_distribution(pkg_resources.Requirement(dist_name))
        self.extend_dists(dist)

    @cached_property
    def python_version(self):
        # type: () -> str
        with self.activated():
            sysconfig = self.safe_import("sysconfig")
            py_version = sysconfig.get_python_version()
            return py_version

    def find_libdir(self):
        # type: () -> Optional[vistir.compat.Path]
        libdir = self.prefix / "lib"
        return next(iter(list(libdir.iterdir())), None)

    @property
    def python_info(self):
        # type: () -> Dict[str, str]
        include_dir = self.prefix / "include"
        if not os.path.exists(include_dir):
            include_dirs = self.get_include_path()
            if include_dirs:
                include_path = include_dirs.get("include", include_dirs.get("platinclude"))
                if not include_path:
                    return {}
                include_dir = vistir.compat.Path(include_path)
        python_path = next(iter(list(include_dir.iterdir())), None)
        if python_path and python_path.name.startswith("python"):
            python_version = python_path.name.replace("python", "")
            py_version_short, abiflags = python_version[:3], python_version[3:]
            return {"py_version_short": py_version_short, "abiflags": abiflags}
        return {}

    def _replace_parent_version(self, path, replace_version):
        # type: (str, str) -> str
        if not os.path.exists(path):
            base, leaf = os.path.split(path)
            base, parent = os.path.split(base)
            leaf = os.path.join(parent, leaf).replace(
                replace_version, self.python_info.get("py_version_short", get_python_version())
            )
            return os.path.join(base, leaf)
        return path

    @cached_property
    def base_paths(self):
        # type: () -> Dict[str, str]
        """
        Returns the context appropriate paths for the environment.

        :return: A dictionary of environment specific paths to be used for installation operations
        :rtype: dict

        .. note:: The implementation of this is borrowed from a combination of pip and
           virtualenv and is likely to change at some point in the future.

        >>> from pipenv.core import project
        >>> from pipenv.environment import Environment
        >>> env = Environment(prefix=project.virtualenv_location, is_venv=True, sources=project.sources)
        >>> import pprint
        >>> pprint.pprint(env.base_paths)
        {'PATH': '/home/hawk/.virtualenvs/pipenv-MfOPs1lW/bin::/bin:/usr/bin',
        'PYTHONPATH': '/home/hawk/.virtualenvs/pipenv-MfOPs1lW/lib/python3.7/site-packages',
        'data': '/home/hawk/.virtualenvs/pipenv-MfOPs1lW',
        'include': '/home/hawk/.pyenv/versions/3.7.1/include/python3.7m',
        'libdir': '/home/hawk/.virtualenvs/pipenv-MfOPs1lW/lib/python3.7/site-packages',
        'platinclude': '/home/hawk/.pyenv/versions/3.7.1/include/python3.7m',
        'platlib': '/home/hawk/.virtualenvs/pipenv-MfOPs1lW/lib/python3.7/site-packages',
        'platstdlib': '/home/hawk/.virtualenvs/pipenv-MfOPs1lW/lib/python3.7',
        'prefix': '/home/hawk/.virtualenvs/pipenv-MfOPs1lW',
        'purelib': '/home/hawk/.virtualenvs/pipenv-MfOPs1lW/lib/python3.7/site-packages',
        'scripts': '/home/hawk/.virtualenvs/pipenv-MfOPs1lW/bin',
        'stdlib': '/home/hawk/.pyenv/versions/3.7.1/lib/python3.7'}
        """

        prefix = make_posix(self.prefix.as_posix())
        paths = {}
        if self._base_paths:
            paths = self._base_paths.copy()
        else:
            try:
                paths = self.get_paths()
            except Exception:
                install_scheme = 'nt' if (os.name == 'nt') else 'posix_prefix'
                paths = get_paths(install_scheme, vars={
                    'base': prefix,
                    'platbase': prefix,
                })
                current_version = get_python_version()
                try:
                    for k in list(paths.keys()):
                        if not os.path.exists(paths[k]):
                            paths[k] = self._replace_parent_version(paths[k], current_version)
                except OSError:
                    # Sometimes virtualenvs are made using virtualenv interpreters and there is no
                    # include directory, which will cause this approach to fail. This failsafe
                    # will make sure we fall back to the shell execution to find the real include path
                    paths = self.get_include_path()
                    paths.update(self.get_lib_paths())
                    paths["scripts"] = self.script_basedir
        if not paths:
            install_scheme = 'nt' if (os.name == 'nt') else 'posix_prefix'
            paths = get_paths(install_scheme, vars={
                'base': prefix,
                'platbase': prefix,
            })
        if not os.path.exists(paths["purelib"]) and not os.path.exists(paths["platlib"]):
            lib_paths = self.get_lib_paths()
            paths.update(lib_paths)
        paths["PATH"] = paths["scripts"] + os.pathsep + os.defpath
        if "prefix" not in paths:
            paths["prefix"] = prefix
        purelib = paths["purelib"] = make_posix(paths["purelib"])
        platlib = paths["platlib"] = make_posix(paths["platlib"])
        if purelib == platlib:
            lib_dirs = purelib
        else:
            lib_dirs = purelib + os.pathsep + platlib
        paths["libdir"] = purelib
        paths['PYTHONPATH'] = os.pathsep.join(["", ".", lib_dirs])
        paths["libdirs"] = lib_dirs
        return paths

    @cached_property
    def script_basedir(self):
        # type: () -> str
        """Path to the environment scripts dir"""
        prefix = make_posix(self.prefix.as_posix())
        install_scheme = 'nt' if (os.name == 'nt') else 'posix_prefix'
        paths = get_paths(install_scheme, vars={
            'base': prefix,
            'platbase': prefix,
        })
        return paths["scripts"]

    @property
    def python(self):
        # type: () -> str
        """Path to the environment python"""
        if self._python is not None:
            return self._python
        if os.name == "nt" and not self.is_venv:
            py = vistir.compat.Path(self.prefix).joinpath("python").absolute().as_posix()
        else:
            py = vistir.compat.Path(self.script_basedir).joinpath("python").absolute().as_posix()
        if not py:
            py = vistir.compat.Path(sys.executable).as_posix()
        self._python = py
        return py

    @cached_property
    def sys_path(self):
        # type: () -> List[str]
        """
        The system path inside the environment

        :return: The :data:`sys.path` from the environment
        :rtype: list
        """

        from .vendor.vistir.compat import JSONDecodeError
        current_executable = vistir.compat.Path(sys.executable).as_posix()
        if not self.python or self.python == current_executable:
            return sys.path
        elif any([sys.prefix == self.prefix, not self.is_venv]):
            return sys.path
        cmd_args = [self.python, "-c", "import json, sys; print(json.dumps(sys.path))"]
        path, _ = vistir.misc.run(cmd_args, return_object=False, nospin=True, block=True, combine_stderr=False, write_to_stdout=False)
        try:
            path = json.loads(path.strip())
        except JSONDecodeError:
            path = sys.path
        return path

    def build_command(self, python_lib=False, python_inc=False, scripts=False, py_version=False):
        # type: (bool, bool, bool, bool) -> str
        """Build the text for running a command in the given environment

        :param python_lib: Whether to include the python lib dir commands, defaults to False
        :type python_lib: bool, optional
        :param python_inc: Whether to include the python include dir commands, defaults to False
        :type python_inc: bool, optional
        :param scripts: Whether to include the scripts directory, defaults to False
        :type scripts: bool, optional
        :param py_version: Whether to include the python version info, defaults to False
        :type py_version: bool, optional
        :return: A string representing the command to run
        """
        pylib_lines = []
        pyinc_lines = []
        py_command = (
            "import sysconfig, distutils.sysconfig, io, json, sys; paths = {{"
            "%s }}; value = u'{{0}}'.format(json.dumps(paths));"
            "fh = io.open('{0}', 'w'); fh.write(value); fh.close()"
        )
        distutils_line = "distutils.sysconfig.get_python_{0}(plat_specific={1})"
        sysconfig_line = "sysconfig.get_path('{0}')"
        if python_lib:
            for key, var, val in (("pure", "lib", "0"), ("plat", "lib", "1")):
                dist_prefix = "{0}lib".format(key)
                # XXX: We need to get 'stdlib' or 'platstdlib'
                sys_prefix = "{0}stdlib".format("" if key == "pure" else key)
                pylib_lines.append("u'%s': u'{{0}}'.format(%s)" % (dist_prefix, distutils_line.format(var, val)))
                pylib_lines.append("u'%s': u'{{0}}'.format(%s)" % (sys_prefix, sysconfig_line.format(sys_prefix)))
        if python_inc:
            for key, var, val in (("include", "inc", "0"), ("platinclude", "inc", "1")):
                pylib_lines.append("u'%s': u'{{0}}'.format(%s)" % (key, distutils_line.format(var, val)))
        lines = pylib_lines + pyinc_lines
        if scripts:
            lines.append("u'scripts': u'{{0}}'.format(%s)" % sysconfig_line.format("scripts"))
        if py_version:
            lines.append("u'py_version_short': u'{{0}}'.format(distutils.sysconfig.get_python_version()),")
        lines_as_str = u",".join(lines)
        py_command = py_command % lines_as_str
        return py_command

    def get_paths(self):
        # type: () -> Optional[Dict[str, str]]
        """
        Get the paths for the environment by running a subcommand

        :return: The python paths for the environment
        :rtype: Dict[str, str]
        """
        tmpfile = vistir.path.create_tracked_tempfile(suffix=".json")
        tmpfile.close()
        tmpfile_path = make_posix(tmpfile.name)
        py_command = self.build_command(python_lib=True, python_inc=True, scripts=True, py_version=True)
        command = [self.python, "-c", py_command.format(tmpfile_path)]
        c = vistir.misc.run(
            command, return_object=True, block=True, nospin=True, write_to_stdout=False
        )
        if c.returncode == 0:
            paths = {}
            with io.open(tmpfile_path, "r", encoding="utf-8") as fh:
                paths = json.load(fh)
            if "purelib" in paths:
                paths["libdir"] = paths["purelib"] = make_posix(paths["purelib"])
            for key in ("platlib", "scripts", "platstdlib", "stdlib", "include", "platinclude"):
                if key in paths:
                    paths[key] = make_posix(paths[key])
            return paths
        else:
            vistir.misc.echo("Failed to load paths: {0}".format(c.err), fg="yellow")
            vistir.misc.echo("Output: {0}".format(c.out), fg="yellow")
        return None

    def get_lib_paths(self):
        # type: () -> Dict[str, str]
        """Get the include path for the environment

        :return: The python include path for the environment
        :rtype: Dict[str, str]
        """
        tmpfile = vistir.path.create_tracked_tempfile(suffix=".json")
        tmpfile.close()
        tmpfile_path = make_posix(tmpfile.name)
        py_command = self.build_command(python_lib=True)
        command = [self.python, "-c", py_command.format(tmpfile_path)]
        c = vistir.misc.run(
            command, return_object=True, block=True, nospin=True, write_to_stdout=False
        )
        paths = None
        if c.returncode == 0:
            paths = {}
            with io.open(tmpfile_path, "r", encoding="utf-8") as fh:
                paths = json.load(fh)
            if "purelib" in paths:
                paths["libdir"] = paths["purelib"] = make_posix(paths["purelib"])
            for key in ("platlib", "platstdlib", "stdlib"):
                if key in paths:
                    paths[key] = make_posix(paths[key])
            return paths
        else:
            vistir.misc.echo("Failed to load paths: {0}".format(c.err), fg="yellow")
            vistir.misc.echo("Output: {0}".format(c.out), fg="yellow")
        if not paths:
            if not self.prefix.joinpath("lib").exists():
                return {}
            stdlib_path = next(iter([
                p for p in self.prefix.joinpath("lib").iterdir()
                if p.name.startswith("python")
            ]), None)
            lib_path = None
            if stdlib_path:
                lib_path = next(iter([
                    p.as_posix() for p in stdlib_path.iterdir()
                    if p.name == "site-packages"
                ]))
                paths = {"stdlib": stdlib_path.as_posix()}
                if lib_path:
                    paths["purelib"] = lib_path
                return paths
        return {}

    def get_include_path(self):
        # type: () -> Optional[Dict[str, str]]
        """Get the include path for the environment

        :return: The python include path for the environment
        :rtype: Dict[str, str]
        """
        tmpfile = vistir.path.create_tracked_tempfile(suffix=".json")
        tmpfile.close()
        tmpfile_path = make_posix(tmpfile.name)
        py_command = (
            "import distutils.sysconfig, io, json, sys; paths = {{u'include': "
            "u'{{0}}'.format(distutils.sysconfig.get_python_inc(plat_specific=0)), "
            "u'platinclude': u'{{0}}'.format(distutils.sysconfig.get_python_inc("
            "plat_specific=1)) }}; value = u'{{0}}'.format(json.dumps(paths));"
            "fh = io.open('{0}', 'w'); fh.write(value); fh.close()"
        )
        command = [self.python, "-c", py_command.format(tmpfile_path)]
        c = vistir.misc.run(
            command, return_object=True, block=True, nospin=True, write_to_stdout=False
        )
        if c.returncode == 0:
            paths = []
            with io.open(tmpfile_path, "r", encoding="utf-8") as fh:
                paths = json.load(fh)
            for key in ("include", "platinclude"):
                if key in paths:
                    paths[key] = make_posix(paths[key])
            return paths
        else:
            vistir.misc.echo("Failed to load paths: {0}".format(c.err), fg="yellow")
            vistir.misc.echo("Output: {0}".format(c.out), fg="yellow")
        return None

    @cached_property
    def sys_prefix(self):
        # type: () -> str
        """
        The prefix run inside the context of the environment

        :return: The python prefix inside the environment
        :rtype: :data:`sys.prefix`
        """

        command = [self.python, "-c", "import sys; print(sys.prefix)"]
        c = vistir.misc.run(command, return_object=True, block=True, nospin=True, write_to_stdout=False)
        sys_prefix = vistir.compat.Path(vistir.misc.to_text(c.out).strip()).as_posix()
        return sys_prefix

    @cached_property
    def paths(self):
        # type: () -> Dict[str, str]
        paths = {}
        with vistir.contextmanagers.temp_environ(), vistir.contextmanagers.temp_path():
            os.environ["PYTHONIOENCODING"] = vistir.compat.fs_str("utf-8")
            os.environ["PYTHONDONTWRITEBYTECODE"] = vistir.compat.fs_str("1")
            paths = self.base_paths
            os.environ["PATH"] = paths["PATH"]
            os.environ["PYTHONPATH"] = paths["PYTHONPATH"]
            if "headers" not in paths:
                paths["headers"] = paths["include"]
        return paths

    @property
    def scripts_dir(self):
        # type: () -> str
        return self.paths["scripts"]

    @property
    def libdir(self):
        # type: () -> str
        purelib = self.paths.get("purelib", None)
        if purelib and os.path.exists(purelib):
            return "purelib", purelib
        return "platlib", self.paths["platlib"]

    @property
    def pip_version(self):
        # type: () -> Version
        """
        Get the pip version in the environment.  Useful for knowing which args we can use
        when installing.
        """
        from .vendor.packaging.version import parse as parse_version
        pip = next(iter(
            pkg for pkg in self.get_installed_packages() if pkg.key == "pip"
        ), None)
        if pip is not None:
            return parse_version(pip.version)
        return parse_version("20.2")

    def expand_egg_links(self):
        # type: () -> None
        """
        Expand paths specified in egg-link files to prevent pip errors during
        reinstall
        """
        prefixes = [
            vistir.compat.Path(prefix)
            for prefix in self.base_paths["libdirs"].split(os.pathsep)
            if vistir.path.is_in_path(prefix, self.prefix.as_posix())
        ]
        for loc in prefixes:
            if not loc.exists():
                continue
            for pth in loc.iterdir():
                if not pth.suffix == ".egg-link":
                    continue
                contents = [
                    vistir.path.normalize_path(line.strip())
                    for line in pth.read_text().splitlines()
                ]
                pth.write_text("\n".join(contents))

    def get_distributions(self):
        # type: () -> Generator[pkg_resources.Distribution, None, None]
        """
        Retrives the distributions installed on the library path of the environment

        :return: A set of distributions found on the library path
        :rtype: iterator
        """

        pkg_resources = self.safe_import("pkg_resources")
        libdirs = self.base_paths["libdirs"].split(os.pathsep)
        dists = (pkg_resources.find_distributions(libdir) for libdir in libdirs)
        for dist in itertools.chain.from_iterable(dists):
            yield dist

    def find_egg(self, egg_dist):
        # type: (pkg_resources.Distribution) -> str
        """Find an egg by name in the given environment"""
        site_packages = self.libdir[1]
        search_filename = "{0}.egg-link".format(egg_dist.project_name)
        try:
            user_site = site.getusersitepackages()
        except AttributeError:
            user_site = site.USER_SITE
        search_locations = [site_packages, user_site]
        for site_directory in search_locations:
            egg = os.path.join(site_directory, search_filename)
            if os.path.isfile(egg):
                return egg

    def locate_dist(self, dist):
        # type: (pkg_resources.Distribution) -> str
        """Given a distribution, try to find a corresponding egg link first.

        If the egg - link doesn 't exist, return the supplied distribution."""

        location = self.find_egg(dist)
        return location or dist.location

    def dist_is_in_project(self, dist):
        # type: (pkg_resources.Distribution) -> bool
        """Determine whether the supplied distribution is in the environment."""
        from .project import _normalized
        prefixes = [
            _normalized(prefix) for prefix in self.base_paths["libdirs"].split(os.pathsep)
            if _normalized(prefix).startswith(_normalized(self.prefix.as_posix()))
        ]
        location = self.locate_dist(dist)
        if not location:
            return False
        location = _normalized(make_posix(location))
        return any(location.startswith(prefix) for prefix in prefixes)

    def get_installed_packages(self):
        # type: () -> List[pkg_resources.Distribution]
        """Returns all of the installed packages in a given environment"""
        workingset = self.get_working_set()
        packages = [
            pkg for pkg in workingset
            if self.dist_is_in_project(pkg) and pkg.key != "python"
        ]
        return packages

    @contextlib.contextmanager
    def get_finder(self, pre=False):
        # type: (bool) -> ContextManager[pip_shims.shims.PackageFinder]
        from .vendor.pip_shims.shims import (
            InstallCommand, get_package_finder
        )
        from .environments import PIPENV_CACHE_DIR

        pip_command = InstallCommand()
        pip_args = self._modules["pipenv"].utils.prepare_pip_source_args(self.sources)
        pip_options, _ = pip_command.parser.parse_args(pip_args)
        pip_options.cache_dir = PIPENV_CACHE_DIR
        pip_options.pre = self.pipfile.get("pre", pre)
        with pip_command._build_session(pip_options) as session:
            finder = get_package_finder(install_cmd=pip_command, options=pip_options, session=session)
            yield finder

    def get_package_info(self, pre=False):
        # type: (bool) -> Generator[pkg_resources.Distribution, None, None]
        from .vendor.pip_shims.shims import pip_version, parse_version
        dependency_links = []
        packages = self.get_installed_packages()
        # This code is borrowed from pip's current implementation
        if parse_version(pip_version) < parse_version("19.0"):
            for dist in packages:
                if dist.has_metadata('dependency_links.txt'):
                    dependency_links.extend(
                        dist.get_metadata_lines('dependency_links.txt')
                    )

        with self.get_finder() as finder:
            if parse_version(pip_version) < parse_version("19.0"):
                finder.add_dependency_links(dependency_links)

            for dist in packages:
                typ = 'unknown'
                all_candidates = finder.find_all_candidates(dist.key)
                if not self.pipfile.get("pre", finder.allow_all_prereleases):
                    # Remove prereleases
                    all_candidates = [
                        candidate for candidate in all_candidates
                        if not candidate.version.is_prerelease
                    ]

                if not all_candidates:
                    continue
                candidate_evaluator = finder.make_candidate_evaluator(project_name=dist.key)
                best_candidate_result = candidate_evaluator.compute_best_candidate(all_candidates)
                remote_version = best_candidate_result.best_candidate.version
                if best_candidate_result.best_candidate.link.is_wheel:
                    typ = 'wheel'
                else:
                    typ = 'sdist'
                # This is dirty but makes the rest of the code much cleaner
                dist.latest_version = remote_version
                dist.latest_filetype = typ
                yield dist

    def get_outdated_packages(self, pre=False):
        # type: (bool) -> List[pkg_resources.Distribution]
        return [
            pkg for pkg in self.get_package_info(pre=pre)
            if pkg.latest_version._key > pkg.parsed_version._key
        ]

    @classmethod
    def _get_requirements_for_package(cls, node, key_tree, parent=None, chain=None):
        if chain is None:
            chain = [node.project_name]

        d = node.as_dict()
        if parent:
            d['required_version'] = node.version_spec if node.version_spec else 'Any'
        else:
            d['required_version'] = d['installed_version']

        get_children = lambda n: key_tree.get(n.key, [])    # noqa

        d['dependencies'] = [
            cls._get_requirements_for_package(c, key_tree, parent=node,
                                              chain=chain+[c.project_name])
            for c in get_children(node)
            if c.project_name not in chain
        ]

        return d

    def get_package_requirements(self, pkg=None):
        from .vendor.pipdeptree import flatten, sorted_tree, build_dist_index, construct_tree
        packages = self.get_installed_packages()
        if pkg:
            packages = [p for p in packages if p.key == pkg]
        dist_index = build_dist_index(packages)
        tree = sorted_tree(construct_tree(dist_index))
        branch_keys = set(r.key for r in flatten(tree.values()))
        if pkg is not None:
            nodes = [p for p in tree.keys() if p.key == pkg]
        else:
            nodes = [p for p in tree.keys() if p.key not in branch_keys]
        key_tree = dict((k.key, v) for k, v in tree.items())

        return [self._get_requirements_for_package(p, key_tree) for p in nodes]

    @classmethod
    def reverse_dependency(cls, node):
        new_node = {
            "package_name": node["package_name"],
            "installed_version": node["installed_version"],
            "required_version": node["required_version"]
        }
        for dependency in node.get("dependencies", []):
            for dep in cls.reverse_dependency(dependency):
                new_dep = dep.copy()
                new_dep["parent"] = (node["package_name"], node["installed_version"])
                yield new_dep
        yield new_node

    def reverse_dependencies(self):
        from vistir.misc import unnest, chunked
        rdeps = {}
        for req in self.get_package_requirements():
            for d in self.reverse_dependency(req):
                parents = None
                name = d["package_name"]
                pkg = {
                    name: {
                        "installed": d["installed_version"],
                        "required": d["required_version"]
                    }
                }
                parents = tuple(d.get("parent", ()))
                pkg[name]["parents"] = parents
                if rdeps.get(name):
                    if not (rdeps[name].get("required") or rdeps[name].get("installed")):
                        rdeps[name].update(pkg[name])
                    rdeps[name]["parents"] = rdeps[name].get("parents", ()) + parents
                else:
                    rdeps[name] = pkg[name]
        for k in list(rdeps.keys()):
            entry = rdeps[k]
            if entry.get("parents"):
                rdeps[k]["parents"] = set([
                   p for p, version in chunked(2, unnest(entry["parents"]))
                ])
        return rdeps

    def get_working_set(self):
        """Retrieve the working set of installed packages for the environment.

        :return: The working set for the environment
        :rtype: :class:`pkg_resources.WorkingSet`
        """

        working_set = pkg_resources.WorkingSet(self.sys_path)
        return working_set

    def is_installed(self, pkgname):
        """Given a package name, returns whether it is installed in the environment

        :param str pkgname: The name of a package
        :return: Whether the supplied package is installed in the environment
        :rtype: bool
        """

        return any(d for d in self.get_distributions() if d.project_name == pkgname)

    def is_satisfied(self, req):
        match = next(
            iter(
                d for d in self.get_distributions()
                if canonicalize_name(d.project_name) == req.normalized_name
            ), None
        )
        if match is not None:
            if req.editable and req.line_instance.is_local and self.find_egg(match):
                requested_path = req.line_instance.path
                return requested_path and vistir.compat.samefile(requested_path, match.location)
            elif match.has_metadata("direct_url.json"):
                direct_url_metadata = json.loads(match.get_metadata("direct_url.json"))
                commit_id = direct_url_metadata.get("vcs_info", {}).get("commit_id", "")
                vcs_type = direct_url_metadata.get("vcs_info", {}).get("vcs", "")
                _, pipfile_part = req.as_pipfile().popitem()
                return (
                    vcs_type == req.vcs and commit_id == req.commit_hash
                    and direct_url_metadata["url"] == pipfile_part[req.vcs]
                )
            elif req.is_vcs or req.is_file_or_url:
                return False
            elif req.line_instance.specifiers is not None:
                return req.line_instance.specifiers.contains(
                    match.version, prereleases=True
                )
            return True
        return False

    def run(self, cmd, cwd=os.curdir):
        """Run a command with :class:`~subprocess.Popen` in the context of the environment

        :param cmd: A command to run in the environment
        :type cmd: str or list
        :param str cwd: The working directory in which to execute the command, defaults to :data:`os.curdir`
        :return: A finished command object
        :rtype: :class:`~subprocess.Popen`
        """

        c = None
        with self.activated():
            script = vistir.cmdparse.Script.parse(cmd)
            c = vistir.misc.run(script._parts, return_object=True, nospin=True, cwd=cwd, write_to_stdout=False)
        return c

    def run_py(self, cmd, cwd=os.curdir):
        """Run a python command in the enviornment context.

        :param cmd: A command to run in the environment - runs with `python -c`
        :type cmd: str or list
        :param str cwd: The working directory in which to execute the command, defaults to :data:`os.curdir`
        :return: A finished command object
        :rtype: :class:`~subprocess.Popen`
        """

        c = None
        if isinstance(cmd, six.string_types):
            script = vistir.cmdparse.Script.parse("{0} -c {1}".format(self.python, cmd))
        else:
            script = vistir.cmdparse.Script.parse([self.python, "-c"] + list(cmd))
        with self.activated():
            c = vistir.misc.run(script._parts, return_object=True, nospin=True, cwd=cwd, write_to_stdout=False)
        return c

    def run_activate_this(self):
        """Runs the environment's inline activation script"""
        if self.is_venv:
            activate_this = os.path.join(self.scripts_dir, "activate_this.py")
            if not os.path.isfile(activate_this):
                raise OSError("No such file: {0!s}".format(activate_this))
            with open(activate_this, "r") as f:
                code = compile(f.read(), activate_this, "exec")
                exec(code, dict(__file__=activate_this))

    @contextlib.contextmanager
    def activated(self, include_extras=True, extra_dists=None):
        """Helper context manager to activate the environment.

        This context manager will set the following variables for the duration
        of its activation:

            * sys.prefix
            * sys.path
            * os.environ["VIRTUAL_ENV"]
            * os.environ["PATH"]

        In addition, it will make any distributions passed into `extra_dists` available
        on `sys.path` while inside the context manager, as well as making `passa` itself
        available.

        The environment's `prefix` as well as `scripts_dir` properties are both prepended
        to `os.environ["PATH"]` to ensure that calls to `~Environment.run()` use the
        environment's path preferentially.
        """

        if not extra_dists:
            extra_dists = []
        original_path = sys.path
        original_prefix = sys.prefix
        parent_path = vistir.compat.Path(__file__).absolute().parent
        vendor_dir = parent_path.joinpath("vendor").as_posix()
        patched_dir = parent_path.joinpath("patched").as_posix()
        parent_path = parent_path.as_posix()
        self.add_dist("pip")
        prefix = self.prefix.as_posix()
        with vistir.contextmanagers.temp_environ(), vistir.contextmanagers.temp_path():
            os.environ["PATH"] = os.pathsep.join([
                vistir.compat.fs_str(self.script_basedir),
                vistir.compat.fs_str(self.prefix.as_posix()),
                os.environ.get("PATH", "")
            ])
            os.environ["PYTHONIOENCODING"] = vistir.compat.fs_str("utf-8")
            os.environ["PYTHONDONTWRITEBYTECODE"] = vistir.compat.fs_str("1")
            from .environments import PIPENV_USE_SYSTEM
            if self.is_venv:
                os.environ["PYTHONPATH"] = self.base_paths["PYTHONPATH"]
                os.environ["VIRTUAL_ENV"] = vistir.compat.fs_str(prefix)
            else:
                if not PIPENV_USE_SYSTEM and not os.environ.get("VIRTUAL_ENV"):
                    os.environ["PYTHONPATH"] = self.base_paths["PYTHONPATH"]
                    os.environ.pop("PYTHONHOME", None)
            sys.path = self.sys_path
            sys.prefix = self.sys_prefix
            site.addsitedir(self.base_paths["purelib"])
            pip = self.safe_import("pip")       # noqa
            pip_vendor = self.safe_import("pip._vendor")
            pep517_dir = os.path.join(os.path.dirname(pip_vendor.__file__), "pep517")
            site.addsitedir(pep517_dir)
            os.environ["PYTHONPATH"] = os.pathsep.join([
                os.environ.get("PYTHONPATH", self.base_paths["PYTHONPATH"]), pep517_dir
            ])
            if include_extras:
                site.addsitedir(parent_path)
                sys.path.extend([parent_path, patched_dir, vendor_dir])
                extra_dists = list(self.extra_dists) + extra_dists
                for extra_dist in extra_dists:
                    if extra_dist not in self.get_working_set():
                        extra_dist.activate(self.sys_path)
            try:
                yield
            finally:
                sys.path = original_path
                sys.prefix = original_prefix
                six.moves.reload_module(pkg_resources)

    @cached_property
    def finders(self):
        from pipenv.vendor.pythonfinder import Finder
        finders = [
            Finder(path=self.base_paths["scripts"], global_search=gs, system=False)
            for gs in (False, True)
        ]
        return finders

    @property
    def finder(self):
        return next(iter(self.finders), None)

    def which(self, search, as_path=True):
        find = operator.methodcaller("which", search)
        result = next(iter(filter(None, (find(finder) for finder in self.finders))), None)
        if not result:
            result = self._which(search)
        else:
            if as_path:
                result = str(result.path)
        return result

    def get_install_args(self, editable=False, setup_path=None):
        install_arg = "install" if not editable else "develop"
        install_keys = ["headers", "purelib", "platlib", "scripts", "data"]
        install_args = [
            self.environment.python, "-u", "-c", SETUPTOOLS_SHIM % setup_path,
            install_arg, "--single-version-externally-managed", "--no-deps",
            "--prefix={0}".format(self.base_paths["prefix"]), "--no-warn-script-location"
        ]
        for key in install_keys:
            install_args.append(
                "--install-{0}={1}".format(key, self.base_paths[key])
            )
        return install_args

    def install(self, requirements):
        if not isinstance(requirements, (tuple, list)):
            requirements = [requirements]
        with self.get_finder() as finder:
            args = []
            for format_control in ('no_binary', 'only_binary'):
                formats = getattr(finder.format_control, format_control)
                args.extend(('--' + format_control.replace('_', '-'),
                            ','.join(sorted(formats or {':none:'}))))
            if finder.index_urls:
                args.extend(['-i', finder.index_urls[0]])
                for extra_index in finder.index_urls[1:]:
                    args.extend(['--extra-index-url', extra_index])
            else:
                args.append('--no-index')
            for link in finder.find_links:
                args.extend(['--find-links', link])
            for _, host, _ in finder.secure_origins:
                args.extend(['--trusted-host', host])
            if finder.allow_all_prereleases:
                args.append('--pre')
            if finder.process_dependency_links:
                args.append('--process-dependency-links')
            args.append('--')
            args.extend(requirements)
            out, _ = vistir.misc.run(args, return_object=False, nospin=True, block=True,
                                     combine_stderr=False)

    @contextlib.contextmanager
    def uninstall(self, pkgname, *args, **kwargs):
        """A context manager which allows uninstallation of packages from the environment

        :param str pkgname: The name of a package to uninstall

        >>> env = Environment("/path/to/env/root")
        >>> with env.uninstall("pytz", auto_confirm=True, verbose=False) as uninstaller:
                cleaned = uninstaller.paths
        >>> if cleaned:
                print("uninstalled packages: %s" % cleaned)
        """

        auto_confirm = kwargs.pop("auto_confirm", True)
        verbose = kwargs.pop("verbose", False)
        with self.activated():
            monkey_patch = next(iter(
                dist for dist in self.base_working_set
                if dist.project_name == "recursive-monkey-patch"
            ), None)
            if monkey_patch:
                monkey_patch.activate()
            pip_shims = self.safe_import("pip_shims")
            pathset_base = pip_shims.UninstallPathSet
            pathset_base._permitted = PatchedUninstaller._permitted
            dist = next(
                iter(d for d in self.get_working_set() if d.project_name == pkgname),
                None
            )
            pathset = pathset_base.from_dist(dist)
            if pathset is not None:
                pathset.remove(auto_confirm=auto_confirm, verbose=verbose)
            try:
                yield pathset
            except Exception:
                if pathset is not None:
                    pathset.rollback()
            else:
                if pathset is not None:
                    pathset.commit()
            if pathset is None:
                return


class PatchedUninstaller(object):
    def _permitted(self, path):
        return True


SETUPTOOLS_SHIM = (
    "import setuptools, tokenize;__file__=%r;"
    "f=getattr(tokenize, 'open', open)(__file__);"
    "code=f.read().replace('\\r\\n', '\\n');"
    "f.close();"
    "exec(compile(code, __file__, 'exec'))"
)
