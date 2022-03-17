from pipenv.pep508checker import lookup

specifiers = [k for k in lookup.keys()]  # TODO Is this used?

# List of version control systems we support.
VCS_LIST = ("git", "svn", "hg", "bzr")
SCHEME_LIST = ("http://", "https://", "ftp://", "ftps://", "file://")
