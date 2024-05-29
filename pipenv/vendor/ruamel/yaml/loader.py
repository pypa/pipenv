
from __future__ import annotations

from pipenv.vendor.ruamel.yaml.reader import Reader
from pipenv.vendor.ruamel.yaml.scanner import Scanner, RoundTripScanner
from pipenv.vendor.ruamel.yaml.parser import Parser, RoundTripParser
from pipenv.vendor.ruamel.yaml.composer import Composer
from pipenv.vendor.ruamel.yaml.constructor import (
    BaseConstructor,
    SafeConstructor,
    Constructor,
    RoundTripConstructor,
)
from pipenv.vendor.ruamel.yaml.resolver import VersionedResolver

if False:  # MYPY
    from typing import Any, Dict, List, Union, Optional  # NOQA
    from pipenv.vendor.ruamel.yaml.compat import StreamTextType, VersionType  # NOQA

__all__ = ['BaseLoader', 'SafeLoader', 'Loader', 'RoundTripLoader']


class BaseLoader(Reader, Scanner, Parser, Composer, BaseConstructor, VersionedResolver):
    def __init__(
        self,
        stream: StreamTextType,
        version: Optional[VersionType] = None,
        preserve_quotes: Optional[bool] = None,
    ) -> None:
        self.comment_handling = None
        Reader.__init__(self, stream, loader=self)
        Scanner.__init__(self, loader=self)
        Parser.__init__(self, loader=self)
        Composer.__init__(self, loader=self)
        BaseConstructor.__init__(self, loader=self)
        VersionedResolver.__init__(self, version, loader=self)


class SafeLoader(Reader, Scanner, Parser, Composer, SafeConstructor, VersionedResolver):
    def __init__(
        self,
        stream: StreamTextType,
        version: Optional[VersionType] = None,
        preserve_quotes: Optional[bool] = None,
    ) -> None:
        self.comment_handling = None
        Reader.__init__(self, stream, loader=self)
        Scanner.__init__(self, loader=self)
        Parser.__init__(self, loader=self)
        Composer.__init__(self, loader=self)
        SafeConstructor.__init__(self, loader=self)
        VersionedResolver.__init__(self, version, loader=self)


class Loader(Reader, Scanner, Parser, Composer, Constructor, VersionedResolver):
    def __init__(
        self,
        stream: StreamTextType,
        version: Optional[VersionType] = None,
        preserve_quotes: Optional[bool] = None,
    ) -> None:
        self.comment_handling = None
        Reader.__init__(self, stream, loader=self)
        Scanner.__init__(self, loader=self)
        Parser.__init__(self, loader=self)
        Composer.__init__(self, loader=self)
        Constructor.__init__(self, loader=self)
        VersionedResolver.__init__(self, version, loader=self)


class RoundTripLoader(
    Reader,
    RoundTripScanner,
    RoundTripParser,
    Composer,
    RoundTripConstructor,
    VersionedResolver,
):
    def __init__(
        self,
        stream: StreamTextType,
        version: Optional[VersionType] = None,
        preserve_quotes: Optional[bool] = None,
    ) -> None:
        # self.reader = Reader.__init__(self, stream)
        self.comment_handling = None  # issue 385
        Reader.__init__(self, stream, loader=self)
        RoundTripScanner.__init__(self, loader=self)
        RoundTripParser.__init__(self, loader=self)
        Composer.__init__(self, loader=self)
        RoundTripConstructor.__init__(self, preserve_quotes=preserve_quotes, loader=self)
        VersionedResolver.__init__(self, version, loader=self)
