from typing import Dict, Optional, Text, Tuple, TypeVar, Union
from urllib.parse import quote
from urllib.parse import unquote as url_unquote
from urllib.parse import unquote_plus

from pipenv.patched.pip._internal.models.link import Link
from pipenv.patched.pip._internal.req.constructors import _strip_extras
from pipenv.patched.pip._vendor.urllib3.util import parse_url as urllib3_parse
from pipenv.patched.pip._vendor.urllib3.util.url import Url
from pipenv.vendor.pydantic import Field

from ..environment import MYPY_RUNNING
from ..utils import is_installable_file
from .common import ReqLibBaseModel
from .utils import DIRECT_URL_RE, extras_to_string, parse_extras_str, split_ref_from_uri

if MYPY_RUNNING:

    _T = TypeVar("_T")
    STRING_TYPE = Union[bytes, str, Text]
    S = TypeVar("S", bytes, str, Text)


def _get_parsed_url(url) -> Url:
    """This is a stand-in function for `urllib3.util.parse_url`

    The original function doesn't handle special characters very well, this simply splits
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


class URI(ReqLibBaseModel):
    host: Optional[str] = Field(...)
    scheme: Optional[str] = Field(
        "https", description="The URI Scheme, e.g. `salesforce`"
    )
    port: Optional[int] = Field(
        None, description="The numeric port of the url if specified"
    )
    path: Optional[str] = Field("", description="The url path, e.g. `/path/to/endpoint`")
    query: Optional[str] = Field(
        "", description="Query parameters, e.g. `?variable=value...`"
    )
    fragment: Optional[str] = Field(
        "", description="URL Fragments, e.g. `#fragment=value`"
    )
    subdirectory: Optional[str] = Field(
        "", description="Subdirectory fragment, e.g. `&subdirectory=blah...`"
    )
    ref: Optional[str] = Field("", description="VCS ref this URI points at, if available")
    username: Optional[str] = Field(
        "", description="The username if provided, parsed from `user:password@hostname`"
    )
    password: Optional[str] = Field(
        "", description="Password parsed from `user:password@hostname`", repr=False
    )
    query_dict: Optional[Dict] = Field(default_factory=dict)
    name: Optional[str] = Field(
        "",
        description="The name of the specified package in case it is a VCS URI with an egg fragment",
    )
    extras: Optional[Tuple] = Field(default_factory=tuple)
    is_direct_url: Optional[bool] = Field(False)
    is_implicit_ssh: Optional[bool] = Field(False)
    auth: Optional[str] = None
    _fragment_dict: Optional[Dict] = Field(default_factory=dict)
    _username_is_quoted: Optional[bool] = False
    _password_is_quoted: Optional[bool] = False

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = True
        # keep_untouched = (cached_property,)

    def __init__(self, **data):
        super().__init__(**data)
        self._parse_auth()
        self._parse_query()
        self._parse_fragment()

    def _parse_query(self) -> None:
        query = self.query if self.query is not None else ""
        query_dict = dict()
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
        query_dict.update(query_items)
        self.query_dict = query_dict
        self.subdirectory = subdirectory
        self.query = query

    def _parse_fragment(self) -> None:
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
                from .utils import parse_extras_str

                name, stripped_extras = _strip_extras(val)
                if stripped_extras:
                    extras = tuple(parse_extras_str(stripped_extras))
            elif key == "subdirectory":
                subdirectory = val
        self.name = name
        self.extras = extras
        self.subdirectory = subdirectory
        self.fragment = fragment
        self._fragment_dict = fragment_items

    def _parse_auth(self) -> None:
        if self.auth:
            username, _, password = self.auth.partition(":")
            username_is_quoted, password_is_quoted = False, False
            quoted_username, quoted_password = "", ""
            if password:
                quoted_password = quote(password)
                password_is_quoted = quoted_password != password
            if username:
                quoted_username = quote(username)
                username_is_quoted = quoted_username != username
            self.username = quoted_username
            self.password = quoted_password
            self._username_is_quoted = username_is_quoted
            self._password_is_quoted = password_is_quoted

    def get_password(self, unquote=False, include_token=True) -> str:
        password = self.password if self.password else ""
        if password and unquote and self._password_is_quoted:
            password = url_unquote(password)
        return password

    def get_username(self, unquote=False) -> str:
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
        maybe_auth = None
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
    def parse(cls, url) -> "URI":
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
        return cls(**parsed_dict)

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
        link = Link(self.to_string(escape_password=False, strip_ssh=False, direct=False))
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
        name, extras = _strip_extras(name_with_extras)
        if extras:
            parsed_extras = parsed_extras + tuple(parse_extras_str(extras))
        if parsed_dict["fragment"] is not None:
            fragment = "{0}".format(parsed_dict["fragment"])
            if fragment.startswith("egg="):
                _, _, fragment_part = fragment.partition("=")
                fragment_name, fragment_extras = _strip_extras(fragment_part)
                name = name if name else fragment_name
                if fragment_extras:
                    parsed_extras = parsed_extras + tuple(
                        parse_extras_str(fragment_extras)
                    )
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
