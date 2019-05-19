from __future__ import absolute_import

import logging
import os.path
import re

from pipenv.patched.notpip._vendor.packaging.version import parse as parse_version
from pipenv.patched.notpip._vendor.six.moves.urllib import parse as urllib_parse
from pipenv.patched.notpip._vendor.six.moves.urllib import request as urllib_request

from pipenv.patched.notpip._internal.exceptions import BadCommand
from pipenv.patched.notpip._internal.utils.compat import samefile
from pipenv.patched.notpip._internal.utils.misc import (
    display_path, make_vcs_requirement_url, redact_password_from_url,
)
from pipenv.patched.notpip._internal.utils.temp_dir import TempDirectory
from pipenv.patched.notpip._internal.vcs import RemoteNotFoundError, VersionControl, vcs

urlsplit = urllib_parse.urlsplit
urlunsplit = urllib_parse.urlunsplit


logger = logging.getLogger(__name__)


HASH_REGEX = re.compile('[a-fA-F0-9]{40}')


def looks_like_hash(sha):
    return bool(HASH_REGEX.match(sha))


class Git(VersionControl):
    name = 'git'
    dirname = '.git'
    repo_name = 'clone'
    schemes = (
        'git', 'git+http', 'git+https', 'git+ssh', 'git+git', 'git+file',
    )
    # Prevent the user's environment variables from interfering with pip:
    # https://github.com/pypa/pip/issues/1130
    unset_environ = ('GIT_DIR', 'GIT_WORK_TREE')
    default_arg_rev = 'HEAD'

    def __init__(self, url=None, *args, **kwargs):

        # Works around an apparent Git bug
        # (see https://article.gmane.org/gmane.comp.version-control.git/146500)
        if url:
            scheme, netloc, path, query, fragment = urlsplit(url)
            if scheme.endswith('file'):
                initial_slashes = path[:-len(path.lstrip('/'))]
                newpath = (
                    initial_slashes +
                    urllib_request.url2pathname(path)
                    .replace('\\', '/').lstrip('/')
                )
                url = urlunsplit((scheme, netloc, newpath, query, fragment))
                after_plus = scheme.find('+') + 1
                url = scheme[:after_plus] + urlunsplit(
                    (scheme[after_plus:], netloc, newpath, query, fragment),
                )

        super(Git, self).__init__(url, *args, **kwargs)

    def get_base_rev_args(self, rev):
        return [rev]

    def get_git_version(self):
        VERSION_PFX = 'git version '
        version = self.run_command(['version'], show_stdout=False)
        if version.startswith(VERSION_PFX):
            version = version[len(VERSION_PFX):].split()[0]
        else:
            version = ''
        # get first 3 positions of the git version becasue
        # on windows it is x.y.z.windows.t, and this parses as
        # LegacyVersion which always smaller than a Version.
        version = '.'.join(version.split('.')[:3])
        return parse_version(version)

    def get_current_branch(self, location):
        """
        Return the current branch, or None if HEAD isn't at a branch
        (e.g. detached HEAD).
        """
        # git-symbolic-ref exits with empty stdout if "HEAD" is a detached
        # HEAD rather than a symbolic ref.  In addition, the -q causes the
        # command to exit with status code 1 instead of 128 in this case
        # and to suppress the message to stderr.
        args = ['symbolic-ref', '-q', 'HEAD']
        output = self.run_command(
            args, extra_ok_returncodes=(1, ), show_stdout=False, cwd=location,
        )
        ref = output.strip()

        if ref.startswith('refs/heads/'):
            return ref[len('refs/heads/'):]

        return None

    def export(self, location):
        """Export the Git repository at the url to the destination location"""
        if not location.endswith('/'):
            location = location + '/'

        with TempDirectory(kind="export") as temp_dir:
            self.unpack(temp_dir.path)
            self.run_command(
                ['checkout-index', '-a', '-f', '--prefix', location],
                show_stdout=False, cwd=temp_dir.path
            )

    def get_revision_sha(self, dest, rev):
        """
        Return (sha_or_none, is_branch), where sha_or_none is a commit hash
        if the revision names a remote branch or tag, otherwise None.

        Args:
          dest: the repository directory.
          rev: the revision name.
        """
        # Pass rev to pre-filter the list.
        output = self.run_command(['show-ref', rev], cwd=dest,
                                  show_stdout=False, on_returncode='ignore')
        refs = {}
        for line in output.strip().splitlines():
            try:
                sha, ref = line.split()
            except ValueError:
                # Include the offending line to simplify troubleshooting if
                # this error ever occurs.
                raise ValueError('unexpected show-ref line: {!r}'.format(line))

            refs[ref] = sha

        branch_ref = 'refs/remotes/origin/{}'.format(rev)
        tag_ref = 'refs/tags/{}'.format(rev)

        sha = refs.get(branch_ref)
        if sha is not None:
            return (sha, True)

        sha = refs.get(tag_ref)

        return (sha, False)

    def resolve_revision(self, dest, url, rev_options):
        """
        Resolve a revision to a new RevOptions object with the SHA1 of the
        branch, tag, or ref if found.

        Args:
          rev_options: a RevOptions object.
        """
        rev = rev_options.arg_rev
        sha, is_branch = self.get_revision_sha(dest, rev)

        if sha is not None:
            rev_options = rev_options.make_new(sha)
            rev_options.branch_name = rev if is_branch else None

            return rev_options

        # Do not show a warning for the common case of something that has
        # the form of a Git commit hash.
        if not looks_like_hash(rev):
            logger.warning(
                "Did not find branch or tag '%s', assuming revision or ref.",
                rev,
            )

        if not rev.startswith('refs/'):
            return rev_options

        # If it looks like a ref, we have to fetch it explicitly.
        self.run_command(
            ['fetch', '-q', url] + rev_options.to_args(),
            cwd=dest,
        )
        # Change the revision to the SHA of the ref we fetched
        sha = self.get_revision(dest, rev='FETCH_HEAD')
        rev_options = rev_options.make_new(sha)

        return rev_options

    def is_commit_id_equal(self, dest, name):
        """
        Return whether the current commit hash equals the given name.

        Args:
          dest: the repository directory.
          name: a string name.
        """
        if not name:
            # Then avoid an unnecessary subprocess call.
            return False

        return self.get_revision(dest) == name

    def fetch_new(self, dest, url, rev_options):
        rev_display = rev_options.to_display()
        logger.info(
            'Cloning %s%s to %s', redact_password_from_url(url),
            rev_display, display_path(dest),
        )
        self.run_command(['clone', '-q', url, dest])

        if rev_options.rev:
            # Then a specific revision was requested.
            rev_options = self.resolve_revision(dest, url, rev_options)
            branch_name = getattr(rev_options, 'branch_name', None)
            if branch_name is None:
                # Only do a checkout if the current commit id doesn't match
                # the requested revision.
                if not self.is_commit_id_equal(dest, rev_options.rev):
                    cmd_args = ['checkout', '-q'] + rev_options.to_args()
                    self.run_command(cmd_args, cwd=dest)
            elif self.get_current_branch(dest) != branch_name:
                # Then a specific branch was requested, and that branch
                # is not yet checked out.
                track_branch = 'origin/{}'.format(branch_name)
                cmd_args = [
                    'checkout', '-b', branch_name, '--track', track_branch,
                ]
                self.run_command(cmd_args, cwd=dest)

        #: repo may contain submodules
        self.update_submodules(dest)

    def switch(self, dest, url, rev_options):
        self.run_command(['config', 'remote.origin.url', url], cwd=dest)
        cmd_args = ['checkout', '-q'] + rev_options.to_args()
        self.run_command(cmd_args, cwd=dest)

        self.update_submodules(dest)

    def update(self, dest, url, rev_options):
        # First fetch changes from the default remote
        if self.get_git_version() >= parse_version('1.9.0'):
            # fetch tags in addition to everything else
            self.run_command(['fetch', '-q', '--tags'], cwd=dest)
        else:
            self.run_command(['fetch', '-q'], cwd=dest)
        # Then reset to wanted revision (maybe even origin/master)
        rev_options = self.resolve_revision(dest, url, rev_options)
        cmd_args = ['reset', '--hard', '-q'] + rev_options.to_args()
        self.run_command(cmd_args, cwd=dest)
        #: update submodules
        self.update_submodules(dest)

    @classmethod
    def get_remote_url(cls, location):
        """
        Return URL of the first remote encountered.

        Raises RemoteNotFoundError if the repository does not have a remote
        url configured.
        """
        # We need to pass 1 for extra_ok_returncodes since the command
        # exits with return code 1 if there are no matching lines.
        stdout = cls.run_command(
            ['config', '--get-regexp', r'remote\..*\.url'],
            extra_ok_returncodes=(1, ), show_stdout=False, cwd=location,
        )
        remotes = stdout.splitlines()
        try:
            found_remote = remotes[0]
        except IndexError:
            raise RemoteNotFoundError

        for remote in remotes:
            if remote.startswith('remote.origin.url '):
                found_remote = remote
                break
        url = found_remote.split(' ')[1]
        return url.strip()

    @classmethod
    def get_revision(cls, location, rev=None):
        if rev is None:
            rev = 'HEAD'
        current_rev = cls.run_command(
            ['rev-parse', rev], show_stdout=False, cwd=location,
        )
        return current_rev.strip()

    @classmethod
    def _get_subdirectory(cls, location):
        """Return the relative path of setup.py to the git repo root."""
        # find the repo root
        git_dir = cls.run_command(['rev-parse', '--git-dir'],
                                  show_stdout=False, cwd=location).strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.join(location, git_dir)
        root_dir = os.path.join(git_dir, '..')
        # find setup.py
        orig_location = location
        while not os.path.exists(os.path.join(location, 'setup.py')):
            last_location = location
            location = os.path.dirname(location)
            if location == last_location:
                # We've traversed up to the root of the filesystem without
                # finding setup.py
                logger.warning(
                    "Could not find setup.py for directory %s (tried all "
                    "parent directories)",
                    orig_location,
                )
                return None
        # relative path of setup.py to repo root
        if samefile(root_dir, location):
            return None
        return os.path.relpath(location, root_dir)

    @classmethod
    def get_src_requirement(cls, location, project_name):
        repo = cls.get_remote_url(location)
        if not repo.lower().startswith('git:'):
            repo = 'git+' + repo
        current_rev = cls.get_revision(location)
        subdir = cls._get_subdirectory(location)
        req = make_vcs_requirement_url(repo, current_rev, project_name,
                                       subdir=subdir)

        return req

    def get_url_rev_and_auth(self, url):
        """
        Prefixes stub URLs like 'user@hostname:user/repo.git' with 'ssh://'.
        That's required because although they use SSH they sometimes don't
        work with a ssh:// scheme (e.g. GitHub). But we need a scheme for
        parsing. Hence we remove it again afterwards and return it as a stub.
        """
        if '://' not in url:
            assert 'file:' not in url
            url = url.replace('git+', 'git+ssh://')
            url, rev, user_pass = super(Git, self).get_url_rev_and_auth(url)
            url = url.replace('ssh://', '')
        else:
            url, rev, user_pass = super(Git, self).get_url_rev_and_auth(url)

        return url, rev, user_pass

    def update_submodules(self, location):
        if not os.path.exists(os.path.join(location, '.gitmodules')):
            return
        self.run_command(
            ['submodule', 'update', '--init', '--recursive', '-q'],
            cwd=location,
        )

    @classmethod
    def controls_location(cls, location):
        if super(Git, cls).controls_location(location):
            return True
        try:
            r = cls.run_command(['rev-parse'],
                                cwd=location,
                                show_stdout=False,
                                on_returncode='ignore')
            return not r
        except BadCommand:
            logger.debug("could not determine if %s is under git control "
                         "because git is not available", location)
            return False


vcs.register(Git)
