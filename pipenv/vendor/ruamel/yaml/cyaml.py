# coding: utf-8

from _ruamel_yaml import CParser, CEmitter  # type: ignore

from pipenv.vendor.ruamel.yaml.constructor import Constructor, BaseConstructor, SafeConstructor
from pipenv.vendor.ruamel.yaml.representer import Representer, SafeRepresenter, BaseRepresenter
from pipenv.vendor.ruamel.yaml.resolver import Resolver, BaseResolver


from typing import Any, Union, Optional  # NOQA
from pipenv.vendor.ruamel.yaml.compat import StreamTextType, StreamType, VersionType  # NOQA

__all__ = ['CBaseLoader', 'CSafeLoader', 'CLoader', 'CBaseDumper', 'CSafeDumper', 'CDumper']


# this includes some hacks to solve the  usage of resolver by lower level
# parts of the parser


class CBaseLoader(CParser, BaseConstructor, BaseResolver):  # type: ignore
    def __init__(
        self,
        stream: StreamTextType,
        version: Optional[VersionType] = None,
        preserve_quotes: Optional[bool] = None,
    ) -> None:
        CParser.__init__(self, stream)
        self._parser = self._composer = self
        BaseConstructor.__init__(self, loader=self)
        BaseResolver.__init__(self, loadumper=self)
        # self.descend_resolver = self._resolver.descend_resolver
        # self.ascend_resolver = self._resolver.ascend_resolver
        # self.resolve = self._resolver.resolve


class CSafeLoader(CParser, SafeConstructor, Resolver):  # type: ignore
    def __init__(
        self,
        stream: StreamTextType,
        version: Optional[VersionType] = None,
        preserve_quotes: Optional[bool] = None,
    ) -> None:
        CParser.__init__(self, stream)
        self._parser = self._composer = self
        SafeConstructor.__init__(self, loader=self)
        Resolver.__init__(self, loadumper=self)
        # self.descend_resolver = self._resolver.descend_resolver
        # self.ascend_resolver = self._resolver.ascend_resolver
        # self.resolve = self._resolver.resolve


class CLoader(CParser, Constructor, Resolver):  # type: ignore
    def __init__(
        self,
        stream: StreamTextType,
        version: Optional[VersionType] = None,
        preserve_quotes: Optional[bool] = None,
    ) -> None:
        CParser.__init__(self, stream)
        self._parser = self._composer = self
        Constructor.__init__(self, loader=self)
        Resolver.__init__(self, loadumper=self)
        # self.descend_resolver = self._resolver.descend_resolver
        # self.ascend_resolver = self._resolver.ascend_resolver
        # self.resolve = self._resolver.resolve


class CBaseDumper(CEmitter, BaseRepresenter, BaseResolver):  # type: ignore
    def __init__(
        self: StreamType,
        stream: Any,
        default_style: Any = None,
        default_flow_style: Any = None,
        canonical: Optional[bool] = None,
        indent: Optional[int] = None,
        width: Optional[int] = None,
        allow_unicode: Optional[bool] = None,
        line_break: Any = None,
        encoding: Any = None,
        explicit_start: Optional[bool] = None,
        explicit_end: Optional[bool] = None,
        version: Any = None,
        tags: Any = None,
        block_seq_indent: Any = None,
        top_level_colon_align: Any = None,
        prefix_colon: Any = None,
    ) -> None:
        # NOQA
        CEmitter.__init__(
            self,
            stream,
            canonical=canonical,
            indent=indent,
            width=width,
            encoding=encoding,
            allow_unicode=allow_unicode,
            line_break=line_break,
            explicit_start=explicit_start,
            explicit_end=explicit_end,
            version=version,
            tags=tags,
        )
        self._emitter = self._serializer = self._representer = self
        BaseRepresenter.__init__(
            self,
            default_style=default_style,
            default_flow_style=default_flow_style,
            dumper=self,
        )
        BaseResolver.__init__(self, loadumper=self)


class CSafeDumper(CEmitter, SafeRepresenter, Resolver):  # type: ignore
    def __init__(
        self: StreamType,
        stream: Any,
        default_style: Any = None,
        default_flow_style: Any = None,
        canonical: Optional[bool] = None,
        indent: Optional[int] = None,
        width: Optional[int] = None,
        allow_unicode: Optional[bool] = None,
        line_break: Any = None,
        encoding: Any = None,
        explicit_start: Optional[bool] = None,
        explicit_end: Optional[bool] = None,
        version: Any = None,
        tags: Any = None,
        block_seq_indent: Any = None,
        top_level_colon_align: Any = None,
        prefix_colon: Any = None,
    ) -> None:
        # NOQA
        self._emitter = self._serializer = self._representer = self
        CEmitter.__init__(
            self,
            stream,
            canonical=canonical,
            indent=indent,
            width=width,
            encoding=encoding,
            allow_unicode=allow_unicode,
            line_break=line_break,
            explicit_start=explicit_start,
            explicit_end=explicit_end,
            version=version,
            tags=tags,
        )
        self._emitter = self._serializer = self._representer = self
        SafeRepresenter.__init__(
            self, default_style=default_style, default_flow_style=default_flow_style,
        )
        Resolver.__init__(self)


class CDumper(CEmitter, Representer, Resolver):  # type: ignore
    def __init__(
        self: StreamType,
        stream: Any,
        default_style: Any = None,
        default_flow_style: Any = None,
        canonical: Optional[bool] = None,
        indent: Optional[int] = None,
        width: Optional[int] = None,
        allow_unicode: Optional[bool] = None,
        line_break: Any = None,
        encoding: Any = None,
        explicit_start: Optional[bool] = None,
        explicit_end: Optional[bool] = None,
        version: Any = None,
        tags: Any = None,
        block_seq_indent: Any = None,
        top_level_colon_align: Any = None,
        prefix_colon: Any = None,
    ) -> None:
        # NOQA
        CEmitter.__init__(
            self,
            stream,
            canonical=canonical,
            indent=indent,
            width=width,
            encoding=encoding,
            allow_unicode=allow_unicode,
            line_break=line_break,
            explicit_start=explicit_start,
            explicit_end=explicit_end,
            version=version,
            tags=tags,
        )
        self._emitter = self._serializer = self._representer = self
        Representer.__init__(
            self, default_style=default_style, default_flow_style=default_flow_style,
        )
        Resolver.__init__(self)
