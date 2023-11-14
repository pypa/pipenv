# coding: utf-8

from pipenv.vendor.ruamel.yaml.emitter import Emitter
from pipenv.vendor.ruamel.yaml.serializer import Serializer
from pipenv.vendor.ruamel.yaml.representer import (
    Representer,
    SafeRepresenter,
    BaseRepresenter,
    RoundTripRepresenter,
)
from pipenv.vendor.ruamel.yaml.resolver import Resolver, BaseResolver, VersionedResolver

from typing import Any, Dict, List, Union, Optional  # NOQA
from pipenv.vendor.ruamel.yaml.compat import StreamType, VersionType  # NOQA

__all__ = ['BaseDumper', 'SafeDumper', 'Dumper', 'RoundTripDumper']


class BaseDumper(Emitter, Serializer, BaseRepresenter, BaseResolver):
    def __init__(
        self: Any,
        stream: StreamType,
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
        Emitter.__init__(
            self,
            stream,
            canonical=canonical,
            indent=indent,
            width=width,
            allow_unicode=allow_unicode,
            line_break=line_break,
            block_seq_indent=block_seq_indent,
            dumper=self,
        )
        Serializer.__init__(
            self,
            encoding=encoding,
            explicit_start=explicit_start,
            explicit_end=explicit_end,
            version=version,
            tags=tags,
            dumper=self,
        )
        BaseRepresenter.__init__(
            self,
            default_style=default_style,
            default_flow_style=default_flow_style,
            dumper=self,
        )
        BaseResolver.__init__(self, loadumper=self)


class SafeDumper(Emitter, Serializer, SafeRepresenter, Resolver):
    def __init__(
        self,
        stream: StreamType,
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
        Emitter.__init__(
            self,
            stream,
            canonical=canonical,
            indent=indent,
            width=width,
            allow_unicode=allow_unicode,
            line_break=line_break,
            block_seq_indent=block_seq_indent,
            dumper=self,
        )
        Serializer.__init__(
            self,
            encoding=encoding,
            explicit_start=explicit_start,
            explicit_end=explicit_end,
            version=version,
            tags=tags,
            dumper=self,
        )
        SafeRepresenter.__init__(
            self,
            default_style=default_style,
            default_flow_style=default_flow_style,
            dumper=self,
        )
        Resolver.__init__(self, loadumper=self)


class Dumper(Emitter, Serializer, Representer, Resolver):
    def __init__(
        self,
        stream: StreamType,
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
        Emitter.__init__(
            self,
            stream,
            canonical=canonical,
            indent=indent,
            width=width,
            allow_unicode=allow_unicode,
            line_break=line_break,
            block_seq_indent=block_seq_indent,
            dumper=self,
        )
        Serializer.__init__(
            self,
            encoding=encoding,
            explicit_start=explicit_start,
            explicit_end=explicit_end,
            version=version,
            tags=tags,
            dumper=self,
        )
        Representer.__init__(
            self,
            default_style=default_style,
            default_flow_style=default_flow_style,
            dumper=self,
        )
        Resolver.__init__(self, loadumper=self)


class RoundTripDumper(Emitter, Serializer, RoundTripRepresenter, VersionedResolver):
    def __init__(
        self,
        stream: StreamType,
        default_style: Any = None,
        default_flow_style: Optional[bool] = None,
        canonical: Optional[int] = None,
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
        Emitter.__init__(
            self,
            stream,
            canonical=canonical,
            indent=indent,
            width=width,
            allow_unicode=allow_unicode,
            line_break=line_break,
            block_seq_indent=block_seq_indent,
            top_level_colon_align=top_level_colon_align,
            prefix_colon=prefix_colon,
            dumper=self,
        )
        Serializer.__init__(
            self,
            encoding=encoding,
            explicit_start=explicit_start,
            explicit_end=explicit_end,
            version=version,
            tags=tags,
            dumper=self,
        )
        RoundTripRepresenter.__init__(
            self,
            default_style=default_style,
            default_flow_style=default_flow_style,
            dumper=self,
        )
        VersionedResolver.__init__(self, loader=self)
