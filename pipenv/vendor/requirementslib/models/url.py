# -*- coding=utf-8 -*-
from __future__ import absolute_import, print_function

import attr
import pip_shims.shims
from orderedmultidict import omdict
from six.moves.urllib.parse import quote, unquote_plus, unquote as url_unquote
from urllib3 import util as urllib3_util
from urllib3.util import parse_url as urllib3_parse
from urllib3.util.url import Url

from ..environment import MYPY_RUNNING
from ..utils import is_installable_file
from .utils import extras_to_string, parse_extras

if MYPY_RUNNING:
    from typing import Dict, List, Optional, Text, Tuple, TypeVar, Union
    from pip_shims.shims import Link
    from vistir.compat import Path

    _T = TypeVar("_T")
    STRING_TYPE = Union[bytes, str, Text]
    S = TypeVar("S", bytes, str, Text)


def _get_parsed_url(url):
    # type: (S) -> Url
    """This is a stand-in function for `urllib3.util.parse_url`

    The orignal function doesn't handle special characters very well, this simply splits
    out the authentication section, creates the parsed url, then puts the authentication
    section back in, bypassing validation.

    :return: The new, parsed URL object
    :rtype: :class:`~urllib3.util.url.Url`
    """

    try:
        parsed = urllib3_parse(url)
    except ValueError:
        scheme, _, url = url.partition("://")
        auth, _, url = url.rpartition("@")
        url = "{scheme}://{url}".format(scheme=scheme, url=url)
        parsed = urllib3_parse(url)._replace(auth=auth)
    if parsed.auth:
        return parsed._replace(auth=url_unquote(parsed.auth))
    return parsed


def remove_password_from_url(url):
    # type: (S) -> S
    """Given a url, remove the password and insert 4 dashes.

    :param url: The url to replace the authentication in
    :type url: S
    :return: The new URL without authentication
    :rtype: S
    """

    parsed = _get_parsed_url(url)
    if parsed.auth:
        auth, _, _ = parsed.auth.partition(":")
        return parsed._replace(auth="{auth}:----".format(auth=auth)).url
    return parsed.url


@attr.s(hash=True)
class URI(object):
    #: The target hostname, e.g. `amazon.com`
    host = attr.ib(type=str)
    #: The URI Scheme, e.g. `salesforce`
    scheme = attr.ib(default="https", type=str)
    #: The numeric port of the url if specified
    port = attr.ib(default=None, type=int)
    #: The url path, e.g. `/path/to/endpoint`
    path = attr.ib(default="", type=str)
    #: Query parameters, e.g. `?variable=value...`
    query = attr.ib(default="", type=str)
    #: URL Fragments, e.g. `#fragment=value`
    fragment = attr.ib(default="", type=str)
    #: Subdirectory fragment, e.g. `&subdirectory=blah...`
    subdirectory = attr.ib(default="", type=str)
    #: VCS ref this URI points at, if available
    ref = attr.ib(default="", type=str)
    #: The username if provided, parsed from `user:password@hostname`
    username = attr.ib(default="", type=str)
    #: Password parsed from `user:password@hostname`
    password = attr.ib(default="", type=str, repr=False)
    #: An orderedmultidict representing query fragments
    query_dict = attr.ib(factory=omdict, type=omdict)
    #: The name of the specified package in case it is a VCS URI with an egg fragment
    name = attr.ib(default="", type=str)
    #: Any extras requested from the requirement
    extras = attr.ib(factory=tuple, type=tuple)
    #: Whether the url was parsed as a direct pep508-style URL
    is_direct_url = attr.ib(default=False, type=bool)
    #: Whether the url was an implicit `git+ssh` url (passed as `git+git@`)
    is_implicit_ssh = attr.ib(default=False, type=bool)
    _auth = attr.ib(default=None, type=str, repr=False)
    _fragment_dict = attr.ib(factory=dict, type=dict)
    _username_is_quoted = attr.ib(type=bool, default=False)
    _password_is_quoted = attr.ib(type=bool, default=False)

    def _parse_query(self):
        # type: () -> URI
        query = self.query if self.query is not None else ""
        query_dict = omdict()
        queries = query.split("&")
        query_items = []
        subdirectory = self.subdirectory if self.subdirectory else None
        for q in queries:
            key, _, val = q.partition("=")
            val = unquote_plus(val)
            if key == "subdirectory" and not subdirectory:
                subdirectory = val
            else:
                query_items.append((key, val))
        query_dict.load(query_items)
        return attr.evolve(
            self, query_dict=query_dict, subdirectory=subdirectory, query=query
        )

    def _parse_fragment(self):
        # type: () -> URI
        subdirectory = self.subdirectory if self.subdirectory else ""
        fragment = self.fragment if self.fragment else ""
        if self.fragment is None:
            return self
        fragments = self.fragment.split("&")
        fragment_items = {}
        name = self.name if self.name else ""
        extras = self.extras
        for q in fragments:
            key, _, val = q.partition("=")
            val = unquote_plus(val)
            fragment_items[key] = val
            if key == "egg":
                from .utils import parse_extras

                name, stripped_extras = pip_shims.shims._strip_extras(val)
                if stripped_extras:
                    extras = tuple(parse_extras(stripped_extras))
            elif key == "subdirectory":
                subdirectory = val
        return attr.evolve(
            self,
            fragment_dict=fragment_items,
            subdirectory=subdirectory,
            fragment=fragment,
            extras=extras,
            name=name,
        )

    def _parse_auth(self):
        # type: () -> URI
        if self._auth:
            username, _, password = self._auth.partition(":")
            username_is_quoted, password_is_quoted = False, False
            quoted_username, quoted_password = "", ""
            if password:
                quoted_password = quote(password)
                password_is_quoted = quoted_password != password
            if username:
                quoted_username = quote(username)
                username_is_quoted = quoted_username != username
            return attr.evolve(
                self,
                username=quoted_username,
                password=quoted_password,
                username_is_quoted=username_is_quoted,
                password_is_quoted=password_is_quoted,
            )
        return self

    def get_password(self, unquote=False, include_token=True):
        # type: (bool, bool) -> str
        password = self.password if self.password else ""
        if password and unquote and self._password_is_quoted:
            password = url_unquote(password)
        return password

    def get_username(self, unquote=False):
        # type: (bool) -> str
        username = self.username if self.username else ""
        if username and unquote and self._username_is_quoted:
            username = url_unquote(username)
        return username

    @staticmethod
    def parse_subdirectory(url_part):
        # type: (str) -> Tuple[str, Optional[str]]
        subdir = None
        if "&subdirectory" in url_part:
            url_part, _, subdir = url_part.rpartition("&")
            if "#egg=" not in url_part:
                subdir = "#{0}".format(subdir.strip())
            else:
                subdir = "&{0}".format(subdir.strip())
        return url_part.strip(), subdir

    @classmethod
    def get_parsed_url(cls, url):
        # if there is a "#" in the auth section, this could break url parsing
        parsed_url = _get_parsed_url(url)
        if "@" in url and "#" in url:
            scheme = "{0}://".format(parsed_url.scheme)
            if parsed_url.scheme == "file":
                scheme = "{0}/".format(scheme)
            url_without_scheme = url.replace(scheme, "")
            maybe_auth, _, maybe_url = url_without_scheme.partition("@")
            if "#" in maybe_auth and (not parsed_url.host or "." not in parsed_url.host):
                new_parsed_url = _get_parsed_url("{0}{1}".format(scheme, maybe_url))
                new_parsed_url = new_parsed_url._replace(auth=maybe_auth)
                return new_parsed_url
        return parsed_url

    @classmethod
    def parse(cls, url):
        # type: (S) -> URI
        from .utils import DIRECT_URL_RE, split_ref_from_uri

        is_direct_url = False
        name_with_extras = None
        is_implicit_ssh = url.strip().startswith("git+git@")
        if is_implicit_ssh:
            from ..utils import add_ssh_scheme_to_git_uri

            url = add_ssh_scheme_to_git_uri(url)
        direct_match = DIRECT_URL_RE.match(url)
        if direct_match is not None:
            is_direct_url = True
            name_with_extras, _, url = url.partition("@")
            name_with_extras = name_with_extras.strip()
        url, ref = split_ref_from_uri(url.strip())
        if "file:/" in url and "file:///" not in url:
            url = url.replace("file:/", "file:///")
        parsed = cls.get_parsed_url(url)
        # if there is a "#" in the auth section, this could break url parsing
        if not (parsed.scheme and parsed.host):
            # check if this is a file uri
            if not (
                parsed.scheme
                and parsed.path
                and (parsed.scheme == "file" or parsed.scheme.endswith("+file"))
            ):
                raise ValueError("Failed parsing URL {0!r} - Not a valid url".format(url))
        parsed_dict = dict(parsed._asdict()).copy()
        parsed_dict["is_direct_url"] = is_direct_url
        parsed_dict["is_implicit_ssh"] = is_implicit_ssh
        parsed_dict.update(
            **update_url_name_and_fragment(name_with_extras, ref, parsed_dict)
        )  # type: ignore
        return cls(**parsed_dict)._parse_auth()._parse_query()._parse_fragment()

    def to_string(
        self,
        escape_password=True,  # type: bool
        unquote=True,  # type: bool
        direct=None,  # type: Optional[bool]
        strip_ssh=False,  # type: bool
        strip_ref=False,  # type: bool
        strip_name=False,  # type: bool
        strip_subdir=False,  # type: bool
    ):
        # type: (...) -> str
        """Converts the current URI to a string, unquoting or escaping the
        password as needed.

        :param escape_password: Whether to replace password with ``----``, default True
        :param escape_password: bool, optional
        :param unquote: Whether to unquote url-escapes in the password, default False
        :param unquote: bool, optional
        :param bool direct: Whether to format as a direct URL
        :param bool strip_ssh: Whether to strip the SSH scheme from the url (git only)
        :param bool strip_ref: Whether to drop the VCS ref (if present)
        :param bool strip_name: Whether to drop the name and extras (if present)
        :param bool strip_subdir: Whether to drop the subdirectory (if present)
        :return: The reconstructed string representing the URI
        :rtype: str
        """

        if direct is None:
            direct = self.is_direct_url
        if escape_password:
            password = "----" if self.password else ""
            if password:
                username = self.get_username(unquote=unquote)
            elif self.username:
                username = "----"
            else:
                username = ""
        else:
            password = self.get_password(unquote=unquote)
            username = self.get_username(unquote=unquote)
        auth = ""
        if username:
            if password:
                auth = "{username}:{password}@".format(
                    password=password, username=username
                )
            else:
                auth = "{username}@".format(username=username)
        query = ""
        if self.query:
            query = "{query}?{self.query}".format(query=query, self=self)
        subdir_prefix = "#"
        if not direct:
            if self.name and not strip_name:
                fragment = "#egg={self.name_with_extras}".format(self=self)
                subdir_prefix = "&"
            elif not strip_name and (
                self.extras and self.scheme and self.scheme.startswith("file")
            ):
                from .utils import extras_to_string

                fragment = extras_to_string(self.extras)
            else:
                fragment = ""
            query = "{query}{fragment}".format(query=query, fragment=fragment)
        if self.subdirectory and not strip_subdir:
            query = "{query}{subdir_prefix}subdirectory={self.subdirectory}".format(
                query=query, subdir_prefix=subdir_prefix, self=self
            )
        host_port_path = self.get_host_port_path(strip_ref=strip_ref)
        url = "{self.scheme}://{auth}{host_port_path}{query}".format(
            self=self, auth=auth, host_port_path=host_port_path, query=query
        )
        if strip_ssh:
            from ..utils import strip_ssh_from_git_uri

            url = strip_ssh_from_git_uri(url)
        if self.name and direct and not strip_name:
            return "{self.name_with_extras}@ {url}".format(self=self, url=url)
        return url

    def get_host_port_path(self, strip_ref=False):
        # type: (bool) -> str
        host = self.host if self.host else ""
        if self.port is not None:
            host = "{host}:{self.port!s}".format(host=host, self=self)
        path = "{self.path}".format(self=self) if self.path else ""
        if self.ref and not strip_ref:
            path = "{path}@{self.ref}".format(path=path, self=self)
        return "{host}{path}".format(host=host, path=path)

    @property
    def hidden_auth(self):
        # type: () -> str
        auth = ""
        if self.username and self.password:
            password = "****"
            username = self.get_username(unquote=True)
            auth = "{username}:{password}".format(username=username, password=password)
        elif self.username and not self.password:
            auth = "****"
        return auth

    @property
    def name_with_extras(self):
        # type: () -> str
        from .utils import extras_to_string

        if not self.name:
            return ""
        extras = extras_to_string(self.extras)
        return "{self.name}{extras}".format(self=self, extras=extras)

    @property
    def as_link(self):
        # type: () -> Link
        link = pip_shims.shims.Link(
            self.to_string(escape_password=False, strip_ssh=False, direct=False)
        )
        return link

    @property
    def bare_url(self):
        # type: () -> str
        return self.to_string(
            escape_password=False,
            strip_ssh=self.is_implicit_ssh,
            direct=False,
            strip_name=True,
            strip_ref=True,
            strip_subdir=True,
        )

    @property
    def url_without_fragment_or_ref(self):
        # type: () -> str
        return self.to_string(
            escape_password=False,
            strip_ssh=self.is_implicit_ssh,
            direct=False,
            strip_name=True,
            strip_ref=True,
        )

    @property
    def url_without_fragment(self):
        # type: () -> str
        return self.to_string(
            escape_password=False,
            strip_ssh=self.is_implicit_ssh,
            direct=False,
            strip_name=True,
        )

    @property
    def url_without_ref(self):
        # type: () -> str
        return self.to_string(
            escape_password=False,
            strip_ssh=self.is_implicit_ssh,
            direct=False,
            strip_ref=True,
        )

    @property
    def base_url(self):
        # type: () -> str
        return self.to_string(
            escape_password=False,
            strip_ssh=self.is_implicit_ssh,
            direct=False,
            unquote=False,
        )

    @property
    def full_url(self):
        # type: () -> str
        return self.to_string(escape_password=False, strip_ssh=False, direct=False)

    @property
    def secret(self):
        # type: () -> str
        return self.full_url

    @property
    def safe_string(self):
        # type: () -> str
        return self.to_string(escape_password=True, unquote=True)

    @property
    def unsafe_string(self):
        # type: () -> str
        return self.to_string(escape_password=False, unquote=True)

    @property
    def uri_escape(self):
        # type: () -> str
        return self.to_string(escape_password=False, unquote=False)

    @property
    def is_installable(self):
        # type: () -> bool
        return self.is_file_url and is_installable_file(self.bare_url)

    @property
    def is_vcs(self):
        # type: () -> bool
        from ..utils import VCS_SCHEMES

        return self.scheme in VCS_SCHEMES

    @property
    def is_file_url(self):
        # type: () -> bool
        return all([self.scheme, self.scheme == "file"])

    def __str__(self):
        # type: () -> str
        return self.to_string(escape_password=True, unquote=True)


def update_url_name_and_fragment(name_with_extras, ref, parsed_dict):
    # type: (Optional[str], Optional[str], Dict[str, Optional[str]]) -> Dict[str, Optional[str]]
    if name_with_extras:
        fragment = ""  # type: Optional[str]
        parsed_extras = ()
        name, extras = pip_shims.shims._strip_extras(name_with_extras)
        if extras:
            parsed_extras = parsed_extras + tuple(parse_extras(extras))
        if parsed_dict["fragment"] is not None:
            fragment = "{0}".format(parsed_dict["fragment"])
            if fragment.startswith("egg="):
                _, _, fragment_part = fragment.partition("=")
                fragment_name, fragment_extras = pip_shims.shims._strip_extras(
                    fragment_part
                )
                name = name if name else fragment_name
                if fragment_extras:
                    parsed_extras = parsed_extras + tuple(parse_extras(fragment_extras))
                name_with_extras = "{0}{1}".format(name, extras_to_string(parsed_extras))
        elif (
            parsed_dict.get("path") is not None and "&subdirectory" in parsed_dict["path"]
        ):
            path, fragment = URI.parse_subdirectory(parsed_dict["path"])  # type: ignore
            parsed_dict["path"] = path
        elif ref is not None and "&subdirectory" in ref:
            ref, fragment = URI.parse_subdirectory(ref)
        parsed_dict["name"] = name
        parsed_dict["extras"] = parsed_extras
    if ref:
        parsed_dict["ref"] = ref.strip()
    return parsed_dict
