import click
import pkg_resources


class PluginManager(object):  # pylint: disable=too-few-public-methods
    """Find and manage plugins."""

    def __init__(self, cli=None, namespace='pipenv.extension',
                 verify_requirements=False):
        """Initialize the manager.
        :param str namespace:
            Namespace of the plugins to manage, e.g., 'pipenv.extension'.
        :param bool verify_requirements:
            Whether or not to make setuptools verify that the requirements for
            the plugin are satisfied.
        """
        self.namespace = namespace
        self.verify_requirements = verify_requirements
        self.plugins = {}
        self.names = []
        self.cli = cli
        self._load_entrypoint_plugins()
        # TODO: Use pluggy or blinker to register hooks?

    def _load_entrypoint_plugins(self):
        for entry_point in pkg_resources.iter_entry_points(self.namespace):
            self._load_plugin_from_entrypoint(entry_point)

    def _load_plugin_from_entrypoint(self, entry_point):
        """Load a plugin from a setuptools EntryPoint.
        :param EntryPoint entry_point:
            EntryPoint to load plugin from.
        """
        name = entry_point.name
        self.plugins[name] = Plugin(name, entry_point)
        self.names.append(name)
        if self.cli is not None:
            self.cli.add_command(self.plugins[name].plugin, name=name)


class Plugin(object):
    """Wrap an EntryPoint from setuptools and other logic."""

    def __init__(self, name, entry_point, verify_requirements=False):
            """Initialize our Plugin.
            :param str name:
                Name of the entry-point as it was registered with setuptools.
            :param entry_point:
                EntryPoint returned by setuptools.
            :type entry_point:
                setuptools.EntryPoint
            """
            self.name = name
            self.entry_point = entry_point
            self._plugin = None
            self._plugin_name = None
            self._verify_requirements = verify_requirements

    def __repr__(self):
        """Provide an easy to read description of the current plugin."""
        return 'Plugin(name="{0}", entry_point="{1}")'.format(
            self.name, self.entry_point
        )

    @property
    def plugin(self):
        """Load and return the plugin associated with the entry-point.
        This property implicitly loads the plugin and then caches it.
        """
        self.load_plugin()
        return self._plugin

    def execute(self, *args, **kwargs):
        r"""Call the plugin with \*args and \*\*kwargs."""
        return self.plugin(*args, **kwargs)  # pylint: disable=not-callable

    def _load(self):
        # Avoid relying on hasattr() here.
        resolve = getattr(self.entry_point, 'resolve', None)
        require = getattr(self.entry_point, 'require', None)
        if resolve and require:
            if self._verify_requirements:
                require()
            self._plugin = resolve()
        else:
            self._plugin = self.entry_point.load(
                require=self._verify_requirements
            )
        if not callable(self._plugin):
            msg = ('Plugin %r is not a callable'
                   ' version' % self._plugin)
            raise TypeError(msg)

    def load_plugin(self):
        """Retrieve the plugin for this entry-point.
        This loads the plugin, stores it on the instance and then returns it.
        It does not reload it after the first time, it merely returns the
        cached plugin.
        :returns:
            Nothing
        """
        if self._plugin is None:
            try:
                self._load()
            except Exception as e:
                click.echo(
                    'Cannot load the plugin %r with error %s' % (self, str(e))
                )
                # could use contextlib.supress here if only py3
