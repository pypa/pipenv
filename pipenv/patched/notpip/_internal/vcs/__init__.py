"""Handles all VCS (version control) support"""
from __future__ import absolute_import

import copy
import errno
import logging
import os
import shutil
import sys

from pipenv.patched.notpip._vendor.six.moves.urllib import parse as urllib_parse

from pipenv.patched.notpip._internal.exceptions import BadCommand
from pipenv.patched.notpip._internal.utils.misc import (
    display_path, backup_dir, call_subprocess, rmtree, ask_path_exists,
)
from pipenv.patched.notpip._internal.utils.typing import MYPY_CHECK_RUNNING

if MYPY_CHECK_RUNNING:
    from typing import Dict, Optional, Tuple
    from pipenv.patched.notpip._internal.basecommand import Command

__all__ = ['vcs', 'get_src_requirement']


logger = logging.getLogger(__name__)


class RevOptions(object):

    """
    Encapsulates a VCS-specific revision to install, along with any VCS
    install options.

    Instances of this class should be treated as if immutable.
    """

    def __init__(self, vcs, rev=None, extra_args=None):
        """
        Args:
          vcs: a VersionControl object.
          rev: the name of the revision to install.
          extra_args: a list of extra options.
        """
        if extra_args is None:
            extra_args = []

        self.extra_args = extra_args
        self.rev = rev
        self.vcs = vcs

    def __repr__(self):
        return '<RevOptions {}: rev={!r}>'.format(self.vcs.name, self.rev)

    @property
    def arg_rev(self):
        if self.rev is None:
            return self.vcs.default_arg_rev

        return self.rev

    def to_args(self):
        """
        Return the VCS-specific command arguments.
        """
        args = []
        rev = self.arg_rev
        if rev is not None:
            args += self.vcs.get_base_rev_args(rev)
        args += self.extra_args

        return args

    def to_display(self):
        if not self.rev:
            return ''

        return ' (to revision {})'.format(self.rev)

    def make_new(self, rev):
        """
        Make a copy of the current instance, but with a new rev.

        Args:
          rev: the name of the revision for the new object.
        """
        return self.vcs.make_rev_options(rev, extra_args=self.extra_args)


class VcsSupport(object):
    _registry = {}  # type: Dict[str, Command]
    schemes = ['ssh', 'git', 'hg', 'bzr', 'sftp', 'svn']

    def __init__(self):
        # Register more schemes with urlparse for various version control
        # systems
        urllib_parse.uses_netloc.extend(self.schemes)
        # Python >= 2.7.4, 3.3 doesn't have uses_fragment
        if getattr(urllib_parse, 'uses_fragment', None):
            urllib_parse.uses_fragment.extend(self.schemes)
        super(VcsSupport, self).__init__()

    def __iter__(self):
        return self._registry.__iter__()

    @property
    def backends(self):
        return list(self._registry.values())

    @property
    def dirnames(self):
        return [backend.dirname for backend in self.backends]

    @property
    def all_schemes(self):
        schemes = []
        for backend in self.backends:
            schemes.extend(backend.schemes)
        return schemes

    def register(self, cls):
        if not hasattr(cls, 'name'):
            logger.warning('Cannot register VCS %s', cls.__name__)
            return
        if cls.name not in self._registry:
            self._registry[cls.name] = cls
            logger.debug('Registered VCS backend: %s', cls.name)

    def unregister(self, cls=None, name=None):
        if name in self._registry:
            del self._registry[name]
        elif cls in self._registry.values():
            del self._registry[cls.name]
        else:
            logger.warning('Cannot unregister because no class or name given')

    def get_backend_name(self, location):
        """
        Return the name of the version control backend if found at given
        location, e.g. vcs.get_backend_name('/path/to/vcs/checkout')
        """
        for vc_type in self._registry.values():
            if vc_type.controls_location(location):
                logger.debug('Determine that %s uses VCS: %s',
                             location, vc_type.name)
                return vc_type.name
        return None

    def get_backend(self, name):
        name = name.lower()
        if name in self._registry:
            return self._registry[name]

    def get_backend_from_location(self, location):
        vc_type = self.get_backend_name(location)
        if vc_type:
            return self.get_backend(vc_type)
        return None


vcs = VcsSupport()


class VersionControl(object):
    name = ''
    dirname = ''
    # List of supported schemes for this Version Control
    schemes = ()  # type: Tuple[str, ...]
    # Iterable of environment variable names to pass to call_subprocess().
    unset_environ = ()  # type: Tuple[str, ...]
    default_arg_rev = None  # type: Optional[str]

    def __init__(self, url=None, *args, **kwargs):
        self.url = url
        super(VersionControl, self).__init__(*args, **kwargs)

    def get_base_rev_args(self, rev):
        """
        Return the base revision arguments for a vcs command.

        Args:
          rev: the name of a revision to install.  Cannot be None.
        """
        raise NotImplementedError

    def make_rev_options(self, rev=None, extra_args=None):
        """
        Return a RevOptions object.

        Args:
          rev: the name of a revision to install.
          extra_args: a list of extra options.
        """
        return RevOptions(self, rev, extra_args=extra_args)

    def _is_local_repository(self, repo):
        """
           posix absolute paths start with os.path.sep,
           win32 ones start with drive (like c:\\folder)
        """
        drive, tail = os.path.splitdrive(repo)
        return repo.startswith(os.path.sep) or drive

    # See issue #1083 for why this method was introduced:
    # https://github.com/pypa/pip/issues/1083
    def translate_egg_surname(self, surname):
        # For example, Django has branches of the form "stable/1.7.x".
        return surname.replace('/', '_')

    def export(self, location):
        """
        Export the repository at the url to the destination location
        i.e. only download the files, without vcs informations
        """
        raise NotImplementedError

    def get_url_rev(self):
        """
        Returns the correct repository URL and revision by parsing the given
        repository URL
        """
        error_message = (
            "Sorry, '%s' is a malformed VCS url. "
            "The format is <vcs>+<protocol>://<url>, "
            "e.g. svn+http://myrepo/svn/MyApp#egg=MyApp"
        )
        assert '+' in self.url, error_message % self.url
        url = self.url.split('+', 1)[1]
        scheme, netloc, path, query, frag = urllib_parse.urlsplit(url)
        rev = None
        if '@' in path:
            path, rev = path.rsplit('@', 1)
        url = urllib_parse.urlunsplit((scheme, netloc, path, query, ''))
        return url, rev

    def get_info(self, location):
        """
        Returns (url, revision), where both are strings
        """
        assert not location.rstrip('/').endswith(self.dirname), \
            'Bad directory: %s' % location
        return self.get_url(location), self.get_revision(location)

    def normalize_url(self, url):
        """
        Normalize a URL for comparison by unquoting it and removing any
        trailing slash.
        """
        return urllib_parse.unquote(url).rstrip('/')

    def compare_urls(self, url1, url2):
        """
        Compare two repo URLs for identity, ignoring incidental differences.
        """
        return (self.normalize_url(url1) == self.normalize_url(url2))

    def obtain(self, dest):
        """
        Called when installing or updating an editable package, takes the
        source path of the checkout.
        """
        raise NotImplementedError

    def switch(self, dest, url, rev_options):
        """
        Switch the repo at ``dest`` to point to ``URL``.

        Args:
          rev_options: a RevOptions object.
        """
        raise NotImplementedError

    def update(self, dest, rev_options):
        """
        Update an already-existing repo to the given ``rev_options``.

        Args:
          rev_options: a RevOptions object.
        """
        raise NotImplementedError

    def is_commit_id_equal(self, dest, name):
        """
        Return whether the id of the current commit equals the given name.

        Args:
          dest: the repository directory.
          name: a string name.
        """
        raise NotImplementedError

    def check_destination(self, dest, url, rev_options):
        """
        Prepare a location to receive a checkout/clone.

        Return True if the location is ready for (and requires) a
        checkout/clone, False otherwise.

        Args:
          rev_options: a RevOptions object.
        """
        checkout = True
        prompt = False
        rev_display = rev_options.to_display()
        if os.path.exists(dest):
            checkout = False
            if os.path.exists(os.path.join(dest, self.dirname)):
                existing_url = self.get_url(dest)
                if self.compare_urls(existing_url, url):
                    logger.debug(
                        '%s in %s exists, and has correct URL (%s)',
                        self.repo_name.title(),
                        display_path(dest),
                        url,
                    )
                    if not self.is_commit_id_equal(dest, rev_options.rev):
                        logger.info(
                            'Updating %s %s%s',
                            display_path(dest),
                            self.repo_name,
                            rev_display,
                        )
                        self.update(dest, rev_options)
                    else:
                        logger.info(
                            'Skipping because already up-to-date.')
                else:
                    logger.warning(
                        '%s %s in %s exists with URL %s',
                        self.name,
                        self.repo_name,
                        display_path(dest),
                        existing_url,
                    )
                    prompt = ('(s)witch, (i)gnore, (w)ipe, (b)ackup ',
                              ('s', 'i', 'w', 'b'))
            else:
                logger.warning(
                    'Directory %s already exists, and is not a %s %s.',
                    dest,
                    self.name,
                    self.repo_name,
                )
                prompt = ('(i)gnore, (w)ipe, (b)ackup ', ('i', 'w', 'b'))
        if prompt:
            logger.warning(
                'The plan is to install the %s repository %s',
                self.name,
                url,
            )
            response = ask_path_exists('What to do?  %s' % prompt[0],
                                       prompt[1])

            if response == 's':
                logger.info(
                    'Switching %s %s to %s%s',
                    self.repo_name,
                    display_path(dest),
                    url,
                    rev_display,
                )
                self.switch(dest, url, rev_options)
            elif response == 'i':
                # do nothing
                pass
            elif response == 'w':
                logger.warning('Deleting %s', display_path(dest))
                rmtree(dest)
                checkout = True
            elif response == 'b':
                dest_dir = backup_dir(dest)
                logger.warning(
                    'Backing up %s to %s', display_path(dest), dest_dir,
                )
                shutil.move(dest, dest_dir)
                checkout = True
            elif response == 'a':
                sys.exit(-1)
        return checkout

    def unpack(self, location):
        """
        Clean up current location and download the url repository
        (and vcs infos) into location
        """
        if os.path.exists(location):
            rmtree(location)
        self.obtain(location)

    def get_src_requirement(self, dist, location):
        """
        Return a string representing the requirement needed to
        redownload the files currently present in location, something
        like:
          {repository_url}@{revision}#egg={project_name}-{version_identifier}
        """
        raise NotImplementedError

    def get_url(self, location):
        """
        Return the url used at location
        Used in get_info or check_destination
        """
        raise NotImplementedError

    def get_revision(self, location):
        """
        Return the current commit id of the files at the given location.
        """
        raise NotImplementedError

    def run_command(self, cmd, show_stdout=True, cwd=None,
                    on_returncode='raise',
                    command_desc=None,
                    extra_environ=None, spinner=None):
        """
        Run a VCS subcommand
        This is simply a wrapper around call_subprocess that adds the VCS
        command name, and checks that the VCS is available
        """
        cmd = [self.name] + cmd
        try:
            return call_subprocess(cmd, show_stdout, cwd,
                                   on_returncode,
                                   command_desc, extra_environ,
                                   unset_environ=self.unset_environ,
                                   spinner=spinner)
        except OSError as e:
            # errno.ENOENT = no such file or directory
            # In other words, the VCS executable isn't available
            if e.errno == errno.ENOENT:
                raise BadCommand(
                    'Cannot find command %r - do you have '
                    '%r installed and in your '
                    'PATH?' % (self.name, self.name))
            else:
                raise  # re-raise exception if a different error occurred

    @classmethod
    def controls_location(cls, location):
        """
        Check if a location is controlled by the vcs.
        It is meant to be overridden to implement smarter detection
        mechanisms for specific vcs.
        """
        logger.debug('Checking in %s for %s (%s)...',
                     location, cls.dirname, cls.name)
        path = os.path.join(location, cls.dirname)
        return os.path.exists(path)


def get_src_requirement(dist, location):
    version_control = vcs.get_backend_from_location(location)
    if version_control:
        try:
            return version_control().get_src_requirement(dist,
                                                         location)
        except BadCommand:
            logger.warning(
                'cannot determine version of editable source in %s '
                '(%s command not found in path)',
                location,
                version_control.name,
            )
            return dist.as_requirement()
    logger.warning(
        'cannot determine version of editable source in %s (is not SVN '
        'checkout, Git clone, Mercurial clone or Bazaar branch)',
        location,
    )
    return dist.as_requirement()
