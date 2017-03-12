from __future__ import unicode_literals
import re
from pkg_resources import Requirement as Req

from .vcs import VCS, VCS_SCHEMES


URI_REGEX = re.compile(
    r'^(?P<scheme>https?|file|ftps?)://(?P<path>[^#]+)'
    r'(#egg=(?P<name>[^&]+))?$'
)

VCS_REGEX = re.compile(
    r'^(?P<scheme>{0})://'.format(r'|'.join(
        [scheme.replace('+', r'\+') for scheme in VCS_SCHEMES])) +
    r'((?P<login>[^/@]+)@)?'
    r'(?P<path>[^#@]+)'
    r'(@(?P<revision>[^#]+))?'
    r'(#egg=(?P<name>[^&]+))?$'
)

# This matches just about everyting
LOCAL_REGEX = re.compile(
    r'^((?P<scheme>file)://)?'
    r'(?P<path>[^#]+)'
    r'(#egg=(?P<name>[^&]+))?$'
)


class Requirement(object):
    """
    Represents a single requirement

    Typically instances of this class are created with ``Requirement.parse``.
    For local file requirements, there's no verification that the file
    exists. This class attempts to be *dict-like*.

    See: http://www.pip-installer.org/en/latest/logic.html

    **Members**:

    * ``line`` - the actual requirement line being parsed
    * ``editable`` - a boolean whether this requirement is "editable"
    * ``local_file`` - a boolean whether this requirement is a local file/path
    * ``specifier`` - a boolean whether this requirement used a requirement
      specifier (eg. "django>=1.5" or "requirements")
    * ``vcs`` - a string specifying the version control system
    * ``revision`` - a version control system specifier
    * ``name`` - the name of the requirement
    * ``uri`` - the URI if this requirement was specified by URI
    * ``path`` - the local path to the requirement
    * ``extras`` - a list of extras for this requirement
      (eg. "mymodule[extra1, extra2]")
    * ``specs`` - a list of specs for this requirement
      (eg. "mymodule>1.5,<1.6" => [('>', '1.5'), ('<', '1.6')])
    """

    def __init__(self, line):
        # Do not call this private method
        self.line = line
        self.editable = False
        self.local_file = False
        self.specifier = False
        self.vcs = None
        self.name = None
        self.uri = None
        self.path = None
        self.revision = None
        self.extras = []
        self.specs = []

    def __repr__(self):
        return '<Requirement: "{0}">'.format(self.line)

    def __getitem__(self, key):
        return getattr(self, key)

    def keys(self):
        return self.__dict__.keys()

    @classmethod
    def parse_editable(cls, line):
        """
        Parses a Requirement from an "editable" requirement which is either
        a local project path or a VCS project URI.

        See: pip/req.py:from_editable()

        :param line: an "editable" requirement
        :returns: a Requirement instance for the given line
        :raises: ValueError on an invalid requirement
        """

        req = cls('-e {0}'.format(line))
        req.editable = True
        vcs_match = VCS_REGEX.match(line)
        local_match = LOCAL_REGEX.match(line)

        if vcs_match is not None:
            groups = vcs_match.groupdict()
            req.uri = '{scheme}://{path}'.format(**groups)
            req.revision = groups['revision']
            req.name = groups['name']
            for vcs in VCS:
                if req.uri.startswith(vcs):
                    req.vcs = vcs
        else:
            assert local_match is not None, 'This should match everything'
            groups = local_match.groupdict()
            req.local_file = True
            req.name = groups['name']
            req.path = groups['path']

        return req

    @classmethod
    def parse_line(cls, line):
        """
        Parses a Requirement from a non-editable requirement.

        See: pip/req.py:from_line()

        :param line: a "non-editable" requirement
        :returns: a Requirement instance for the given line
        :raises: ValueError on an invalid requirement
        """

        req = cls(line)

        vcs_match = VCS_REGEX.match(line)
        uri_match = URI_REGEX.match(line)
        local_match = LOCAL_REGEX.match(line)

        if vcs_match is not None:
            groups = vcs_match.groupdict()
            req.uri = '{scheme}://{path}'.format(**groups)
            req.revision = groups['revision']
            req.name = groups['name']
            for vcs in VCS:
                if req.uri.startswith(vcs):
                    req.vcs = vcs
        elif uri_match is not None:
            groups = uri_match.groupdict()
            req.uri = '{scheme}://{path}'.format(**groups)
            req.name = groups['name']
            if groups['scheme'] == 'file':
                req.local_file = True
        elif '#egg=' in line:
            # Assume a local file match
            assert local_match is not None, 'This should match everything'
            groups = local_match.groupdict()
            req.local_file = True
            req.name = groups['name']
            req.path = groups['path']
        else:
            # This is a requirement specifier.
            # Delegate to pkg_resources and hope for the best
            req.specifier = True
            pkg_req = Req.parse(line)
            req.name = pkg_req.unsafe_name
            req.extras = list(pkg_req.extras)
            req.specs = pkg_req.specs
        return req

    @classmethod
    def parse(cls, line):
        """
        Parses a Requirement from a line of a requirement file.

        :param line: a line of a requirement file
        :returns: a Requirement instance for the given line
        :raises: ValueError on an invalid requirement
        """

        if line.startswith('-e') or line.startswith('--editable'):
            # Editable installs are either a local project path
            # or a VCS project URI
            return cls.parse_editable(
                re.sub(r'^(-e|--editable=?)\s*', '', line))

        return cls.parse_line(line)
