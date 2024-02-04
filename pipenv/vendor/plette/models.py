# pylint: disable=missing-module-docstring,missing-class-docstring
# pylint: disable=missing-function-docstring
# pylint: disable=no-member
# pylint: disable=too-few-public-methods
import os
import re
import shlex


from dataclasses import dataclass

from typing import Optional, List, Union


class ValidationError(ValueError):
    pass


def remove_empty_values(d):
    #  Iterate over a copy of the dictionary
    for key, value in list(d.items()):
        # If the value is a dictionary, call the function recursively
        if isinstance(value, dict):
            remove_empty_values(value)
            # If the dictionary is empty, remove the key
            if not value:
                del d[key]
        # If the value is None or an empty string, remove the key
        elif value is None or value == '':
            del d[key]


class BaseModel:

    def __post_init__(self):
        """Run validation methods if declared.
        The validation method can be a simple check
        that raises ValueError or a transformation to
        the field value.
        The validation is performed by calling a function named:
            `validate_<field_name>(self, value) -> field.type`
        """
        for name, _ in self.__dataclass_fields__.items():
            if (method := getattr(self, f"validate_{name}", None)):
                setattr(self, name, method(getattr(self, name)))


@dataclass
class Hash(BaseModel):

    name: str
    value: str

    def validate_name(self, value):
        if not isinstance(value, str):
            raise ValueError("Hash.name must be a string")

        return value

    def validate_value(self, value):
        if not isinstance(value, str):
            raise ValueError("Hash.value must be a string")

        return value

    @classmethod
    def from_hash(cls, ins):
        """Interpolation to the hash result of `hashlib`.
        """
        return cls(name=ins.name, value=ins.hexdigest())

    @classmethod
    def from_dict(cls, value):
        """parse a depedency line and create an Hash object"""
        try:
            name, value = list(value.items())[0]
        except AttributeError:
            name, value = value.split(":", 1)
        return cls(name, value)

    @classmethod
    def from_line(cls, value):
        """parse a dependecy line and create a Hash object"""
        try:
            name, value = value.split(":", 1)
        except AttributeError:
            name, value = list(value.items())[0]
        return cls(name, value)

    def __eq__(self, other):
        if not isinstance(other, Hash):
            raise TypeError(f"cannot compare Hash with {type(other).__name__!r}")
        return self.value == other.value

    def as_line(self):
        return f"{self.name}:{self.value}"


@dataclass
class Source(BaseModel):
    """Information on a "simple" Python package index.

    This could be PyPI, or a self-hosted index server, etc. The server
    specified by the `url` attribute is expected to provide the "simple"
    package API.
    """
    name: str
    verify_ssl: bool
    url: str

    @property
    def url_expanded(self):
        return os.path.expandvars(self.url)

    def validate_verify_ssl(self, value):
        if not isinstance(value, bool):
            raise ValidationError("verify_ssl: must be of boolean type")
        return value


@dataclass
class PackageSpecfiers(BaseModel):

    extras: List[str]

    def validate_extras(self, value):
        if not isinstance(value, list):
            raise ValidationError("Extras must be a list")


@dataclass
class Package(BaseModel):

    version: Union[Optional[str],Optional[dict]] = "*"
    specifiers: Optional[PackageSpecfiers] = None
    editable: Optional[bool] = None
    extras: Optional[PackageSpecfiers] = None
    path: Optional[str] = None

    def validate_extras(self, value):
        if value is None:
            return value
        if not (isinstance(value, list) and all(isinstance(i, str) for i in value)):
            raise ValidationError("Extras must be a list or None")
        return value

    def validate_version(self, value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return value
        if value is None:
            return "*"

        raise ValidationError(f"Unknown type {type(value)} for version")


@dataclass(init=False)
class Script(BaseModel):

    script:  Union[str, List[str]]

    def __init__(self, script):

        if isinstance(script, str):
            script = shlex.split(script)
        self._parts = [script[0]]
        self._parts.extend(script[1:])

    def validate_script(self, value):
        if not (isinstance(value, str) or
                (isinstance(value, list) and all(isinstance(i, str) for i in value))
                ):
            raise ValueError("script must be a string or a list of strings")

    def __repr__(self):
        return f"Script({self._parts!r})"

    @property
    def command(self):
        return self._parts[0]

    @property
    def args(self):
        return self._parts[1:]

    def cmdify(self, extra_args=None):
        """Encode into a cmd-executable string.

        This re-implements CreateProcess's quoting logic to turn a list of
        arguments into one single string for the shell to interpret.

        * All double quotes are escaped with a backslash.
        * Existing backslashes before a quote are doubled, so they are all
          escaped properly.
        * Backslashes elsewhere are left as-is; cmd will interpret them
          literally.

        The result is then quoted into a pair of double quotes to be grouped.

        An argument is intentionally not quoted if it does not contain
        whitespaces. This is done to be compatible with Windows built-in
        commands that don't work well with quotes, e.g. everything with `echo`,
        and DOS-style (forward slash) switches.

        The intended use of this function is to pre-process an argument list
        before passing it into ``subprocess.Popen(..., shell=True)``.

        See also: https://docs.python.org/3/library/subprocess.html
        """
        parts = list(self._parts)
        if extra_args:
            parts.extend(extra_args)
        return " ".join(
            arg if not next(re.finditer(r'\s', arg), None)
            else '"{0}"'.format(re.sub(r'(\\*)"', r'\1\1\\"', arg))
            for arg in parts
        )


@dataclass
class PackageCollection(BaseModel):

    packages: List[Package]

    def validate_packages(self, value):
        if isinstance(value, dict):
            packages = {}
            for k, v in value.items():
                if isinstance(v, dict):
                    packages[k] = Package(**v)
                else:
                    packages[k] = Package(version=v)
            return packages
        return value


@dataclass
class ScriptCollection(BaseModel):
    scripts: List[Script]


@dataclass
class SourceCollection(BaseModel):

    sources: List[Source]

    def validate_sources(self, value):
        sources = []
        for v in value:
            if isinstance(v, dict):
                sources.append(Source(**v))
            elif isinstance(v, Source):
                sources.append(v)
        return sources

    def __iter__(self):
        return (d for d in self.sources)

    def __getitem__(self, key):
        if isinstance(key, slice):
            return SourceCollection(self.sources[key])
        if isinstance(key, int):
            src = self.sources[key]
            if isinstance(src, dict):
                return Source(**key)
            if isinstance(src, Source):
                return src
        raise TypeError(f"Unextepcted type {type(src)}")

    def __len__(self):
        return len(self.sources)

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            self.sources[key] = value
        elif isinstance(value, Source):
            self.sources.append(value)
        elif isinstance(value, list):
            self.sources.extend(value)
        else:
            raise TypeError(f"Unextepcted type {type(value)} for {value}")

    def __delitem__(self, key):
        del self.sources[key]


@dataclass
class Requires(BaseModel):
    python_version: Optional[str] = None
    python_full_version: Optional[str] = None


META_SECTIONS = {
    "hash": Hash,
    "requires": Requires,
    "sources": SourceCollection,
}


@dataclass
class PipfileSection(BaseModel):

    """
    Dummy pipfile validator that needs to be completed in a future PR
    Hint: many pipfile features are undocumented in pipenv/project.py
    """


@dataclass
class Meta(BaseModel):

    hash: Hash
    pipfile_spec: str
    requires: Requires
    sources: SourceCollection

    @classmethod
    def from_dict(cls, d: dict) -> "Meta":
        return cls(**{k.replace('-', '_'): v for k, v in d.items()})

    def validate_hash(self, value):
        try:
            return Hash(**value)
        except TypeError:
            return Hash.from_line(value)

    def validate_requires(self, value):
        return Requires(value)

    def validate_sources(self, value):
        return SourceCollection(value)

    def validate_pipfile_spec(self, value):
        if int(value) != 6:
            raise ValueError('Only pipefile-spec version 6 is supported')
        return value


@dataclass
class Pipenv(BaseModel):
    """Represent the [pipenv] section in Pipfile"""
    allow_prereleases: Optional[bool] = False
    install_search_all_sources: Optional[bool] = True

    def validate_allow_prereleases(self, value):
        if not isinstance(value, bool):
            raise ValidationError('allow_prereleases must be a boolean')
        return value

    def validate_install_search_all_sources(self, value):
        if not isinstance(value, bool):
            raise ValidationError('install_search_all_sources must be a boolean')

        return value
