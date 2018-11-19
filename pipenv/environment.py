# -*- coding=utf-8 -*-

import contextlib
import importlib
import json
import os
import sys
import operator
import pkg_resources
import site
import six

from distutils.sysconfig import get_python_lib
from sysconfig import get_paths

from cached_property import cached_property

import vistir
import pipenv

from .utils import normalize_path

BASE_WORKING_SET = pkg_resources.WorkingSet(sys.path)


class Environment(object):
    def __init__(self, prefix=None, is_venv=False, base_working_set=None, pipfile=None,
                 sources=None, project=None):
        super(Environment, self).__init__()
        self._modules = {'pkg_resources': pkg_resources, 'pipenv': pipenv}
        self.base_working_set = base_working_set if base_working_set else BASE_WORKING_SET
        prefix = normalize_path(prefix)
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
        self.sys_paths = get_paths()

    def safe_import(self, name):
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
        return module

    @classmethod
    def resolve_dist(cls, dist, working_set):
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
        except (AttributeError, OSError, IOError):  # The METADATA file can't be found
            return deps
        for req in reqs:
            dist = working_set.find(req)
            deps |= cls.resolve_dist(dist, working_set)
        return deps

    def add_dist(self, dist_name):
        dist = pkg_resources.get_distribution(pkg_resources.Requirement(dist_name))
        extras = self.resolve_dist(dist, self.base_working_set)
        if extras:
            self.extra_dists.extend(extras)

    @cached_property
    def python_version(self):
        with self.activated():
            from sysconfig import get_python_version
            py_version = get_python_version()
            return py_version

    @property
    def python_info(self):
        include_dir = self.prefix / "include"
        python_path = next(iter(list(include_dir.iterdir())), None)
        if python_path and python_path.name.startswith("python"):
            python_version = python_path.name.replace("python", "")
            py_version_short, abiflags = python_version[:3], python_version[3:]
            return {"py_version_short": py_version_short, "abiflags": abiflags}
        return {}

    @cached_property
    def base_paths(self):
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

        prefix = self.prefix.as_posix()
        install_scheme = 'nt' if (os.name == 'nt') else 'posix_prefix'
        paths = get_paths(install_scheme, vars={
            'base': prefix,
            'platbase': prefix,
        })
        paths["PATH"] = paths["scripts"] + os.pathsep + os.defpath
        if "prefix" not in paths:
            paths["prefix"] = prefix
        purelib = get_python_lib(plat_specific=0, prefix=prefix)
        platlib = get_python_lib(plat_specific=1, prefix=prefix)
        if purelib == platlib:
            lib_dirs = purelib
        else:
            lib_dirs = purelib + os.pathsep + platlib
        paths["libdir"] = purelib
        paths["purelib"] = purelib
        paths["platlib"] = platlib
        paths['PYTHONPATH'] = lib_dirs
        paths["libdirs"] = lib_dirs
        return paths

    @cached_property
    def script_basedir(self):
        """Path to the environment scripts dir"""
        script_dir = self.base_paths["scripts"]
        return script_dir

    @property
    def python(self):
        """Path to the environment python"""
        py = vistir.compat.Path(self.base_paths["scripts"]).joinpath("python").as_posix()
        if not py:
            return vistir.compat.Path(sys.executable).as_posix()
        return py

    @cached_property
    def sys_path(self):
        """The system path inside the environment

        :return: The :data:`sys.path` from the environment
        :rtype: list
        """

        current_executable = vistir.compat.Path(sys.executable).as_posix()
        if not self.python or self.python == current_executable:
            return sys.path
        elif any([sys.prefix == self.prefix, not self.is_venv]):
            return sys.path
        cmd_args = [self.python, "-c", "import json, sys; print(json.dumps(sys.path))"]
        path, _ = vistir.misc.run(cmd_args, return_object=False, nospin=True, block=True, combine_stderr=False, write_to_stdout=False)
        path = json.loads(path.strip())
        return path

    @cached_property
    def sys_prefix(self):
        """The prefix run inside the context of the environment

        :return: The python prefix inside the environment
        :rtype: :data:`sys.prefix`
        """

        command = [self.python, "-c" "import sys; print(sys.prefix)"]
        c = vistir.misc.run(command, return_object=True, block=True, nospin=True, write_to_stdout=False)
        sys_prefix = vistir.compat.Path(vistir.misc.to_text(c.out).strip()).as_posix()
        return sys_prefix

    @cached_property
    def paths(self):
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
        return self.paths["scripts"]

    @property
    def libdir(self):
        purelib = self.paths.get("purelib", None)
        if purelib and os.path.exists(purelib):
            return "purelib", purelib
        return "platlib", self.paths["platlib"]

    def get_distributions(self):
        """Retrives the distributions installed on the library path of the environment

        :return: A set of distributions found on the library path
        :rtype: iterator
        """

        pkg_resources = self.safe_import("pkg_resources")
        return pkg_resources.find_distributions(self.paths["PYTHONPATH"])

    def find_egg(self, egg_dist):
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
        """Given a distribution, try to find a corresponding egg link first.

        If the egg - link doesn 't exist, return the supplied distribution."""

        location = self.find_egg(dist)
        return location or dist.location

    def dist_is_in_project(self, dist):
        """Determine whether the supplied distribution is in the environment."""
        from .project import _normalized
        prefix = _normalized(self.base_paths["prefix"])
        location = self.locate_dist(dist)
        if not location:
            return False
        return _normalized(location).startswith(prefix)

    def get_installed_packages(self):
        """Returns all of the installed packages in a given environment"""
        workingset = self.get_working_set()
        packages = [pkg for pkg in workingset if self.dist_is_in_project(pkg)]
        return packages

    @contextlib.contextmanager
    def get_finder(self, pre=False):
        from .vendor.pip_shims import Command, cmdoptions, index_group, PackageFinder
        from .environments import PIPENV_CACHE_DIR
        index_urls = [source.get("url") for source in self.sources]

        class PipCommand(Command):
            name = "PipCommand"

        pip_command = PipCommand()
        index_opts = cmdoptions.make_option_group(
            index_group, pip_command.parser
        )
        cmd_opts = pip_command.cmd_opts
        pip_command.parser.insert_option_group(0, index_opts)
        pip_command.parser.insert_option_group(0, cmd_opts)
        pip_args = self._modules["pipenv"].utils.prepare_pip_source_args(self.sources)
        pip_options, _ = pip_command.parser.parse_args(pip_args)
        pip_options.cache_dir = PIPENV_CACHE_DIR
        pip_options.pre = self.pipfile.get("pre", pre)
        with pip_command._build_session(pip_options) as session:
            finder = PackageFinder(
                find_links=pip_options.find_links,
                index_urls=index_urls, allow_all_prereleases=pip_options.pre,
                trusted_hosts=pip_options.trusted_hosts,
                process_dependency_links=pip_options.process_dependency_links,
                session=session
            )
            yield finder

    def get_package_info(self, pre=False):
        dependency_links = []
        packages = self.get_installed_packages()
        # This code is borrowed from pip's current implementation
        for dist in packages:
            if dist.has_metadata('dependency_links.txt'):
                dependency_links.extend(dist.get_metadata_lines('dependency_links.txt'))

        with self.get_finder() as finder:
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
                best_candidate = max(all_candidates, key=finder._candidate_sort_key)
                remote_version = best_candidate.version
                if best_candidate.location.is_wheel:
                    typ = 'wheel'
                else:
                    typ = 'sdist'
                # This is dirty but makes the rest of the code much cleaner
                dist.latest_version = remote_version
                dist.latest_filetype = typ
                yield dist

    def get_outdated_packages(self, pre=False):
        return [
            pkg for pkg in self.get_package_info(pre=pre)
            if pkg.latest_version._version > pkg.parsed_version._version
        ]

    def get_package_requirements(self):
        from .vendor.pipdeptree import flatten, sorted_tree, build_dist_index, construct_tree
        dist_index = build_dist_index(self.get_installed_packages())
        tree = sorted_tree(construct_tree(dist_index))
        branch_keys = set(r.key for r in flatten(tree.values()))
        nodes = [p for p in tree.keys() if p.key not in branch_keys]
        key_tree = dict((k.key, v) for k, v in tree.items())
        get_children = lambda n: key_tree.get(n.key, [])

        def aux(node, parent=None, chain=None):
            if chain is None:
                chain = [node.project_name]

            d = node.as_dict()
            if parent:
                d['required_version'] = node.version_spec if node.version_spec else 'Any'
            else:
                d['required_version'] = d['installed_version']

            d['dependencies'] = [
                aux(c, parent=node, chain=chain+[c.project_name])
                for c in get_children(node)
                if c.project_name not in chain
            ]

            return d
        return [aux(p) for p in nodes]

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
        prefix = self.prefix.as_posix()
        with vistir.contextmanagers.temp_environ(), vistir.contextmanagers.temp_path():
            os.environ["PATH"] = os.pathsep.join([
                vistir.compat.fs_str(self.scripts_dir),
                vistir.compat.fs_str(self.prefix.as_posix()),
                os.environ.get("PATH", "")
            ])
            os.environ["PYTHONIOENCODING"] = vistir.compat.fs_str("utf-8")
            os.environ["PYTHONDONTWRITEBYTECODE"] = vistir.compat.fs_str("1")
            os.environ["PYTHONPATH"] = self.base_paths["PYTHONPATH"]
            if self.is_venv:
                os.environ["VIRTUAL_ENV"] = vistir.compat.fs_str(prefix)
            sys.path = self.sys_path
            sys.prefix = self.sys_prefix
            site.addsitedir(self.base_paths["purelib"])
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
            requirements = [requirements,]
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
            import recursive_monkey_patch
            recursive_monkey_patch.monkey_patch(
                PatchedUninstaller, pathset_base
            )
            dist = next(
                iter(filter(lambda d: d.project_name == pkgname, self.get_working_set())),
                None
            )
            pathset = pathset_base.from_dist(dist)
            if pathset is not None:
                pathset.remove(auto_confirm=auto_confirm, verbose=verbose)
            try:
                yield pathset
            except Exception as e:
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
